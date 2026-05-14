"""Generate phrase candidates from semordnilap piece pairs."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from semordnilap.phrases.application import (
    GeneratePhrasesCommand,
    run_generation,
)
from semordnilap.phrases.domain import GeneratePhrasePolicy
from semordnilap.phrases.infrastructure import (
    TsvPhraseRepository,
    build_plausibility_scorer,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        "Generate phrase candidates from semordnilap pairs"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-source-count", type=int, default=100)
    parser.add_argument("--min-target-count", type=int, default=100)
    parser.add_argument("--min-pair-score", type=float, default=0.0)
    parser.add_argument("--max-source-n", type=int, default=3)
    parser.add_argument("--max-target-n", type=int, default=3)
    parser.add_argument(
        "--piece-limit",
        type=int,
        default=1000,
        help="Keep only the top N pieces after filtering.",
    )
    parser.add_argument("--min-pieces", type=int, default=2)
    parser.add_argument("--max-pieces", type=int, default=2)
    parser.add_argument("--beam-size", type=int, default=500)
    parser.add_argument("--max-results", type=int, default=500)
    parser.add_argument("--allow-repeated-pieces", action="store_true")
    parser.add_argument(
        "--keep-permutations",
        action="store_true",
        help="Keep different orderings of the same piece set.",
    )
    parser.add_argument("--reciprocal-penalty", type=float, default=12.0)
    parser.add_argument("--edge-penalty", type=float, default=3.0)
    parser.add_argument("--fragment-penalty", type=float, default=6.0)
    parser.add_argument("--wordfreq-weight", type=float, default=0.35)
    parser.add_argument(
        "--plausibility-weight",
        type=float,
        default=None,
        help=(
            "Weight for external plausibility scores. Defaults to 1.0 when "
            "a language model is provided, otherwise 0.0."
        ),
    )
    parser.add_argument("--source-lang", default="es")
    parser.add_argument("--target-lang", default="pt")
    parser.add_argument("--source-lm", type=Path, default=None)
    parser.add_argument("--target-lm", type=Path, default=None)
    return parser


def command_from_args(args: argparse.Namespace) -> GeneratePhrasesCommand:
    if args.min_source_count < 1:
        raise ValueError("--min-source-count must be at least 1")
    if args.min_target_count < 1:
        raise ValueError("--min-target-count must be at least 1")
    if args.max_source_n < 1:
        raise ValueError("--max-source-n must be at least 1")
    if args.max_target_n < 1:
        raise ValueError("--max-target-n must be at least 1")
    if args.piece_limit < 1:
        raise ValueError("--piece-limit must be at least 1")
    if args.beam_size < 1:
        raise ValueError("--beam-size must be at least 1")
    if args.max_results < 1:
        raise ValueError("--max-results must be at least 1")
    if args.min_pieces < 1:
        raise ValueError("--min-pieces must be at least 1")
    if args.max_pieces < args.min_pieces:
        raise ValueError("--max-pieces must be >= --min-pieces")

    has_language_model = args.source_lm is not None or args.target_lm is not None
    plausibility_weight = args.plausibility_weight
    if plausibility_weight is None:
        plausibility_weight = 1.0 if has_language_model else 0.0

    policy = GeneratePhrasePolicy(
        min_source_count=args.min_source_count,
        min_target_count=args.min_target_count,
        min_pair_score=args.min_pair_score,
        max_source_n=args.max_source_n,
        max_target_n=args.max_target_n,
        piece_limit=args.piece_limit,
        min_pieces=args.min_pieces,
        max_pieces=args.max_pieces,
        beam_size=args.beam_size,
        max_results=args.max_results,
        allow_repeated_pieces=args.allow_repeated_pieces,
        collapse_permutations=not args.keep_permutations,
        reciprocal_penalty=args.reciprocal_penalty,
        edge_penalty=args.edge_penalty,
        fragment_penalty=args.fragment_penalty,
        wordfreq_weight=args.wordfreq_weight,
        plausibility_weight=plausibility_weight,
    )
    return GeneratePhrasesCommand(
        input_path=args.input,
        output_path=args.out,
        policy=policy,
    )


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = build_argparser().parse_args(argv)
    command = command_from_args(args)

    logger.info("Starting phrase generation")
    logger.info("Input: %s", command.input_path)
    logger.info("Output: %s", command.output_path)
    logger.info("Policy: %s", command.policy)

    plausibility_scorer = build_plausibility_scorer(
        source_lang=args.source_lang,
        source_lm=args.source_lm,
        target_lang=args.target_lang,
        target_lm=args.target_lm,
    )
    generated = run_generation(
        command,
        TsvPhraseRepository(),
        plausibility_scorer=plausibility_scorer,
    )
    logger.info("Generated %d phrase candidates", generated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
