"""Find semordnilap pairs from extracted corpus n-grams."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from semordnilap.search.application import FindSemordnilapsCommand, run_search
from semordnilap.search.domain import SearchPolicy
from semordnilap.search.infrastructure import DuckDbSemordnilapSearchRepository


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/ngrams/ngrams.duckdb")


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser("Find semordnilaps from n-gram counts")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"DuckDB database path. Default: {DEFAULT_DB_PATH}",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--src-lang", required=True)
    parser.add_argument("--tgt-lang", required=True)
    parser.add_argument("--src-corpus", required=True)
    parser.add_argument("--tgt-corpus", required=True)
    parser.add_argument("--min-src-count", type=int, default=3)
    parser.add_argument("--min-tgt-count", type=int, default=3)
    parser.add_argument(
        "--src-n",
        type=int,
        choices=[0, 1, 2, 3],
        default=0,
        help="Only search source n-grams of this size. 0 means all sizes.",
    )
    parser.add_argument(
        "--tgt-n",
        type=int,
        choices=[0, 1, 2, 3],
        default=0,
        help="Only search target n-grams of this size. 0 means all sizes.",
    )
    parser.add_argument(
        "--min-norm-len",
        type=int,
        default=0,
        help="Only search norm_key values with at least this length.",
    )
    parser.add_argument(
        "--max-norm-len",
        type=int,
        default=0,
        help="Only search norm_key values with at most this length.",
    )
    parser.add_argument(
        "--counts-source",
        choices=["auto", "raw", "compact"],
        default="auto",
        help=(
            "Search compacted totals when available, raw partial counts, "
            "or choose automatically."
        ),
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=0,
        help="Maximum number of pairs to export. 0 means no limit.",
    )
    parser.add_argument(
        "--include-palindromes",
        action="store_true",
        help="Include matches where source and target norm_key are identical.",
    )
    parser.add_argument(
        "--include-identical-text",
        action="store_true",
        help="Include identical source/target text in same lang/corpus.",
    )
    return parser


def command_from_args(args: argparse.Namespace) -> FindSemordnilapsCommand:
    if args.min_src_count < 1:
        raise ValueError("--min-src-count must be at least 1")
    if args.min_tgt_count < 1:
        raise ValueError("--min-tgt-count must be at least 1")
    if args.max_results < 0:
        raise ValueError("--max-results must be 0 or greater")
    if args.min_norm_len < 0:
        raise ValueError("--min-norm-len must be 0 or greater")
    if args.max_norm_len < 0:
        raise ValueError("--max-norm-len must be 0 or greater")
    if (
        args.min_norm_len
        and args.max_norm_len
        and args.min_norm_len > args.max_norm_len
    ):
        raise ValueError("--min-norm-len cannot be greater than --max-norm-len")

    policy = SearchPolicy(
        source_lang=args.src_lang,
        target_lang=args.tgt_lang,
        source_corpus=args.src_corpus,
        target_corpus=args.tgt_corpus,
        min_source_count=args.min_src_count,
        min_target_count=args.min_tgt_count,
        max_results=args.max_results,
        source_n=args.src_n,
        target_n=args.tgt_n,
        min_norm_len=args.min_norm_len,
        max_norm_len=args.max_norm_len,
        counts_source=args.counts_source,
        include_palindromes=args.include_palindromes,
        include_identical_text=args.include_identical_text,
    )

    return FindSemordnilapsCommand(
        db_path=args.db_path,
        output_path=args.out,
        policy=policy,
    )


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = build_argparser().parse_args(argv)
    command = command_from_args(args)

    logger.info("Starting n-gram semordnilap search")
    logger.info("DuckDB database: %s", command.db_path)
    logger.info("Output: %s", command.output_path)
    logger.info("Policy: %s", command.policy)

    repository = DuckDbSemordnilapSearchRepository(command.db_path)
    exported = run_search(command, repository)
    logger.info("Exported %d pairs to %s", exported, command.output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
