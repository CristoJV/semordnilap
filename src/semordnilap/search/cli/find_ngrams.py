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


class HelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
    """Show meaningful defaults without noisy None/False annotations."""

    def _get_help_string(self, action: argparse.Action) -> str:
        if (
            action.required
            or action.default is None
            or action.default is False
        ):
            return action.help
        return super()._get_help_string(action)


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Find semordnilaps in finalized n-gram generations. The default "
            "search is unrestricted: reductions are only applied through "
            "explicit --filter-* options."
        ),
        formatter_class=HelpFormatter,
        epilog=(
            "Run first with --dry-run and no --out to count candidates and "
            "matching pairs. Without --filter-max-results, the export is "
            "unlimited."
        ),
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="DuckDB database containing finalized n-gram generations.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Output TSV. Required unless --dry-run is used.",
    )
    parser.add_argument(
        "--src-lang",
        required=True,
        help="Language code of the source n-gram dataset.",
    )
    parser.add_argument(
        "--tgt-lang",
        required=True,
        help="Language code of the target n-gram dataset.",
    )
    parser.add_argument(
        "--src-corpus",
        required=True,
        help="Corpus alias of the source n-gram dataset.",
    )
    parser.add_argument(
        "--tgt-corpus",
        required=True,
        help="Corpus alias of the target n-gram dataset.",
    )
    parser.add_argument(
        "--src-dataset-id",
        help="Exact source dataset identity; required if its alias is ambiguous.",
    )
    parser.add_argument(
        "--tgt-dataset-id",
        help="Exact target dataset identity; required if its alias is ambiguous.",
    )
    parser.add_argument(
        "--filter-min-src-count",
        type=int,
        default=1,
        help="Discard source n-grams with a lower count.",
    )
    parser.add_argument(
        "--filter-min-tgt-count",
        type=int,
        default=1,
        help="Discard target n-grams with a lower count.",
    )
    parser.add_argument(
        "--filter-src-n",
        type=int,
        choices=[1, 2, 3],
        help="Only search source n-grams of this size.",
    )
    parser.add_argument(
        "--filter-tgt-n",
        type=int,
        choices=[1, 2, 3],
        help="Only search target n-grams of this size.",
    )
    parser.add_argument(
        "--filter-min-norm-len",
        type=int,
        help="Only search norm_key values with at least this length.",
    )
    parser.add_argument(
        "--filter-max-norm-len",
        type=int,
        help="Only search norm_key values with at most this length.",
    )
    parser.add_argument(
        "--filter-max-results",
        type=int,
        help=(
            "Maximum number of pairs to export after sorting. If omitted, "
            "all matching pairs are exported."
        ),
    )
    parser.add_argument(
        "--filter-exclude-palindromes",
        action="store_true",
        help=(
            "Discard matches whose source and target norm_key are identical; "
            "they are included by default."
        ),
    )
    parser.add_argument(
        "--filter-exclude-identical-text",
        action="store_true",
        help=(
            "Discard identical source/target text in the same lang/corpus; "
            "it is included by default."
        ),
    )
    parser.add_argument(
        "--filter-exclude-punctuation",
        action="store_true",
        help=(
            "Discard pairs when either stored surface contains punctuation; "
            "punctuation is included by default."
        ),
    )
    parser.add_argument(
        "--filter-exclude-all-stopword-ngrams",
        action="store_true",
        help=(
            "Discard candidates made exclusively of known stopwords on "
            "either side; all-stopword n-grams are included by default."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Resolve datasets and calculate candidate and pair counts without "
            "writing a TSV."
        ),
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=10_000,
        help="Log export progress every N pairs; 0 disables progress logs.",
    )
    return parser


def command_from_args(args: argparse.Namespace) -> FindSemordnilapsCommand:
    if args.out is None and not args.dry_run:
        raise ValueError("--out is required unless --dry-run is used")
    if args.filter_min_src_count < 1:
        raise ValueError("--filter-min-src-count must be at least 1")
    if args.filter_min_tgt_count < 1:
        raise ValueError("--filter-min-tgt-count must be at least 1")
    if args.filter_max_results is not None and args.filter_max_results < 1:
        raise ValueError("--filter-max-results must be at least 1")
    if args.filter_min_norm_len is not None and args.filter_min_norm_len < 1:
        raise ValueError("--filter-min-norm-len must be at least 1")
    if args.filter_max_norm_len is not None and args.filter_max_norm_len < 1:
        raise ValueError("--filter-max-norm-len must be at least 1")
    if (
        args.filter_min_norm_len is not None
        and args.filter_max_norm_len is not None
        and args.filter_min_norm_len > args.filter_max_norm_len
    ):
        raise ValueError(
            "--filter-min-norm-len cannot be greater than "
            "--filter-max-norm-len"
        )
    if args.progress_every < 0:
        raise ValueError("--progress-every must be 0 or greater")

    policy = SearchPolicy(
        source_lang=args.src_lang,
        target_lang=args.tgt_lang,
        source_corpus=args.src_corpus,
        target_corpus=args.tgt_corpus,
        filter_min_source_count=args.filter_min_src_count,
        filter_min_target_count=args.filter_min_tgt_count,
        filter_max_results=args.filter_max_results,
        filter_source_n=args.filter_src_n,
        filter_target_n=args.filter_tgt_n,
        filter_min_norm_len=args.filter_min_norm_len,
        filter_max_norm_len=args.filter_max_norm_len,
        filter_exclude_palindromes=args.filter_exclude_palindromes,
        filter_exclude_identical_text=args.filter_exclude_identical_text,
        filter_exclude_punctuation=args.filter_exclude_punctuation,
        filter_exclude_all_stopword_ngrams=(
            args.filter_exclude_all_stopword_ngrams
        ),
        source_dataset_id=args.src_dataset_id,
        target_dataset_id=args.tgt_dataset_id,
    )

    return FindSemordnilapsCommand(
        db_path=args.db_path,
        output_path=args.out,
        policy=policy,
        dry_run=args.dry_run,
        progress_every=args.progress_every,
    )


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = build_argparser().parse_args(argv)
    command = command_from_args(args)

    logger.info("Starting n-gram semordnilap search")
    logger.info("DuckDB database: %s", command.db_path)
    if command.output_path is not None:
        logger.info("Output: %s", command.output_path)
    logger.info("Policy: %s", command.policy)

    repository = DuckDbSemordnilapSearchRepository(command.db_path)
    affected = run_search(command, repository)
    if command.dry_run:
        logger.info("Dry run found %d matching pairs", affected)
    else:
        logger.info("Exported %d pairs to %s", affected, command.output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
