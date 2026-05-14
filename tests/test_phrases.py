import csv
import json
from pathlib import Path

from semordnilap.phrases.application import (
    GeneratePhrasesCommand,
    run_generation,
)
from semordnilap.phrases.domain import (
    GeneratePhrasePolicy,
    PhrasePiece,
    generate_phrase_candidates,
)
from semordnilap.phrases.infrastructure import TsvPhraseRepository


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
        "pair_score",
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
            "pair_score": "9.0",
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
            "target_count": "110",
            "target_norm_key": "eson",
            "pair_score": "8.0",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def test_generate_phrase_candidates_builds_reversed_target_order():
    pieces = [
        piece(1, "se le", "eles", "sele", "eles"),
        piece(2, "no se", "e son", "nose", "eson"),
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
    )

    assert candidates
    assert candidates[0].formal_ok
    assert {piece.id for piece in candidates[0].pieces} == {1, 2}
    assert candidates[0].source_norm_key == candidates[0].target_norm_key[::-1]


def test_generation_filters_rare_pieces():
    pieces = [
        piece(1, "se le", "eles", "sele", "eles", source_count=200),
        piece(2, "no se", "e son", "nose", "eson", source_count=1),
    ]

    candidates = generate_phrase_candidates(
        pieces,
        GeneratePhrasePolicy(
            min_source_count=100,
            min_target_count=1,
            min_pieces=2,
            max_pieces=2,
            allow_repeated_pieces=False,
        ),
    )

    assert candidates == []


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

    with output_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    assert exported == 1
    assert rows[0]["formal_ok"] == "True"
    assert json.loads(rows[0]["pieces"])
    assert json.loads(rows[0]["piece_ids"])


def test_generation_collapses_permutations_by_default():
    pieces = [
        piece(1, "se le", "eles", "sele", "eles"),
        piece(2, "no se", "e son", "nose", "eson"),
    ]

    collapsed = generate_phrase_candidates(
        pieces,
        GeneratePhrasePolicy(
            min_source_count=1,
            min_target_count=1,
            min_pieces=2,
            max_pieces=2,
            piece_limit=10,
            beam_size=10,
            max_results=10,
            collapse_permutations=True,
        ),
    )
    kept = generate_phrase_candidates(
        pieces,
        GeneratePhrasePolicy(
            min_source_count=1,
            min_target_count=1,
            min_pieces=2,
            max_pieces=2,
            piece_limit=10,
            beam_size=10,
            max_results=10,
            collapse_permutations=False,
        ),
    )

    assert len(collapsed) == 1
    assert len(kept) == 2


def test_generation_penalizes_reciprocal_piece_pairs():
    normal = (
        piece(1, "se le", "eles", "sele", "eles"),
        piece(2, "no se", "e son", "nose", "eson"),
    )
    reciprocal = (
        piece(3, "roma", "amor", "roma", "amor"),
        piece(4, "amor", "roma", "amor", "roma"),
    )
    policy = GeneratePhrasePolicy(
        min_source_count=1,
        min_target_count=1,
        reciprocal_penalty=12.0,
        fragment_penalty=0.0,
    )

    normal_candidates = generate_phrase_candidates(
        list(normal),
        policy,
    )
    reciprocal_candidates = generate_phrase_candidates(
        list(reciprocal),
        policy,
    )

    assert normal_candidates[0].score > reciprocal_candidates[0].score


def test_generation_penalizes_fragment_pieces():
    fragment = (
        piece(1, "se le", "eles", "sele", "eles"),
        piece(2, "no se", "e son", "nose", "eson"),
    )
    content = (
        piece(3, "roma", "amor", "roma", "amor"),
        piece(4, "aires", "seria", "aires", "seria"),
    )
    policy = GeneratePhrasePolicy(
        min_source_count=1,
        min_target_count=1,
        reciprocal_penalty=0.0,
        fragment_penalty=6.0,
    )

    fragment_candidates = generate_phrase_candidates(list(fragment), policy)
    content_candidates = generate_phrase_candidates(list(content), policy)

    assert content_candidates[0].score > fragment_candidates[0].score


def test_plausibility_scorer_affects_phrase_score():
    class FakeScorer:
        def score(self, text, lang):
            if text == "se le no se":
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
            collapse_permutations=False,
            plausibility_weight=0.0,
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
            collapse_permutations=False,
            plausibility_weight=1.0,
        ),
        plausibility_scorer=FakeScorer(),
    )

    best_without = max(
        candidate.score
        for candidate in without_plausibility
        if candidate.source_phrase == "se le no se"
    )
    best_with = max(
        candidate.score
        for candidate in with_plausibility
        if candidate.source_phrase == "se le no se"
    )

    assert best_with == best_without + 10.0
    assert any(
        candidate.source_plausibility == 10.0
        for candidate in with_plausibility
    )
