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
from semordnilap.ngrams.infrastructure import (
    SOURCE_ADAPTERS,
    DuckDbNgramCountRepository,
    resolve_corpus_input,
)
from semordnilap.utils.artifacts import ArtifactLock

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


HELP_FORMATTER = HelpFormatter


def add_db_path(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="DuckDB database that stores checkpoints and final counts.",
    )


def add_lang_corpus(
    parser: argparse.ArgumentParser,
    *,
    lang_required: bool,
    corpus_default: str | None = "default",
    corpus_required: bool = False,
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
        required=corpus_required,
        help=(
            "Readable corpus alias. Managed adapters infer it when omitted; "
            "--corpus overrides the inferred alias."
        ),
    )
    parser.add_argument(
        "--dataset-id",
        help="Select one immutable extraction identity when an alias is ambiguous.",
    )


def add_policy_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--max-n",
        type=int,
        choices=[1, 2, 3],
        default=3,
        help="Largest lexical window to count (1=unigrams, 2=bigrams, 3=trigrams).",
    )
    parser.add_argument(
        "--min-token-len",
        type=int,
        default=2,
        help="Discard lexical tokens shorter than this many characters.",
    )
    parser.add_argument(
        "--max-token-len",
        type=int,
        default=30,
        help="Discard lexical tokens longer than this many characters.",
    )
    parser.add_argument(
        "--min-norm-len",
        type=int,
        default=3,
        help="Discard n-grams whose normalized key is shorter than this.",
    )
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
        "--punctuation",
        choices=["keep", "boundary"],
        default="keep",
        help=(
            "keep retains punctuation in the stored surface and permits "
            "lexical windows to cross it; boundary treats every punctuation "
            "character as a hard n-gram boundary. Punctuation never counts "
            "toward n or norm_key."
        ),
    )
    # Accept historical spellings without advertising three ways to express
    # the same policy in the public CLI.
    parser.add_argument(
        "--omit-punctuation",
        dest="punctuation",
        action="store_const",
        const="boundary",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--keep-punctuation",
        "--no-omit-punctuation",
        dest="punctuation",
        action="store_const",
        const="keep",
        help=argparse.SUPPRESS,
    )


def add_counting_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Source file, corpus directory, or managed corpus collection.",
    )
    parser.add_argument(
        "--adapter",
        choices=SOURCE_ADAPTERS,
        default="auto",
        help=(
            "Source adapter. auto recognizes downloaded Wikisource and "
            "CorpusNOS manifests; raw keeps the generic reader."
        ),
    )
    parser.add_argument(
        "--format",
        dest="input_format",
        choices=["auto", "txt", "jsonl"],
        default="auto",
        help="Raw input format; managed adapters resolve this automatically.",
    )
    parser.add_argument(
        "--text-field",
        default="text",
        help="JSONL field containing document text (raw adapter only).",
    )
    parser.add_argument(
        "--limit-docs",
        type=int,
        default=0,
        help="Process only the first N documents; 0 processes the full corpus.",
    )
    # Removed from the visible interface because extraction checkpoints each
    # document and this historical option never controlled that behavior.
    parser.add_argument(
        "--chunk-docs",
        type=int,
        default=1000,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--flush-unique-ngrams",
        type=int,
        default=250_000,
        help=(
            "Commit a document segment when its in-memory counter reaches "
            "this many distinct n-grams. This bounds extraction memory."
        ),
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help=(
            "Delete and rebuild only the matching immutable dataset identity. "
            "Without this flag, reruns resume committed checkpoints."
        ),
    )
    parser.add_argument(
        "--no-compact-after-count",
        action="store_true",
        help=argparse.SUPPRESS,
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
        description="Manage corpus n-grams for semordnilap candidate generation.",
        formatter_class=HELP_FORMATTER,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract_parser = subparsers.add_parser(
        "extract",
        help="Count a corpus resumably, then finalize an immutable generation.",
        description=(
            "Count corpus n-grams into transactional staging checkpoints, "
            "then consolidate and atomically activate a final generation. "
            "Rerunning the same command resumes both phases."
        ),
        formatter_class=HELP_FORMATTER,
    )
    add_db_path(extract_parser)
    add_lang_corpus(extract_parser, lang_required=True, corpus_default=None)
    add_policy_options(extract_parser)
    add_counting_options(extract_parser)

    export_parser = subparsers.add_parser(
        "export",
        help="Export existing n-gram counts from DuckDB to TSV.",
        formatter_class=HELP_FORMATTER,
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
        formatter_class=HELP_FORMATTER,
    )
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)

    stats_parser = db_subparsers.add_parser(
        "stats",
        help=(
            "Inventory DuckDB tables, available collections, datasets and "
            "n-gram counts."
        ),
        formatter_class=HELP_FORMATTER,
    )
    add_db_path(stats_parser)
    add_lang_corpus(stats_parser, lang_required=False, corpus_default=None)
    stats_parser.add_argument(
        "--verbose",
        action="store_true",
        help=("Include top raw rows and every generation dataset identity."),
    )

    delete_parser = db_subparsers.add_parser(
        "delete",
        help="Delete all rows for one lang/corpus from the n-gram store.",
        formatter_class=HELP_FORMATTER,
    )
    add_db_path(delete_parser)
    add_lang_corpus(delete_parser, lang_required=True)

    compact_parser = db_subparsers.add_parser(
        "compact",
        help="Build totals for legacy raw-count tables only.",
        description=(
            "Compact legacy ngram_counts rows. Modern extraction generations "
            "are finalized automatically by extract or db finalize."
        ),
        formatter_class=HELP_FORMATTER,
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
    finalize_parser = db_subparsers.add_parser(
        "finalize",
        help="Resume consolidation of an already-counted generation.",
        description=(
            "Resume progressive finalization from committed staging rows. "
            "Use this after an interrupted or out-of-memory finalization; "
            "the source corpus is not read again."
        ),
        formatter_class=HELP_FORMATTER,
    )
    add_db_path(finalize_parser)
    add_lang_corpus(
        finalize_parser,
        lang_required=True,
        corpus_default=None,
        corpus_required=True,
    )
    migrate_parser = db_subparsers.add_parser(
        "migrate",
        help=(
            "Migrate DuckDB to text-only schema v3, preserving textual "
            "counts and dropping UPOS tables."
        ),
        formatter_class=HELP_FORMATTER,
    )
    add_db_path(migrate_parser)
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
    if args.limit_docs < 0:
        raise ValueError("--limit-docs must be 0 or greater")
    if args.flush_unique_ngrams < 1:
        raise ValueError("--flush-unique-ngrams must be at least 1")
    if not args.corpus or not args.corpus.strip():
        raise ValueError("--corpus cannot be empty")
    if args.min_token_len < 1:
        raise ValueError("--min-token-len must be at least 1")
    if args.max_token_len < args.min_token_len:
        raise ValueError("--max-token-len cannot be less than --min-token-len")
    if args.min_norm_len < 0:
        raise ValueError("--min-norm-len must be 0 or greater")


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
        omit_punctuation=getattr(args, "punctuation", "keep") == "boundary",
    )


