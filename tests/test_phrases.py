import csv
import logging
from pathlib import Path

import pytest

from semordnilap.phrases.application import (
    GeneratePhrasesCommand,
    run_generation,
)
from semordnilap.phrases.cli.generate import command_from_args
from semordnilap.phrases.cli.main import build_argparser as build_phrase_cli
from semordnilap.phrases.domain import (
    GeneratePhrasePolicy,
    PhraseCandidate,
    PhraseScoringContext,
    PhraseSearchTrace,
    PhrasePiece,
    PieceSyntax,
    TextSyntax,
    TokenSyntax,
    bilingual_min,
    completion_score,
    edge_compatibility_score,
    generate_phrase_candidates,
    partial_viability_score,
    score_final,
    should_keep_final,
)
from semordnilap.phrases.infrastructure import (
    TsvPhraseRepository,
    build_plausibility_scorer,
    build_syntax_annotator,
)
from semordnilap.scoring import score_semordnilap_pair


def piece(
    id,
    source_text,
    target_text,
    source_norm_key,
    target_norm_key,
    *,
    pair_score=10.0,
    source_count=100,
    target_count=100,
):
    return PhrasePiece(
        id=id,
        source_text=source_text,
        target_text=target_text,
        pair_score=pair_score,
        source_count=source_count,
        target_count=target_count,
        source_n=len(source_text.split()),
        target_n=len(target_text.split()),
        source_norm_key=source_norm_key,
        target_norm_key=target_norm_key,
        source_lang="es",
        target_lang="pt",
    )


class FakeSyntaxAnnotator:
    def __init__(self, syntax_by_piece: dict[int, PieceSyntax]) -> None:
        self._syntax_by_piece = syntax_by_piece

    def annotate(self, pieces: list[PhrasePiece]) -> dict[int, PieceSyntax]:
        return {
            item.id: self._syntax_by_piece[item.id]
            for item in pieces
            if item.id in self._syntax_by_piece
        }


def text_syntax(
    tags: tuple[str, ...] = (),
    *,
    deps: tuple[str, ...] = (),
    morphs: tuple[dict[str, tuple[str, ...]], ...] = (),
) -> TextSyntax:
    deps = deps or ("",) * len(tags)
    morphs = morphs or ({},) * len(tags)
    return TextSyntax(
        tokens=tuple(
            TokenSyntax(
                text=f"t{index}",
                lemma=f"t{index}",
                pos=tag,
                dep=deps[index],
                morph=tuple(sorted(morphs[index].items())),
            )
            for index, tag in enumerate(tags)
        ),
    )


def piece_syntax(
    piece_id: int,
    source_tags: tuple[str, ...] = (),
    target_tags: tuple[str, ...] = (),
    *,
    source_deps: tuple[str, ...] = (),
    target_deps: tuple[str, ...] = (),
    source_morphs: tuple[dict[str, tuple[str, ...]], ...] = (),
    target_morphs: tuple[dict[str, tuple[str, ...]], ...] = (),
) -> PieceSyntax:
    return PieceSyntax(
        piece_id=piece_id,
        source=text_syntax(source_tags, deps=source_deps, morphs=source_morphs),
        target=text_syntax(target_tags, deps=target_deps, morphs=target_morphs),
    )


