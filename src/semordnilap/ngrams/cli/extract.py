"""Manage corpus n-grams for semordnilap candidate generation."""

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


def add_db_path(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"DuckDB database path. Default: {DEFAULT_DB_PATH}",
    )


def add_lang_corpus(
    parser: argparse.ArgumentParser,
    *,
    lang_required: bool,
    corpus_default: str | None = "default",
) -> None:
    parser.add_argument(
        "--lang",
        required=lang_required,
        help=(
            "Language code stored with the extracted n-grams. Known codes "
            "get language-specific filters; unknown codes use generic rules."
        ),
    )
    parser.add_argument(
        "--corpus",
        default=corpus_default,
        help="Corpus identifier stored with each n-gram.",
    )


def add_policy_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-n", type=int, default=3)
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


def add_counting_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--format",
        dest="input_format",
        choices=["auto", "txt", "jsonl"],
        default="auto",
    )
    parser.add_argument("--text-field", default="text")
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
        "--no-compact-after-count",
        action="store_true",
        help="Do not compact n-gram totals after corpus extraction.",
    )


def add_export_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", type=Path, required=True)
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
            "when available, otherwise raw partial rows."
        ),
    )
    parser.add_argument(
        "--export-log-every",
        type=int,
        default=10_000,
        help="Log TSV export progress every N rows. 0 disables progress logs.",
    )


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        "Manage corpus n-grams for semordnilap candidate generation"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract_parser = subparsers.add_parser(
        "extract",
        help="Extract n-gram counts into DuckDB and compact totals.",
    )
    add_db_path(extract_parser)
    add_lang_corpus(extract_parser, lang_required=True)
    add_policy_options(extract_parser)
    add_counting_options(extract_parser)

    export_parser = subparsers.add_parser(
        "export",
        help="Export existing n-gram counts from DuckDB to TSV.",
    )
    add_db_path(export_parser)
    add_lang_corpus(export_parser, lang_required=True)
    export_parser.add_argument("--max-n", type=int, default=3)
    export_parser.add_argument(
        "--fold-nasal-letters",
        action="store_true",
        help="Normalize ñ to n when scoring exported n-grams.",
    )
    add_export_options(export_parser)

    db_parser = subparsers.add_parser(
        "db",
        help="Inspect or maintain the DuckDB n-gram store.",
    )
    db_subparsers = db_parser.add_subparsers(
        dest="db_command", required=True
    )

    stats_parser = db_subparsers.add_parser(
        "stats",
        help="Print DuckDB n-gram storage statistics.",
    )
    add_db_path(stats_parser)
    add_lang_corpus(stats_parser, lang_required=False, corpus_default=None)
    stats_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include detailed diagnostic rows such as top raw partial rows.",
    )

    delete_parser = db_subparsers.add_parser(
        "delete",
        help="Delete all rows for one lang/corpus from the n-gram store.",
    )
    add_db_path(delete_parser)
    add_lang_corpus(delete_parser, lang_required=True)

    compact_parser = db_subparsers.add_parser(
        "compact",
        help="Build compacted total counts for one lang/corpus.",
    )
    add_db_path(compact_parser)
    add_lang_corpus(compact_parser, lang_required=True)
    compact_parser.add_argument("--max-n", type=int, default=3)
    compact_parser.add_argument(
        "--compact-n",
        type=int,
        choices=[1, 2, 3],
        default=0,
        help=(
            "N-gram size to compact. If omitted, compacts n=1..max-n "
            "progressively."
        ),
    )
    return parser


def normalize_lang(args: argparse.Namespace, *, required: bool) -> None:
    lang = getattr(args, "lang", None)
    if lang is None:
        if required:
            raise ValueError("--lang is required")
        return
    args.lang = lang.strip().lower()
    if required and not args.lang:
        raise ValueError("--lang cannot be empty")


