"""Generate phrase candidates from semordnilap piece pairs."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from semordnilap.phrases.application import (
    GeneratePhrasesCommand,
    run_generation,
)
from semordnilap.phrases.cli.configuration import (
    optional_path,
    required_path,
    resolve_generation_config,
    string_list,
)
from semordnilap.phrases.cli.logging import configure_logging
from semordnilap.phrases.domain import GeneratePhrasePolicy, PhraseSearchTrace
from semordnilap.phrases.infrastructure import (
    TsvPhraseRepository,
    build_plausibility_scorer,
    build_syntax_annotator,
)


logger = logging.getLogger(__name__)


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        "Generate phrase candidates from semordnilap pairs"
    )
    add_generation_options(parser, include_io=True)
    return parser


def add_generation_options(
    parser: argparse.ArgumentParser,
    *,
    include_io: bool,
) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional OmegaConf YAML file for phrase generation settings.",
    )
    if include_io:
        parser.add_argument("--input", type=Path, default=None)
        parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--min-source-count", type=int, default=None)
    parser.add_argument("--min-target-count", type=int, default=None)
    parser.add_argument("--min-pair-score", type=float, default=None)
    parser.add_argument("--max-source-n", type=int, default=None)
    parser.add_argument("--max-target-n", type=int, default=None)
    parser.add_argument(
        "--piece-limit",
        type=int,
        default=None,
        help="Keep only the top N pieces after filtering.",
    )
    parser.add_argument("--min-pieces", type=int, default=None)
    parser.add_argument("--max-pieces", type=int, default=None)
    parser.add_argument("--beam-size", type=int, default=None)
    parser.add_argument(
        "--candidate-pool-size",
        type=int,
        default=None,
        help=(
            "Maximum unique expanded candidates kept per level before beam "
            "selection. Defaults to 4 * beam-size."
        ),
    )
    parser.add_argument("--max-results", type=int, default=None)
    parser.add_argument(
        "--expand-sides",
        choices=["both", "right", "left", "center"],
        default=None,
        help="Which side of the source piece sequence can be expanded.",
    )
    parser.add_argument(
        "--center-seed-limit",
        type=int,
        default=None,
        help="How many top pieces can initialize center-out growth.",
    )
    parser.add_argument(
        "--allow-repeated-pieces",
        action="store_true",
        default=None,
    )
    parser.add_argument(
        "--keep-permutations",
        action="store_true",
        default=None,
        help="Keep different orderings of the same piece set.",
    )
    parser.add_argument(
        "--pair-weight",
        type=float,
        default=None,
        help="Weight for the source pair quality signal.",
    )
    parser.add_argument(
        "--fluency-weight",
        type=float,
        default=None,
        help="Weight for KenLM fluency. Defaults to 1.0 when an LM is passed.",
    )
    parser.add_argument("--syntax-weight", type=float, default=None)
    parser.add_argument("--morphology-weight", type=float, default=None)
    parser.add_argument("--partial-viability-weight", type=float, default=None)
    parser.add_argument("--completion-weight", type=float, default=None)
    parser.add_argument("--dead-end-weight", type=float, default=None)
    parser.add_argument("--boundary-weight", type=float, default=None)
    parser.add_argument("--edge-compatibility-weight", type=float, default=None)
    parser.add_argument("--min-completion-score", type=float, default=None)
    parser.add_argument(
        "--min-partial-viability",
        type=float,
        default=None,
    )
    completion_group = parser.add_mutually_exclusive_group()
    completion_group.add_argument(
        "--forbid-low-completion-final",
        dest="forbid_low_completion_final",
        action="store_true",
        default=None,
        help="Reject final candidates below --min-completion-score.",
    )
    completion_group.add_argument(
        "--allow-low-completion-final",
        dest="forbid_low_completion_final",
        action="store_false",
        default=None,
        help="Allow fragmentary finals even when completion evidence is weak.",
    )
    parser.add_argument("--repeat-penalty", type=float, default=None)
    parser.add_argument("--complete-bonus", type=float, default=None)
    parser.add_argument("--source-lang", default=None)
    parser.add_argument("--target-lang", default=None)
    parser.add_argument("--source-lm", type=Path, default=None)
    parser.add_argument("--target-lm", type=Path, default=None)
    parser.add_argument(
        "--source-spacy-model",
        default=None,
        help="Optional spaCy model name for source-language POS tagging.",
    )
    parser.add_argument(
        "--target-spacy-model",
        default=None,
        help="Optional spaCy model name for target-language POS tagging.",
    )
    parser.add_argument("--source-boundary-model", type=Path, default=None)
    parser.add_argument("--target-boundary-model", type=Path, default=None)
    parser.add_argument("--source-transition-model", type=Path, default=None)
    parser.add_argument("--target-transition-model", type=Path, default=None)
    parser.add_argument(
        "--disable-syntax",
        action="store_true",
        default=None,
        help="Disable model-backed POS/morphology graph annotations.",
    )
    parser.add_argument(
        "--morphology-agreement-features",
        default=None,
        help=(
            "Comma-separated spaCy morph features checked for agreement, "
            "for example Gender,Number or Gender,Number,Tense."
        ),
    )
    parser.add_argument(
        "--trace-out",
        type=Path,
        default=None,
        help=(
            "Optional JSON file with beam evolution, top growth/final "
            "candidates, and selected graph edges."
        ),
    )
    parser.add_argument(
        "--trace-top-n",
        type=int,
        default=None,
        help="How many candidates per trace section to keep.",
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        default=None,
        help="Console log verbosity. Use debug for beam-level details.",
    )
    parser.add_argument(
        "--log-color",
        choices=["auto", "always", "never"],
        default=None,
        help="Color log levels with ANSI colors.",
    )


def command_from_args(args: argparse.Namespace) -> GeneratePhrasesCommand:
    config = resolve_generation_config(args)
    return command_from_config(config)


def command_from_config(config) -> GeneratePhrasesCommand:
    search = config.search
    scoring = config.scoring
    models = config.models

    if search.min_source_count < 1:
        raise ValueError("--min-source-count must be at least 1")
    if search.min_target_count < 1:
        raise ValueError("--min-target-count must be at least 1")
    if search.max_source_n < 1:
        raise ValueError("--max-source-n must be at least 1")
    if search.max_target_n < 1:
        raise ValueError("--max-target-n must be at least 1")
    if search.piece_limit < 1:
        raise ValueError("--piece-limit must be at least 1")
    if search.beam_size < 1:
        raise ValueError("--beam-size must be at least 1")
    if (
        search.candidate_pool_size is not None
        and search.candidate_pool_size < search.beam_size
    ):
        raise ValueError("--candidate-pool-size must be >= --beam-size")
    if search.max_results < 1:
        raise ValueError("--max-results must be at least 1")
    if search.min_pieces < 1:
        raise ValueError("--min-pieces must be at least 1")
    if search.max_pieces < search.min_pieces:
        raise ValueError("--max-pieces must be >= --min-pieces")
    if config.output.trace_top_n < 1:
        raise ValueError("--trace-top-n must be at least 1")
    if search.center_seed_limit < 1:
        raise ValueError("--center-seed-limit must be at least 1")
    for option_name in [
        "pair_weight",
        "syntax_weight",
        "morphology_weight",
        "partial_viability_weight",
        "completion_weight",
        "dead_end_weight",
        "boundary_weight",
        "edge_compatibility_weight",
        "repeat_penalty",
        "complete_bonus",
    ]:
        if getattr(scoring, option_name) < 0:
            raise ValueError(f"--{option_name.replace('_', '-')} must be >= 0")
    if scoring.fluency_weight is not None and scoring.fluency_weight < 0:
        raise ValueError("--fluency-weight must be >= 0")
    morphology_agreement_features = string_list(
        scoring.morphology_agreement_features
    )

    has_language_model = (
        models.source_lm is not None or models.target_lm is not None
    )
    fluency_weight = scoring.fluency_weight
    if fluency_weight is None:
        fluency_weight = 1.0 if has_language_model else 0.0

    policy = GeneratePhrasePolicy(
        min_source_count=search.min_source_count,
        min_target_count=search.min_target_count,
        min_pair_score=search.min_pair_score,
        max_source_n=search.max_source_n,
        max_target_n=search.max_target_n,
        piece_limit=search.piece_limit,
        min_pieces=search.min_pieces,
        max_pieces=search.max_pieces,
        beam_size=search.beam_size,
        candidate_pool_size=search.candidate_pool_size,
        max_results=search.max_results,
        expand_sides=search.expand_sides,
        allow_repeated_pieces=search.allow_repeated_pieces,
        collapse_permutations=not search.keep_permutations,
        pair_weight=scoring.pair_weight,
        fluency_weight=fluency_weight,
        syntax_weight=scoring.syntax_weight,
        morphology_weight=scoring.morphology_weight,
        partial_viability_weight=scoring.partial_viability_weight,
        completion_weight=scoring.completion_weight,
        dead_end_weight=scoring.dead_end_weight,
        boundary_weight=scoring.boundary_weight,
        edge_compatibility_weight=scoring.edge_compatibility_weight,
        min_completion_score=scoring.min_completion_score,
        min_partial_viability=scoring.min_partial_viability,
        forbid_low_completion_final=scoring.forbid_low_completion_final,
        center_seed_limit=search.center_seed_limit,
        source_boundary_model=optional_path(models.source_boundary_model),
        target_boundary_model=optional_path(models.target_boundary_model),
        source_transition_model=optional_path(models.source_transition_model),
        target_transition_model=optional_path(models.target_transition_model),
        repeat_penalty=scoring.repeat_penalty,
        complete_bonus=scoring.complete_bonus,
        morphology_agreement_features=morphology_agreement_features,
    )
    return GeneratePhrasesCommand(
        input_path=required_path(config, "input"),
        output_path=required_path(config, "out"),
        policy=policy,
    )


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = build_argparser().parse_args(argv)
    return run_from_args(args)


def run_from_args(args: argparse.Namespace) -> int:
    config = resolve_generation_config(args)
    configure_logging(config.logging.level, config.logging.color)
    command = command_from_config(config)

    logger.info(
        "Generating phrases: %s -> %s",
        command.input_path,
        command.output_path,
    )
    logger.info(
        "Search settings: pieces=%d..%d beam=%d limit=%d expand=%s",
        command.policy.min_pieces,
        command.policy.max_pieces,
        command.policy.beam_size,
        command.policy.max_results,
        command.policy.expand_sides,
    )
    if any(
        model_path is not None
        for model_path in (
            command.policy.source_boundary_model,
            command.policy.target_boundary_model,
            command.policy.source_transition_model,
            command.policy.target_transition_model,
        )
    ):
        logger.warning(
            "External boundary/transition model loading is not implemented yet; "
            "using built-in parser-backed phrase diagnostics."
        )
    logger.debug("Policy: %s", command.policy)

    plausibility_scorer = build_plausibility_scorer(
        source_lang=config.language.source,
        source_lm=optional_path(config.models.source_lm),
        target_lang=config.language.target,
        target_lm=optional_path(config.models.target_lm),
    )
    syntax_annotator = build_syntax_annotator(
        source_lang=config.language.source,
        target_lang=config.language.target,
        source_spacy_model=config.models.source_spacy_model,
        target_spacy_model=config.models.target_spacy_model,
        enabled=not config.models.disable_syntax,
    )
    trace = (
        PhraseSearchTrace(top_limit=config.output.trace_top_n)
        if config.output.trace_out is not None
        else None
    )
    generated = run_generation(
        command,
        TsvPhraseRepository(),
        plausibility_scorer=plausibility_scorer,
        syntax_annotator=syntax_annotator,
        trace=trace,
    )
    trace_out = optional_path(config.output.trace_out)
    if trace is not None and trace_out is not None:
        trace_out.parent.mkdir(parents=True, exist_ok=True)
        with trace_out.open("w", encoding="utf-8") as f:
            json.dump(trace.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info("Wrote phrase search trace to %s", trace_out)
    logger.debug("Generated %d phrase candidates", generated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
