"""Application services for n-gram extraction."""

from __future__ import annotations

import csv
import logging
from collections import Counter
from time import perf_counter

from tqdm import tqdm

from semordnilap.ngrams.application.commands import ExtractNgramsCommand
from semordnilap.ngrams.domain import (
    NgramCountRepository,
    extract_counts_from_text,
)
from semordnilap.utils.io import iter_texts

logger = logging.getLogger(__name__)


def flush_counts(
    repository: NgramCountRepository,
    counts: Counter[tuple[str, ...]],
    command: ExtractNgramsCommand,
) -> None:
    if not counts:
        return
    logger.info(
        "Flushing %d unique n-grams after %d pending occurrences",
        len(counts),
        counts.total(),
    )
    repository.add_counts(
        counts,
        lang=command.policy.lang,
        corpus=command.corpus,
        fold_nasal_letters=command.policy.fold_nasal_letters,
    )
    counts.clear()


def count_corpus(
    command: ExtractNgramsCommand, repository: NgramCountRepository
) -> None:
    pending_counts: Counter[tuple[str, ...]] = Counter()
    docs_in_chunk = 0

    if command.reset:
        repository.reset_counts(
            lang=command.policy.lang,
            corpus=command.corpus,
        )
    else:
        existing = repository.count_entries(
            lang=command.policy.lang,
            corpus=command.corpus,
        )
        if existing:
            logger.info(
                "Found %d existing rows for lang=%s corpus=%s; "
                "new counts will be added. Use --reset to recompute.",
                existing,
                command.policy.lang,
                command.corpus,
            )

    for doc_index, text in enumerate(
        tqdm(
            iter_texts(
                command.input_path,
                command.input_format,
                command.text_field,
            ),
            desc="Reading corpus",
            unit="doc",
        ),
        1,
    ):
        if command.limit_docs and doc_index > command.limit_docs:
            break

        pending_counts.update(extract_counts_from_text(text, command.policy))
        docs_in_chunk += 1

        should_flush_docs = command.chunk_docs and (
            docs_in_chunk >= command.chunk_docs
        )
        should_flush_uniques = command.flush_unique_ngrams and (
            len(pending_counts) >= command.flush_unique_ngrams
        )

        if should_flush_docs or should_flush_uniques:
            flush_counts(repository, pending_counts, command)
            docs_in_chunk = 0

    flush_counts(repository, pending_counts, command)


def export_tsv(
    command: ExtractNgramsCommand,
    repository: NgramCountRepository,
    *,
    source: str | None = None,
) -> int:
    command.output_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = perf_counter()
    export_source = source or command.export_source
    rows = repository.iter_counts(
        lang=command.policy.lang,
        corpus=command.corpus,
        min_count=command.min_count,
        max_results=command.max_results,
        export_n=command.export_n,
        min_norm_len=command.min_export_norm_len,
        max_norm_len=command.max_export_norm_len,
        source=export_source,
    )

    with command.output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "lang",
                "corpus",
                "text",
                "n",
                "count",
                "score",
                "norm_key",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        exported = 0
        for row in rows:
            writer.writerow(
                {
                    "lang": row.lang,
                    "corpus": row.corpus,
                    "text": row.text,
                    "n": row.n,
                    "count": row.count,
                    "score": row.score(command.policy),
                    "norm_key": row.norm_key,
                }
            )
            exported += 1
            if (
                command.export_log_every
                and exported % command.export_log_every == 0
            ):
                logger.info(
                    "Exported %d n-grams to %s in %.2fs",
                    exported,
                    command.output_path,
                    perf_counter() - started_at,
                )

    logger.info(
        "Finished TSV export: %d n-grams written to %s in %.2fs",
        exported,
        command.output_path,
        perf_counter() - started_at,
    )
    return exported


def compact_counts(
    command: ExtractNgramsCommand, repository: NgramCountRepository
) -> int:
    logger.info(
        "Compacting counts for lang=%s corpus=%s n=%d",
        command.policy.lang,
        command.corpus,
        command.compact_n,
    )
    return repository.compact_counts(
        lang=command.policy.lang,
        corpus=command.corpus,
        n=command.compact_n,
    )


def compact_one(
    command: ExtractNgramsCommand,
    repository: NgramCountRepository,
    *,
    n: int,
    step: int,
    total_steps: int,
) -> int:
    logger.info(
        "Compaction step %d/%d started: lang=%s corpus=%s n=%d",
        step,
        total_steps,
        command.policy.lang,
        command.corpus,
        n,
    )
    started_at = perf_counter()
    compacted = repository.compact_counts(
        lang=command.policy.lang,
        corpus=command.corpus,
        n=n,
    )
    logger.info(
        "Compaction step %d/%d finished: lang=%s corpus=%s n=%d rows=%d "
        "elapsed=%.2fs",
        step,
        total_steps,
        command.policy.lang,
        command.corpus,
        n,
        compacted,
        perf_counter() - started_at,
    )
    return compacted


def compact_all_counts(
    command: ExtractNgramsCommand, repository: NgramCountRepository
) -> int:
    total = 0
    n_values = list(range(1, command.policy.max_n + 1))
    logger.info(
        "Starting progressive compaction for lang=%s corpus=%s n_values=%s",
        command.policy.lang,
        command.corpus,
        ",".join(str(n) for n in n_values),
    )
    for step, n in enumerate(n_values, 1):
        total += compact_one(
            command,
            repository,
            n=n,
            step=step,
            total_steps=len(n_values),
        )
    logger.info(
        "Finished progressive compaction for lang=%s corpus=%s: %d rows",
        command.policy.lang,
        command.corpus,
        total,
    )
    return total


def delete_counts(
    command: ExtractNgramsCommand, repository: NgramCountRepository
) -> int:
    deleted = repository.delete_counts(
        lang=command.policy.lang,
        corpus=command.corpus,
    )
    total = sum(deleted.values())
    logger.info(
        "Deleted %d rows for lang=%s corpus=%s",
        total,
        command.policy.lang,
        command.corpus,
    )
    return total


def run_extraction(
    command: ExtractNgramsCommand, repository: NgramCountRepository
) -> int:
    try:
        if command.delete_only:
            return delete_counts(command, repository)
        if command.compact_only:
            if command.compact_n:
                return compact_counts(command, repository)
            return compact_all_counts(command, repository)
        export_source_override = None
        if command.export_only:
            logger.info(
                "Export-only mode: using existing DuckDB counts for "
                "lang=%s corpus=%s",
                command.policy.lang,
                command.corpus,
            )
        else:
            count_corpus(command, repository)
            compacted = 0
            if command.compact_after_count:
                compacted = compact_all_counts(command, repository)
                if command.export_source == "auto":
                    export_source_override = "compact"
            else:
                logger.info(
                    "Skipping automatic compaction after extraction for "
                    "lang=%s corpus=%s",
                    command.policy.lang,
                    command.corpus,
                )
            if not command.export_after_count:
                logger.info(
                    "Skipping TSV export after extraction for lang=%s corpus=%s",
                    command.policy.lang,
                    command.corpus,
                )
                return compacted
        return export_tsv(
            command,
            repository,
            source=export_source_override,
        )
    finally:
        repository.close()