def validate_max_n(args: argparse.Namespace) -> None:
    args.max_n = getattr(args, "max_n", 3)
    if args.max_n < 1:
        raise ValueError("--max-n must be at least 1")
    if args.max_n > 3:
        raise ValueError("--max-n cannot be greater than 3")
    if getattr(args, "compact_n", 0) and args.compact_n > args.max_n:
        raise ValueError("--compact-n cannot be greater than --max-n")


def validate_counting_args(args: argparse.Namespace) -> None:
    if args.chunk_docs < 1:
        raise ValueError("--chunk-docs must be at least 1")
    if args.flush_unique_ngrams < 1:
        raise ValueError("--flush-unique-ngrams must be at least 1")


def validate_export_args(args: argparse.Namespace) -> None:
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
    if args.export_log_every < 0:
        raise ValueError("--export-log-every must be 0 or greater")


def policy_from_args(args: argparse.Namespace) -> NgramExtractionPolicy:
    return NgramExtractionPolicy(
        lang=args.lang,
        max_n=getattr(args, "max_n", 3),
        min_token_len=getattr(args, "min_token_len", 2),
        max_token_len=getattr(args, "max_token_len", 30),
        min_norm_len=getattr(args, "min_norm_len", 3),
        include_all_stopword_ngrams=getattr(
            args, "include_all_stopword_ngrams", False
        ),
        fold_nasal_letters=getattr(args, "fold_nasal_letters", False),
    )


def command_from_args(args: argparse.Namespace) -> ExtractNgramsCommand:
    if args.command == "db" and args.db_command == "stats":
        raise ValueError("stats does not build an extraction command")

    normalize_lang(args, required=True)
    validate_max_n(args)

    if args.command == "extract":
        validate_counting_args(args)
    if args.command == "export":
        validate_export_args(args)

    is_export = args.command == "export"
    is_delete = args.command == "db" and args.db_command == "delete"
    is_compact = args.command == "db" and args.db_command == "compact"

    return ExtractNgramsCommand(
        input_path=getattr(args, "input", None),
        output_path=getattr(args, "out", Path("-")),
        corpus=args.corpus,
        input_format=getattr(args, "input_format", "auto"),
        text_field=getattr(args, "text_field", "text"),
        min_count=getattr(args, "min_count", 3),
        max_results=getattr(args, "max_results", 0),
        export_n=getattr(args, "export_n", 0),
        min_export_norm_len=getattr(args, "min_export_norm_len", 0),
        max_export_norm_len=getattr(args, "max_export_norm_len", 0),
        export_source=getattr(args, "export_source", "auto"),
        export_log_every=getattr(args, "export_log_every", 10_000),
        limit_docs=getattr(args, "limit_docs", 0),
        chunk_docs=getattr(args, "chunk_docs", 1000),
        flush_unique_ngrams=getattr(args, "flush_unique_ngrams", 250_000),
        reset=getattr(args, "reset", False),
        export_only=is_export,
        export_after_count=is_export,
        delete_only=is_delete,
        compact_only=is_compact,
        compact_n=getattr(args, "compact_n", 0),
        compact_after_count=(
            args.command == "extract"
            and not getattr(args, "no_compact_after_count", False)
        ),
        policy=policy_from_args(args),
    )


def format_number(value: int | None) -> str:
    if value is None:
        return "0"
    return f"{value:,}".replace(",", "_")