def write_pairs(path: Path) -> None:
    fieldnames = [
        "source_lang",
        "source_corpus",
        "source_text",
        "source_n",
        "source_count",
        "source_norm_key",
        "target_lang",
        "target_corpus",
        "target_text",
        "target_n",
        "target_count",
        "target_norm_key",
    ]
    rows = [
        {
            "source_lang": "es",
            "source_corpus": "wiki",
            "source_text": "se le",
            "source_n": "2",
            "source_count": "150",
            "source_norm_key": "sele",
            "target_lang": "pt",
            "target_corpus": "wiki",
            "target_text": "eles",
            "target_n": "1",
            "target_count": "120",
            "target_norm_key": "eles",
        },
        {
            "source_lang": "es",
            "source_corpus": "wiki",
            "source_text": "no se",
            "source_n": "2",
            "source_count": "140",
            "source_norm_key": "nose",
            "target_lang": "pt",
            "target_corpus": "wiki",
            "target_text": "e son",
            "target_n": "2",
            "target_count": "130",
            "target_norm_key": "eson",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def test_generation_builds_reversed_target_order():
    candidates = generate_phrase_candidates(
        [
            piece(1, "se le", "eles", "sele", "eles"),
            piece(2, "no se", "e son", "nose", "eson"),
        ],
        GeneratePhrasePolicy(
            min_source_count=1,
            min_target_count=1,
            min_pieces=2,
            max_pieces=2,
            piece_limit=10,
            beam_size=10,
            max_results=10,
        ),
    )

    assert candidates[0].source_phrase == "se le no se"
    assert candidates[0].target_phrase == "e son eles"
    assert candidates[0].formal_ok


def test_tsv_phrase_generation_roundtrip(tmp_path):
    input_path = tmp_path / "pairs.tsv"
    output_path = tmp_path / "phrases.tsv"
    write_pairs(input_path)
    command = GeneratePhrasesCommand(
        input_path=input_path,
        output_path=output_path,
        policy=GeneratePhrasePolicy(
            min_source_count=100,
            min_target_count=100,
            min_pieces=2,
            max_pieces=2,
            piece_limit=10,
            beam_size=10,
            max_results=10,
        ),
    )

    exported = run_generation(command, TsvPhraseRepository())

    rows = list(csv.DictReader(output_path.open(encoding="utf-8"), delimiter="\t"))
    assert exported == 1
    assert rows[0]["formal_ok"] == "True"
    assert "growth_score" in rows[0]
    assert "syntax_score" in rows[0]
    assert "bilingual_completion_score" in rows[0]
    assert "edge_compatibility_score" in rows[0]
    assert "hub_penalty" not in rows[0]


def test_tsv_phrase_repository_recomputes_pair_score(tmp_path):
    input_path = tmp_path / "pairs.tsv"
    write_pairs(input_path)

    pieces = TsvPhraseRepository().load_pieces(input_path)

    assert pieces[0].pair_score == score_semordnilap_pair(150, 120)


def test_syntax_annotator_without_models_does_not_tag_pos():
    annotator = build_syntax_annotator(source_lang="es", target_lang="pt")

    annotations = annotator.annotate(
        [piece(1, "si es sopa", "após seis", "siessopa", "aposseis")]
    )

    assert annotations == {}


def test_missing_plausibility_models_log_scoring_warning(caplog):
    caplog.set_level(logging.WARNING)

    scorer = build_plausibility_scorer(
        source_lang="es",
        source_lm=None,
        target_lang="pt",
        target_lm=None,
    )

    assert scorer.score("roma", "es") == 0.0
    assert "No KenLM models loaded" in caplog.text
    assert "fluency does not affect ranking" in caplog.text


def test_missing_tagging_models_log_syntax_warning(caplog):
    caplog.set_level(logging.WARNING)

    annotator = build_syntax_annotator(source_lang="es", target_lang="pt")

    assert annotator.annotate([]) == {}
    assert "No spaCy tagging models loaded" in caplog.text
    assert "morphology penalties stay at 0.0" in caplog.text


def test_phrase_policy_defaults_to_simple_left_to_right_beam():
    policy = GeneratePhrasePolicy()

    assert policy.expand_sides == "right"
    assert policy.beam_size == 1000
    assert policy.pair_weight == 1.0


def test_phrase_cli_uses_generate_subcommand():
    parser = build_phrase_cli()

    generate_args = parser.parse_args(
        [
            "generate",
            "--input",
            "pairs.tsv",
            "--out",
            "phrases.tsv",
            "--morphology-weight",
            "2",
            "--morphology-agreement-features",
            "Gender,Number,Tense",
            "--log-level",
            "debug",
            "--log-color",
            "never",
            "--expand-sides",
            "center",
            "--center-seed-limit",
            "50",
            "--partial-viability-weight",
            "1.5",
            "--allow-low-completion-final",
        ]
    )

    assert generate_args.command == "generate"
    assert generate_args.morphology_weight == 2
    assert generate_args.log_level == "debug"
    assert generate_args.log_color == "never"
    assert generate_args.expand_sides == "center"
    assert generate_args.center_seed_limit == 50
    assert generate_args.partial_viability_weight == 1.5
    assert generate_args.forbid_low_completion_final is False


def test_phrase_yaml_config_builds_command(tmp_path):
    input_path = tmp_path / "pairs.tsv"
    output_path = tmp_path / "phrases.tsv"
    trace_path = tmp_path / "trace.json"
    config_path = tmp_path / "phrases.yaml"
    config_path.write_text(
        f"""
input: {input_path}
out: {output_path}
language:
  source: es
  target: pt
search:
  min_source_count: 1
  min_target_count: 1
  min_pieces: 3
  max_pieces: 5
  beam_size: 77
  candidate_pool_size: 100
  expand_sides: center
  center_seed_limit: 9
scoring:
  morphology_agreement_features:
    - Gender
    - Number
    - Tense
  completion_weight: 1.7
  forbid_low_completion_final: false
output:
  trace_out: {trace_path}
  trace_top_n: 4
logging:
  level: debug
  color: never
""",
        encoding="utf-8",
    )
    parser = build_phrase_cli()

    args = parser.parse_args(["generate", "--config", str(config_path)])
    command = command_from_args(args)

    assert command.input_path == input_path
    assert command.output_path == output_path
    assert command.policy.expand_sides == "center"
    assert command.policy.beam_size == 77
    assert command.policy.candidate_pool_size == 100
    assert command.policy.center_seed_limit == 9
    assert command.policy.completion_weight == 1.7
    assert command.policy.forbid_low_completion_final is False
    assert command.policy.morphology_agreement_features == (
        "Gender",
        "Number",
        "Tense",
    )


def test_full_default_phrase_yaml_template_builds_command():
    parser = build_phrase_cli()
    config_path = Path("src/semordnilap/phrases/config/default.yaml.template")

    args = parser.parse_args(["generate", "--config", str(config_path)])
    command = command_from_args(args)

    assert command.input_path == Path("data/search/example_pairs.tsv")
    assert command.output_path == Path("data/search/example.phrases.tsv")
    assert command.policy.beam_size == 1000
    assert command.policy.candidate_pool_size is None
    assert command.policy.min_partial_viability == float("-inf")


def test_phrase_cli_flags_override_yaml_config(tmp_path):
    config_path = tmp_path / "phrases.yaml"
    config_path.write_text(
        f"""
input: {tmp_path / "pairs.tsv"}
out: {tmp_path / "phrases.tsv"}
search:
  beam_size: 10
  candidate_pool_size: 40
  expand_sides: right
scoring:
  completion_weight: 0.5
  forbid_low_completion_final: false
""",
        encoding="utf-8",
    )
    parser = build_phrase_cli()

    args = parser.parse_args(
        [
            "generate",
            "--config",
            str(config_path),
            "--beam-size",
            "20",
            "--candidate-pool-size",
            "80",
            "--expand-sides",
            "both",
            "--completion-weight",
            "2.0",
            "--forbid-low-completion-final",
        ]
    )
    command = command_from_args(args)

    assert command.policy.beam_size == 20
    assert command.policy.candidate_pool_size == 80
    assert command.policy.expand_sides == "both"
    assert command.policy.completion_weight == 2.0
    assert command.policy.forbid_low_completion_final is True


def test_candidate_pool_caps_expanded_candidates_in_trace():
    trace = PhraseSearchTrace(top_limit=20)
    pieces = [
        piece(index, str(index), str(index), str(index), str(index))
        for index in range(1, 16)
    ]

    generate_phrase_candidates(
        pieces,
        GeneratePhrasePolicy(
            min_source_count=1,
            min_target_count=1,
            min_pieces=2,
            max_pieces=2,
            piece_limit=20,
            beam_size=5,
            candidate_pool_size=7,
            max_results=10,
            collapse_permutations=False,
        ),
        trace=trace,
    )
    payload = trace.to_dict()
    level = payload["levels"][-1]

    assert level["expanded_count"] > 7
    assert level["expanded_pool_size"] == 7
    assert len(level["top_growth"]) == 7


def test_plausibility_scorer_affects_phrase_score():
    class FakeScorer:
        def score(self, text, lang):
            if text == "se le no se" or text == "e son eles":
                return 10.0
            return 0.0

    pieces = [
        piece(1, "se le", "eles", "sele", "eles"),
        piece(2, "no se", "e son", "nose", "eson"),
    ]

    without_plausibility = generate_phrase_candidates(
        pieces,
        GeneratePhrasePolicy(
            min_source_count=1,
            min_target_count=1,
            min_pieces=2,
            max_pieces=2,
            piece_limit=10,
            beam_size=10,
            max_results=10,
            fluency_weight=0.0,
        ),
        plausibility_scorer=FakeScorer(),
    )
    with_plausibility = generate_phrase_candidates(
        pieces,
        GeneratePhrasePolicy(
            min_source_count=1,
            min_target_count=1,
            min_pieces=2,
            max_pieces=2,
            piece_limit=10,
            beam_size=10,
            max_results=10,
            fluency_weight=1.0,
        ),
        plausibility_scorer=FakeScorer(),
    )

    assert with_plausibility[0].score == pytest.approx(
        without_plausibility[0].score + 10.0
    )


def test_generation_can_expand_on_the_left_when_requested():
    pieces = [
        piece(1, "roma", "amor", "roma", "amor", pair_score=1.0),
        piece(2, "si es", "seis", "sies", "seis", pair_score=10.0),
    ]

    candidates = generate_phrase_candidates(
        pieces,
        GeneratePhrasePolicy(
            min_source_count=1,
            min_target_count=1,
            min_pieces=2,
            max_pieces=2,
            piece_limit=10,
            beam_size=2,
            max_results=10,
            expand_sides="both",
            collapse_permutations=False,
        ),
    )

    assert any(candidate.source_phrase == "roma si es" for candidate in candidates)
    assert any(candidate.last_expansion_side == "left" for candidate in candidates)


def test_generation_trace_records_two_score_types():
    trace = PhraseSearchTrace(top_limit=3)
    pieces = [
        piece(1, "roma", "amor", "roma", "amor", pair_score=10.0),
        piece(2, "sale", "elas", "sale", "elas", pair_score=9.0),
    ]

    candidates = generate_phrase_candidates(
        pieces,
        GeneratePhrasePolicy(
            min_source_count=1,
            min_target_count=1,
            min_pieces=2,
            max_pieces=2,
            piece_limit=10,
            beam_size=10,
            max_results=10,
        ),
        trace=trace,
    )
    payload = trace.to_dict()

    assert candidates
    assert payload["search"]["policy"]["expand_sides"] == "right"
    assert payload["levels"][-1]["top_growth"]
    assert payload["final"]["top_results"]
    top = payload["final"]["top_results"][0]
    assert "bilingual_partial_viability" in top
    assert "bilingual_completion_score" in top
    assert "diagnostic_flags" in top


def test_center_out_growth_preserves_reversible_order():
    pieces = [
        piece(1, "C", "C", "c", "c", pair_score=10.0),
        piece(2, "L", "L", "l", "l", pair_score=9.0),
        piece(3, "R", "R", "r", "r", pair_score=8.0),
    ]

    candidates = generate_phrase_candidates(
        pieces,
        GeneratePhrasePolicy(
            min_source_count=1,
            min_target_count=1,
            min_pieces=3,
            max_pieces=3,
            piece_limit=10,
            beam_size=50,
            max_results=50,
            expand_sides="center",
            center_seed_limit=1,
            collapse_permutations=False,
        ),
    )

    candidate = next(
        item for item in candidates if item.source_phrase == "L C R"
    )
    assert candidate.target_phrase == "R C L"
    assert candidate.piece_count == 3
    assert candidate.growth_mode == "center"
    assert candidate.left_piece_ids == (2,)
    assert candidate.center_piece_ids == (1,)
    assert candidate.right_piece_ids == (3,)


def test_low_completion_final_is_rejected():
    candidate = PhraseCandidate(
        pieces=(piece(1, "x", "x", "x", "x"),),
        score=0.0,
        bilingual_completion_score=-0.1,
    )
    policy = GeneratePhrasePolicy(min_completion_score=0.0)

    assert should_keep_final(candidate, policy) is False
    assert should_keep_final(
        candidate,
        GeneratePhrasePolicy(forbid_low_completion_final=False),
    )


def test_bilingual_completion_uses_weaker_side():
    assert bilingual_min(0.9, -0.2) == -0.2


def test_partial_viability_does_not_require_completion():
    syntax = list(text_syntax(("DET",)).tokens)

    assert partial_viability_score(syntax) > completion_score(syntax)


def test_edge_compatibility_uses_pos_boundary():
    good = edge_compatibility_score(
        "a",
        "b",
        text_syntax(("ADP",)),
        text_syntax(("NOUN",)),
    )
    bad = edge_compatibility_score(
        "a",
        "b",
        text_syntax(("DET",)),
        text_syntax(("DET",)),
    )

    assert good > bad


def test_model_morphology_agreement_demotes_number_mismatch():
    bad = (
        piece(1, "rolo livres", "rolo livres", "rololivres", "serverlolor"),
    )
    good = (
        piece(2, "rolo livre", "rolo livre", "rololivre", "ervilolor"),
    )
    pieces = [*bad, *good]
    singular_noun = {"Gender": ("Masc",), "Number": ("Sing",)}
    singular_adj = {"Gender": ("Masc",), "Number": ("Sing",)}
    plural_adj = {"Gender": ("Masc",), "Number": ("Plur",)}
    syntax = {
        1: piece_syntax(
            1,
            ("NOUN", "ADJ"),
            ("NOUN", "ADJ"),
            source_morphs=(singular_noun, plural_adj),
            target_morphs=(singular_noun, plural_adj),
        ),
        2: piece_syntax(
            2,
            ("NOUN", "ADJ"),
            ("NOUN", "ADJ"),
            source_morphs=(singular_noun, singular_adj),
            target_morphs=(singular_noun, singular_adj),
        ),
    }
    context = PhraseScoringContext.from_pieces(pieces, syntax)
    policy = GeneratePhrasePolicy(
        min_source_count=1,
        min_target_count=1,
        min_pieces=1,
        pair_weight=0.0,
        syntax_weight=0.0,
        morphology_weight=2.0,
        complete_bonus=0.0,
    )

    bad_score = score_final(
        pieces=bad,
        policy=policy,
        context=context,
        source_plausibility=0.0,
        target_plausibility=0.0,
    )
    good_score = score_final(
        pieces=good,
        policy=policy,
        context=context,
        source_plausibility=0.0,
        target_plausibility=0.0,
    )

    assert good_score > bad_score


def test_model_dependency_clause_completeness_improves_final_score():
    complete = (
        piece(
            1,
            "ella abre puerta",
            "ela abre porta",
            "ellaabrepuerta",
            "atrop",
            pair_score=10.0,
        ),
    )
    incomplete = (
        piece(2, "abre", "abre", "abre", "erba", pair_score=10.0),
    )
    pieces = [*complete, *incomplete]
    syntax = {
        1: piece_syntax(
            1,
            ("PRON", "VERB", "NOUN"),
            ("PRON", "VERB", "NOUN"),
            source_deps=("nsubj", "ROOT", "obj"),
            target_deps=("nsubj", "ROOT", "obj"),
        ),
        2: piece_syntax(
            2,
            ("VERB",),
            ("VERB",),
            source_deps=("ROOT",),
            target_deps=("ROOT",),
        ),
    }
    context = PhraseScoringContext.from_pieces(pieces, syntax)
    policy = GeneratePhrasePolicy(
        min_source_count=1,
        min_target_count=1,
        min_pieces=1,
        pair_weight=0.0,
        syntax_weight=1.0,
        morphology_weight=0.0,
        complete_bonus=0.0,
    )

    complete_score = score_final(
        pieces=complete,
        policy=policy,
        context=context,
        source_plausibility=0.0,
        target_plausibility=0.0,
    )
    incomplete_score = score_final(
        pieces=incomplete,
        policy=policy,
        context=context,
        source_plausibility=0.0,
        target_plausibility=0.0,
    )

    assert complete_score > incomplete_score