def command_from_args(args: argparse.Namespace) -> ExtractNgramsCommand:
    if args.command == "db" and args.db_command == "stats":
        raise ValueError("stats does not build an extraction command")

    normalize_lang(args, required=True)
    validate_max_n(args)

    if args.command == "extract":
        resolved = resolve_corpus_input(
            args.input,
            adapter=args.adapter,
            lang=args.lang,
            corpus=args.corpus,
            requested_format=args.input_format,
            text_field=args.text_field,
        )
        args.input = resolved.path
        args.input_files = resolved.files
        args.input_format = resolved.input_format
        args.text_field = resolved.text_field
        args.corpus = resolved.corpus
        args.source_adapter = resolved.adapter
        if resolved.input_format == "ud-jsonl":
            raise ValueError(
                "Annotated ud-jsonl input is no longer supported by "
                "sp_ngrams; extract directly from the source corpus"
            )
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
        flush_unique_ngrams=getattr(args, "flush_unique_ngrams", 250_000),
        reset=getattr(args, "reset", False),
        export_only=is_export,
        export_after_count=is_export,
        delete_only=is_delete,
        compact_only=is_compact,
        compact_n=getattr(args, "compact_n", 0),
        policy=policy_from_args(args),
        dataset_id=getattr(args, "dataset_id", None),
        source_adapter=getattr(args, "source_adapter", "raw"),
        input_files=getattr(args, "input_files", ()),
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
    lines = [
        "N-gram DuckDB stats",
        f"schema_version: {stats['schema_version']}",
    ]
    filters = []
    if args.lang:
        filters.append(f"lang={args.lang}")
    if args.corpus:
        filters.append(f"corpus={args.corpus}")
    if filters:
        lines.append(f"filters: {' '.join(filters)}")

    table_roles = {
        "semordnilap_schema": "schema history",
        "ngram_counts": "legacy raw partial counts",
        "ngram_totals": "legacy compacted counts",
        "ngram_compactions": "legacy compaction registry",
        "extraction_datasets": "generation dataset registry",
        "extraction_runs": "generation run checkpoints",
        "extraction_chunks": "committed chunk ledger",
        "ngram_finalization_parts": "resumable finalization checkpoints",
        "ngram_stage_v2": "generation staging counts",
        "ngram_final_v2": "active/final generation counts",
    }
    lines.append("database tables:")
    for table, columns, rows in stats["table_inventory"]:
        role = table_roles.get(table, "application table")
        lines.append(
            f"- {table}: rows={format_number(rows)} columns={columns} "
            f"role={role}"
        )

    legacy_catalog = {
        (row[0], row[1]): row[2:] for row in stats["legacy_collections"]
    }
    generation_catalog = {
        (row[0], row[1]): row[2:] for row in stats["generation_collections"]
    }
    available_keys = sorted(legacy_catalog.keys() | generation_catalog.keys())
    if available_keys:
        lines.append("available collections (lang/corpus):")
        for lang, corpus in available_keys:
            details = []
            legacy = legacy_catalog.get((lang, corpus))
            if legacy:
                has_raw, has_compact, n_values, last_compacted = legacy
                locations = []
                if has_raw:
                    locations.append("raw")
                if has_compact:
                    locations.append("compact")
                n_text = ",".join(str(n) for n in n_values) or "none"
                details.append(
                    f"legacy={'+'.join(locations) or 'registry-only'} "
                    f"compacted_n={n_text} "
                    f"last_compacted={last_compacted or 'never'}"
                )
            generation = generation_catalog.get((lang, corpus))
            if generation:
                datasets, complete, active, latest = generation
                details.append(
                    f"generations={datasets} complete={complete} "
                    f"in_progress={active} latest={latest}"
                )
            lines.append(f"- {lang}/{corpus}: {'; '.join(details)}")

    raw_by_collection = {
        (row[0], row[1]): row[2:] for row in stats["by_lang_corpus"]
    }
    compact_by_collection = {}
    totals_by_n = {}
    for lang, corpus, n, rows, occurrences in stats["totals_by_n"]:
        totals_by_n[(lang, corpus, n)] = (rows, occurrences)
        summary = compact_by_collection.setdefault((lang, corpus), [0, 0])
        summary[0] += rows or 0
        summary[1] += occurrences or 0
    compacted_at = {
        (row[0], row[1], row[2]): row[3] for row in stats["compacted"]
    }
    matching_keys = sorted(
        raw_by_collection.keys()
        | compact_by_collection.keys()
        | {(row[0], row[1]) for row in stats["compacted"]}
        | {(row[1], row[2]) for row in stats["generation_by_n"]}
        | {(row[3], row[4]) for row in stats["v2_datasets"]}
    )
    if matching_keys:
        lines.append("matching selection:")
        for lang, corpus in matching_keys:
            values = []
            raw = raw_by_collection.get((lang, corpus))
            if raw:
                raw_rows, raw_occurrences, unique_texts = raw
                values.append(
                    f"raw_rows={format_number(raw_rows)} "
                    f"raw_occurrences={format_number(raw_occurrences)} "
                    f"approx_unique_raw_texts={format_number(unique_texts)}"
                )
            compact = compact_by_collection.get((lang, corpus))
            if compact:
                values.append(
                    f"compact_rows={format_number(compact[0])} "
                    f"compact_occurrences={format_number(compact[1])}"
                )
            generation_rows = sum(
                row[4]
                for row in stats["generation_by_n"]
                if (row[1], row[2]) == (lang, corpus)
            )
            generation_occurrences = sum(
                row[5]
                for row in stats["generation_by_n"]
                if (row[1], row[2]) == (lang, corpus)
            )
            if generation_rows:
                values.append(
                    f"generation_rows={format_number(generation_rows)} "
                    "generation_occurrences="
                    f"{format_number(generation_occurrences)}"
                )
            if not values:
                has_generation_metadata = any(
                    (row[3], row[4]) == (lang, corpus)
                    for row in stats["v2_datasets"]
                )
                if has_generation_metadata:
                    values.append(
                        "generation metadata present; no active final count "
                        "rows"
                    )
                else:
                    values.append("compaction registry present; no count rows")
            lines.append(f"- {lang}/{corpus}: {'; '.join(values)}")
    else:
        lines.append("matching selection: no data matched all filters")
        if filters and available_keys:
            lines.append(
                "hint: choose one of the exact lang/corpus aliases listed "
                "under available collections"
            )

    if stats["v2_datasets"]:
        lines.append("matching immutable datasets:")
        for (
            dataset_id,
            artifact_id,
            policy_hash,
            lang,
            corpus,
            sample,
            status,
            generation,
        ) in stats["v2_datasets"]:
            lines.append(
                f"- {lang}/{corpus}: dataset_id={dataset_id} "
                f"artifact_id={artifact_id} policy_hash={policy_hash} "
                f"sample={sample} status={status} "
                f"generation={generation}"
            )
    if stats["extraction_runs"]:
        lines.append("matching extraction checkpoints:")
        for (
            dataset_id,
            lang,
            corpus,
            status,
            completed_documents,
            occurrences,
            chunks,
            updated_at,
        ) in stats["extraction_runs"]:
            lines.append(
                f"- {lang}/{corpus}: dataset_id={dataset_id} status={status} "
                f"completed_documents={format_number(completed_documents)} "
                f"occurrences={format_number(occurrences)} "
                f"chunks={format_number(chunks)} updated_at={updated_at}"
            )
    if stats["finalization_parts"]:
        lines.append("matching finalization progress:")
        for dataset_id, generation, n, completed, total, updated_at in stats[
            "finalization_parts"
        ]:
            lines.append(
                f"- dataset_id={dataset_id} generation={generation} n={n}: "
                f"parts={completed}/{total} updated_at={updated_at}"
            )
    raw_by_n = {(row[0], row[1], row[2]): row[3:] for row in stats["by_n"]}
    n_keys = sorted(raw_by_n.keys() | totals_by_n.keys() | compacted_at.keys())
    if n_keys:
        lines.append("matching legacy counts by n:")
        for lang, corpus, n in n_keys:
            raw_rows, raw_occurrences, unique_texts = raw_by_n.get(
                (lang, corpus, n), (0, 0, 0)
            )
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

    if stats["generation_by_n"]:
        lines.append("matching generation counts by n:")
        for dataset_id, lang, corpus, n, rows, occurrences in stats[
            "generation_by_n"
        ]:
            lines.append(
                f"- {lang}/{corpus} dataset_id={dataset_id} n={n}: "
                f"rows={format_number(rows)} "
                f"occurrences={format_number(occurrences)}"
            )

    if stats["filtered_table_counts"]:
        filtered_table_counts = ", ".join(
            f"{name}={format_number(rows)}"
            for name, rows in stats["filtered_table_counts"]
        )
        if filters:
            lines.append(
                f"matching legacy table rows: {filtered_table_counts}"
            )
        else:
            lines.append(f"legacy table rows: {filtered_table_counts}")

    if args.verbose and stats["top_partial_rows"]:
        lines.append("top raw partial rows:")
        for lang, corpus, text, n, count, norm_key in stats[
            "top_partial_rows"
        ]:
            lines.append(
                f"- {lang}/{corpus} n={n} count={format_number(count)} "
                f"text={text!r} norm_key={norm_key}"
            )

    if args.verbose and stats["all_v2_datasets"]:
        lines.append("all generation dataset identities:")
        for row in stats["all_v2_datasets"]:
            (
                dataset_id,
                artifact_id,
                policy_hash,
                lang,
                corpus,
                input_format,
                sample,
                status,
                generation,
                created_at,
                completed_at,
            ) = row
            lines.append(
                f"- {lang}/{corpus}: dataset_id={dataset_id} "
                f"artifact_id={artifact_id} policy_hash={policy_hash} "
                f"format={input_format} sample={sample} status={status} "
                f"generation={generation} created_at={created_at} "
                f"completed_at={completed_at}"
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
        repository = DuckDbNgramCountRepository(args.db_path, read_only=True)
        try:
            log_stats(repository, args)
        finally:
            repository.close()
        return 0

    if args.command == "db" and args.db_command == "migrate":
        with ArtifactLock(args.db_path):
            DuckDbNgramCountRepository.migrate(args.db_path)
        logger.info("Migrated DuckDB schema at %s", args.db_path)
        return 0

    if args.command == "db" and args.db_command == "finalize":
        normalize_lang(args, required=True)
        if not args.corpus or not args.corpus.strip():
            raise ValueError("--corpus is required")
        with ArtifactLock(args.db_path):
            repository = DuckDbNgramCountRepository(args.db_path)
            try:
                affected = repository.resume_finalization(
                    lang=args.lang,
                    corpus=args.corpus.strip(),
                    dataset_id=args.dataset_id,
                )
            finally:
                repository.close()
        logger.info(
            "Finalized %d n-grams for lang=%s corpus=%s",
            affected,
            args.lang,
            args.corpus,
        )
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
        "flush_unique_ngrams=%d "
        "adapter=%s "
        "punctuation=%s "
        "reset=%s export_only=%s export_after_count=%s delete_only=%s "
        "compact_only=%s compact_n=%d",
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
        command.flush_unique_ngrams,
        command.source_adapter,
        "boundary" if command.policy.omit_punctuation else "keep",
        command.reset,
        command.export_only,
        command.export_after_count,
        command.delete_only,
        command.compact_only,
        command.compact_n,
    )

    if command.export_only:
        repository = DuckDbNgramCountRepository(args.db_path, read_only=True)
        affected = run_extraction(command, repository)
    else:
        with ArtifactLock(args.db_path):
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
            "(final rows=%d)",
            command.policy.lang,
            command.corpus,
            affected,
        )
    else:
        logger.info("Exported %d n-grams to %s", affected, command.output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