def log_stats(repository: DuckDbNgramCountRepository, args) -> None:
    stats = repository.stats(
        lang=args.lang,
        corpus=args.corpus,
        include_top_rows=args.verbose,
    )
    compacted_at = {
        (row[0], row[1], row[2]): row[3] for row in stats["compacted"]
    }
    totals_by_n = {
        (row[0], row[1], row[2]): (row[3], row[4])
        for row in stats["totals_by_n"]
    }

    lines = ["N-gram DuckDB stats"]
    filters = []
    if args.lang:
        filters.append(f"lang={args.lang}")
    if args.corpus:
        filters.append(f"corpus={args.corpus}")
    if filters:
        lines.append(f"filters: {' '.join(filters)}")

    if stats["by_lang_corpus"]:
        lines.append("scope:")
        for lang, corpus, raw_rows, raw_occurrences, unique_texts in stats[
            "by_lang_corpus"
        ]:
            lines.append(
                f"- {lang}/{corpus}: raw_rows={format_number(raw_rows)} "
                f"raw_occurrences={format_number(raw_occurrences)} "
                f"approx_unique_raw_texts={format_number(unique_texts)}"
            )
    else:
        lines.append("scope: no raw rows found")

    if stats["by_n"]:
        lines.append("by n:")
        for lang, corpus, n, raw_rows, raw_occurrences, unique_texts in stats[
            "by_n"
        ]:
            total_rows, total_occurrences = totals_by_n.get(
                (lang, corpus, n), (0, 0)
            )
            compacted = compacted_at.get((lang, corpus, n), "missing")
            lines.append(
                f"- {lang}/{corpus} n={n}: "
                f"raw_rows={format_number(raw_rows)} "
                f"raw_occurrences={format_number(raw_occurrences)} "
                f"approx_unique_raw_texts={format_number(unique_texts)} "
                f"compact_rows={format_number(total_rows)} "
                f"compact_occurrences={format_number(total_occurrences)} "
                f"compacted_at={compacted}"
            )

    if stats["filtered_table_counts"]:
        filtered_table_counts = ", ".join(
            f"{name}={format_number(rows)}"
            for name, rows in stats["filtered_table_counts"]
        )
        if filters:
            lines.append(f"matching rows: {filtered_table_counts}")
        else:
            lines.append(f"tables: {filtered_table_counts}")

    if filters and stats["table_counts"]:
        table_counts = ", ".join(
            f"{name}={format_number(rows)}"
            for name, rows in stats["table_counts"]
        )
        lines.append(f"database totals: {table_counts}")

    if args.verbose and stats["top_partial_rows"]:
        lines.append("top raw partial rows:")
        for lang, corpus, text, n, count, norm_key in stats[
            "top_partial_rows"
        ]:
            lines.append(
                f"- {lang}/{corpus} n={n} count={format_number(count)} "
                f"text={text!r} norm_key={norm_key}"
            )

    logger.info("\n%s", "\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = build_argparser().parse_args(argv)

    if args.command == "db" and args.db_command == "stats":
        normalize_lang(args, required=False)
        logger.info(
            "Inspecting n-gram DuckDB storage: db=%s lang=%s corpus=%s",
            args.db_path,
            args.lang,
            args.corpus,
        )
        repository = DuckDbNgramCountRepository(args.db_path)
        try:
            log_stats(repository, args)
        finally:
            repository.close()
        return 0

    command = command_from_args(args)

    logger.info("Starting sp_ngrams %s", args.command)
    if command.input_path:
        logger.info("Input: %s", command.input_path)
    if command.output_path != Path("-"):
        logger.info("Output: %s", command.output_path)
    logger.info("DuckDB database: %s", args.db_path)
    logger.info(
        "Options: lang=%s corpus=%s max_n=%d min_count=%d "
        "max_results=%d export_n=%d export_norm_len=%d..%d "
        "export_source=%s export_log_every=%d "
        "chunk_docs=%d flush_unique_ngrams=%d "
        "reset=%s export_only=%s export_after_count=%s delete_only=%s "
        "compact_only=%s compact_n=%d compact_after_count=%s",
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
        command.export_after_count,
        command.delete_only,
        command.compact_only,
        command.compact_n,
        command.compact_after_count,
    )

    repository = DuckDbNgramCountRepository(args.db_path)
    affected = run_extraction(command, repository)
    if command.delete_only:
        logger.info(
            "Deleted %d n-gram storage rows for lang=%s corpus=%s",
            affected,
            command.policy.lang,
            command.corpus,
        )
    elif command.compact_only:
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
    elif args.command == "extract":
        logger.info(
            "Finished n-gram extraction for lang=%s corpus=%s "
            "(compacted rows=%d)",
            command.policy.lang,
            command.corpus,
            affected,
        )
    else:
        logger.info("Exported %d n-grams to %s", affected, command.output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
