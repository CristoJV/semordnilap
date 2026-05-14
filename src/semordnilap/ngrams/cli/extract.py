"""Extract scored unigram, bigram, and trigram candidates from a corpus."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from semordnilap.ngrams.application import (
    ExtractNgramsCommand,
    run_extraction,
)
from semordnilap.ngrams.domain import NgramExtractionPolicy
from semordnilap.ngrams.infrastructure import DuckDbNgramCountRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/ngrams/ngrams.duckdb")


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        "Extract corpus n-grams for semordnilap candidate generation"
    )
    parser.add_argument("--input", type=Path, required=False)
    parser.add_argument("--out", type=Path, required=False)
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"DuckDB database path. Default: {DEFAULT_DB_PATH}",
    )
    parser.add_argument(
        "--lang",
        required=True,
        help=(
            "Language code stored with the extracted n-grams. Known codes "
            "get language-specific filters; unknown codes use generic rules."
        ),
    )
    parser.add_argument(
        "--corpus",
        default="default",
        help="Corpus identifier stored with each n-gram.",
    )
    parser.add_argument(
        "--format",
        dest="input_format",
        choices=["auto", "txt", "jsonl"],
        default="auto",
    )
    parser.add_argument("--text-field", default="text")
    parser.add_argument("--max-n", type=int, default=3)
    parser.add_argument("--min-count", type=int, default=3)
    parser.add_argument(
        "--max-results",
        type=int,
        default=0,
        help="Maximum n-grams to export. 0 means no limit.",
    )
    parser.add_argument(
        "--export-n",
        type=int,
        choices=[0, 1, 2, 3],
        default=0,
        help="Only export n-grams of this size. 0 means all sizes.",
    )
    parser.add_argument(
        "--min-export-norm-len",
        type=int,
        default=0,
        help="Only export rows whose norm_key has at least this length.",
    )
    parser.add_argument(
        "--max-export-norm-len",
        type=int,
        default=0,
        help="Only export rows whose norm_key has at most this length.",
    )
    parser.add_argument(
        "--export-source",
        choices=["auto", "raw", "compact"],
        default="auto",
        help=(
            "Where exported counts come from. auto uses compacted totals "
            "when --export-n has been compacted, otherwise raw partial rows."
        ),
    )
    parser.add_argument(
        "--export-log-every",
        type=int,
        default=10_000,
        help="Log TSV export progress every N rows. 0 disables progress logs.",
    )
    parser.add_argument("--min-token-len", type=int, default=2)
    parser.add_argument("--max-token-len", type=int, default=30)
    parser.add_argument("--min-norm-len", type=int, default=3)
    parser.add_argument(
        "--include-all-stopword-ngrams",
        action="store_true",
        help="Keep n-grams made only of stopwords instead of filtering them.",
    )
    parser.add_argument(
        "--fold-nasal-letters",
        action="store_true",
        help="Normalize ñ to n. ç is always normalized to c.",
    )
    parser.add_argument(
        "--limit-docs",
        type=int,
        default=0,
        help="Process only the first N text records. Useful for smoke tests.",
    )
    parser.add_argument(
        "--chunk-docs",
        type=int,
        default=1000,
        help="Flush counts to DuckDB every N documents.",
    )
    parser.add_argument(
        "--flush-unique-ngrams",
        type=int,
        default=250_000,
        help="Flush counts when the pending Counter reaches N unique n-grams.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing rows for this lang/corpus before counting.",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Skip corpus extraction and export existing DuckDB counts to TSV.",
    )
    parser.add_argument(
        "--compact-only",
        action="store_true",
        help=(
            "Build compacted total counts in DuckDB and exit. Without "
            "--compact-n, compacts n=1..max-n progressively."
        ),
    )
    parser.add_argument(
        "--no-compact-after-count",
        action="store_true",
        help=(
            "Do not automatically compact n-gram totals after corpus "
            "extraction."
        ),
    )
    parser.add_argument(
        "--compact-n",
        type=int,
        choices=[1, 2, 3],
        default=0,
        help=(
            "N-gram size to compact when using --compact-only. If omitted, "
            "compacts n=1..max-n progressively."
        ),
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="Print DuckDB n-gram storage statistics and exit.",
    )
    return parser


def command_from_args(args: argparse.Namespace) -> ExtractNgramsCommand:
    args.lang = args.lang.strip().lower()
    if not args.lang:
        raise ValueError("--lang cannot be empty")
    if args.max_n < 1:
        raise ValueError("--max-n must be at least 1")
    if args.max_n > 3:
        raise ValueError("--max-n cannot be greater than 3")
    if args.min_count < 1:
        raise ValueError("--min-count must be at least 1")
    if args.max_results < 0:
        raise ValueError("--max-results must be 0 or greater")
    if args.min_export_norm_len < 0:
        raise ValueError("--min-export-norm-len must be 0 or greater")
    if args.max_export_norm_len < 0:
        raise ValueError("--max-export-norm-len must be 0 or greater")
    if (
        args.min_export_norm_len
        and args.max_export_norm_len
        and args.min_export_norm_len > args.max_export_norm_len
    ):
        raise ValueError(
            "--min-export-norm-len cannot be greater than "
            "--max-export-norm-len"
        )
    if args.chunk_docs < 1:
        raise ValueError("--chunk-docs must be at least 1")
    if args.flush_unique_ngrams < 1:
        raise ValueError("--flush-unique-ngrams must be at least 1")
    if args.export_log_every < 0:
        raise ValueError("--export-log-every must be 0 or greater")
    if not (args.stats_only or args.compact_only) and args.out is None:
        raise ValueError(
            "--out is required unless --stats-only or --compact-only is used"
        )
    if (
        not (args.export_only or args.stats_only or args.compact_only)
        and args.input is None
    ):
        raise ValueError(
            "--input is required unless --export-only, --compact-only, "
            "or --stats-only is used"
        )

    policy = NgramExtractionPolicy(
        lang=args.lang,
        max_n=args.max_n,
        min_token_len=args.min_token_len,
        max_token_len=args.max_token_len,
        min_norm_len=args.min_norm_len,
        include_all_stopword_ngrams=args.include_all_stopword_ngrams,
        fold_nasal_letters=args.fold_nasal_letters,
    )

    return ExtractNgramsCommand(
        input_path=args.input,
        output_path=args.out or Path("-"),
        corpus=args.corpus,
        input_format=args.input_format,
        text_field=args.text_field,
        min_count=args.min_count,
        max_results=args.max_results,
        export_n=args.export_n,
        min_export_norm_len=args.min_export_norm_len,
        max_export_norm_len=args.max_export_norm_len,
        export_source=args.export_source,
        export_log_every=args.export_log_every,
        limit_docs=args.limit_docs,
        chunk_docs=args.chunk_docs,
        flush_unique_ngrams=args.flush_unique_ngrams,
        reset=args.reset,
        export_only=args.export_only,
        compact_only=args.compact_only,
        compact_n=args.compact_n,
        compact_after_count=not args.no_compact_after_count,
        policy=policy,
    )


def log_stats(repository: DuckDbNgramCountRepository, args) -> None:
    stats = repository.stats(lang=args.lang, corpus=args.corpus)

    logger.info("Stats by lang/corpus")
    for row in stats["by_lang_corpus"]:
        logger.info(
            "lang=%s corpus=%s partial_rows=%d total_occurrences=%d "
            "approx_unique_texts=%d",
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
        )

    logger.info("Stats by n")
    for row in stats["by_n"]:
        logger.info(
            "lang=%s corpus=%s n=%d partial_rows=%d "
            "total_occurrences=%d approx_unique_texts=%d",
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
        )

    logger.info("Compacted totals by n")
    for row in stats["totals_by_n"]:
        logger.info(
            "lang=%s corpus=%s n=%d total_rows=%d total_occurrences=%d",
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
        )

    logger.info("DuckDB table row counts")
    for row in stats["table_counts"]:
        logger.info("table=%s rows=%d", row[0], row[1])

    logger.info("Top partial rows")
    for row in stats["top_partial_rows"]:
        logger.info(
            "lang=%s corpus=%s text=%r n=%d count=%d norm_key=%s",
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
        )

    logger.info("Compacted totals")
    for row in stats["compacted"]:
        logger.info(
            "lang=%s corpus=%s n=%d compacted_at=%s",
            row[0],
            row[1],
            row[2],
            row[3],
        )


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = build_argparser().parse_args(argv)
    command = command_from_args(args)

    logger.info("Starting n-gram extraction")
    logger.info("Input: %s", command.input_path)
    logger.info("Output: %s", command.output_path)
    logger.info("DuckDB database: %s", args.db_path)
    logger.info(
        "Options: lang=%s corpus=%s max_n=%d min_count=%d "
        "max_results=%d export_n=%d export_norm_len=%d..%d "
        "export_source=%s export_log_every=%d "
        "chunk_docs=%d flush_unique_ngrams=%d "
        "reset=%s export_only=%s compact_only=%s compact_n=%d "
        "compact_after_count=%s stats_only=%s",
        command.policy.lang,
        command.corpus,
        command.policy.max_n,
        command.min_count,
        command.max_results,
        command.export_n,
        command.min_export_norm_len,
        command.max_export_norm_len,
        command.export_source,
        command.export_log_every,
        command.chunk_docs,
        command.flush_unique_ngrams,
        command.reset,
        command.export_only,
        command.compact_only,
        command.compact_n,
        command.compact_after_count,
        args.stats_only,
    )

    repository = DuckDbNgramCountRepository(args.db_path)
    if args.stats_only:
        try:
            log_stats(repository, args)
        finally:
            repository.close()
        return 0

    affected = run_extraction(command, repository)
    if command.compact_only:
        if command.compact_n:
            logger.info(
                "Compacted %d n-grams for lang=%s corpus=%s n=%d",
                affected,
                command.policy.lang,
                command.corpus,
                command.compact_n,
            )
        else:
            logger.info(
                "Compacted %d n-grams for lang=%s corpus=%s n=1..%d",
                affected,
                command.policy.lang,
                command.corpus,
                command.policy.max_n,
            )
    else:
        logger.info("Exported %d n-grams to %s", affected, command.output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
