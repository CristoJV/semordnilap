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
    dataset_select: bool = False,
) -> None:
    parser.add_argument(
        "--lang",
        required=lang_required,
        help=(
            "Language code stored with the extracted n-grams. Known codes "
            "provide one-letter allowances and stopword vocabularies for the "
            "optional filters; unknown codes use generic rules."
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
    if dataset_select:
        parser.add_argument(
            "--dataset-id",
            help=(
                "Select one immutable extraction identity when an alias is "
                "ambiguous."
            ),
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
        "--filter-min-token-len",
        dest="filter_min_token_len",
        type=int,
        default=2,
        help="Discard lexical tokens shorter than this many characters.",
    )
    parser.add_argument(
        "--filter-max-token-len",
        dest="filter_max_token_len",
        type=int,
        default=30,
        help="Discard lexical tokens longer than this many characters.",
    )
    parser.add_argument(
        "--filter-min-norm-len",
        dest="filter_min_norm_len",
        type=int,
        default=2,
        help="Discard n-grams whose normalized key is shorter than this.",
    )
    parser.add_argument(
        "--filter-all-stopword-ngrams",
        dest="filter_all_stopword_ngrams",
        action="store_true",
        help=(
            "Discard n-grams made exclusively of stopwords. By default they "
            "are retained like every other valid n-gram."
        ),
    )
    parser.add_argument(
        "--preserve-nasal-letters",
        action="store_true",
        help=(
            "Preserve ñ in norm_key instead of applying the default ñ→n "
            "normalization. ç is always normalized to c."
        ),
    )
    parser.add_argument(
        "--filter-punctuation-boundaries",
        action="store_true",
        help=(
            "Treat punctuation as a hard n-gram boundary. By default "
            "punctuation is retained in the surface form and lexical windows "
            "may cross it; punctuation never counts toward n or norm_key."
        ),
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
    add_lang_corpus(export_parser, lang_required=True, dataset_select=True)
    export_parser.add_argument("--max-n", type=int, default=3)
    export_parser.add_argument(
        "--preserve-nasal-letters",
        action="store_true",
        help="Preserve ñ instead of applying the default ñ→n scoring normalization.",
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
        dataset_select=True,
    )
    migrate_parser = db_subparsers.add_parser(
        "migrate",
        help=(
            "Migrate generation-based schema v3 to v4, preserving modern "
            "datasets and deleting obsolete legacy count tables."
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


def validate_counting_args(args: argparse.Namespace) -> None:
    if args.limit_docs < 0:
        raise ValueError("--limit-docs must be 0 or greater")
    if args.flush_unique_ngrams < 1:
        raise ValueError("--flush-unique-ngrams must be at least 1")
    if not args.corpus or not args.corpus.strip():
        raise ValueError("--corpus cannot be empty")
    if args.filter_min_token_len < 1:
        raise ValueError("--filter-min-token-len must be at least 1")
    if args.filter_max_token_len < args.filter_min_token_len:
        raise ValueError(
            "--filter-max-token-len cannot be less than "
            "--filter-min-token-len"
        )
    if args.filter_min_norm_len < 1:
        raise ValueError("--filter-min-norm-len must be at least 1")


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
        filter_min_token_len=getattr(args, "filter_min_token_len", 2),
        filter_max_token_len=getattr(args, "filter_max_token_len", 30),
        filter_min_norm_len=getattr(args, "filter_min_norm_len", 2),
        filter_all_stopword_ngrams=getattr(
            args, "filter_all_stopword_ngrams", False
        ),
        preserve_nasal_letters=getattr(args, "preserve_nasal_letters", False),
        filter_punctuation_boundaries=getattr(
            args, "filter_punctuation_boundaries", False
        ),
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
        export_log_every=getattr(args, "export_log_every", 10_000),
        limit_docs=getattr(args, "limit_docs", 0),
        flush_unique_ngrams=getattr(args, "flush_unique_ngrams", 250_000),
        reset=getattr(args, "reset", False),
        export_only=is_export,
        export_after_count=is_export,
        delete_only=is_delete,
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
        "extraction_datasets": "dataset and active-generation registry",
        "extraction_runs": "document checkpoints",
        "extraction_chunks": "committed chunk ledger",
        "ngram_finalization_parts": "resumable finalization checkpoints",
        "ngram_stage_v2": "staging counts",
        "ngram_final_v2": "final generation counts",
    }
    lines.append("database tables:")
    for table, columns, rows in stats["table_inventory"]:
        role = table_roles.get(table, "application table")
        lines.append(
            f"- {table}: rows={format_number(rows)} columns={columns} "
            f"role={role}"
        )

    if stats["generation_collections"]:
        lines.append("available collections (lang/corpus):")
        for lang, corpus, datasets, complete, active, latest in stats[
            "generation_collections"
        ]:
            lines.append(
                f"- {lang}/{corpus}: datasets={datasets} complete={complete} "
                f"in_progress={active} latest={latest}"
            )
    else:
        lines.append("matching selection: no data matched all filters")

    if stats["datasets"]:
        lines.append("matching immutable datasets:")
        for (
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
        ) in stats["datasets"]:
            lines.append(
                f"- {lang}/{corpus}: dataset_id={dataset_id} "
                f"artifact_id={artifact_id} policy_hash={policy_hash} "
                f"format={input_format} sample={sample} status={status} "
                f"generation={generation} created_at={created_at} "
                f"completed_at={completed_at}"
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
    if stats["generation_by_n"]:
        lines.append("matching final counts by n:")
        for dataset_id, lang, corpus, n, rows, occurrences in stats[
            "generation_by_n"
        ]:
            lines.append(
                f"- {lang}/{corpus} dataset_id={dataset_id} n={n}: "
                f"rows={format_number(rows)} "
                f"occurrences={format_number(occurrences)}"
            )

    if args.verbose and stats["top_rows"]:
        lines.append("top final rows:")
        for lang, corpus, text, n, count, norm_key, dataset_id in stats[
            "top_rows"
        ]:
            lines.append(
                f"- {lang}/{corpus} n={n} count={format_number(count)} "
                f"dataset_id={dataset_id} text={text!r} norm_key={norm_key}"
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
        "export_log_every=%d "
        "flush_unique_ngrams=%d "
        "adapter=%s "
        "filter_min_token_len=%d filter_max_token_len=%d "
        "filter_min_norm_len=%d filter_all_stopword_ngrams=%s "
        "filter_punctuation_boundaries=%s preserve_nasal_letters=%s "
        "reset=%s export_only=%s export_after_count=%s delete_only=%s",
        command.policy.lang,
        command.corpus,
        command.policy.max_n,
        command.min_count,
        command.max_results,
        command.export_n,
        command.min_export_norm_len,
        command.max_export_norm_len,
        command.export_log_every,
        command.flush_unique_ngrams,
        command.source_adapter,
        command.policy.filter_min_token_len,
        command.policy.filter_max_token_len,
        command.policy.filter_min_norm_len,
        command.policy.filter_all_stopword_ngrams,
        command.policy.filter_punctuation_boundaries,
        command.policy.preserve_nasal_letters,
        command.reset,
        command.export_only,
        command.export_after_count,
        command.delete_only,
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
