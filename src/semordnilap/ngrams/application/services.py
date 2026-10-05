"""Application services for n-gram extraction."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict
from collections import Counter
from time import perf_counter

from tqdm import tqdm

from semordnilap.ngrams.application.commands import ExtractNgramsCommand
from semordnilap.ngrams.domain import (
    NgramKey,
    NgramCountRepository,
    TaggedNgramKey,
    iter_ngrams_from_annotated_document,
    iter_ngrams_from_text,
)
from semordnilap.tagging.io import iter_annotated_documents
from semordnilap.utils.io import iter_texts
from semordnilap.ngrams.domain.normalize import NORMALIZATION_VERSION
from semordnilap.utils.artifacts import (
    ArtifactLock,
    atomic_output,
    compute_artifact_id,
    manifest_path,
    read_complete_manifest,
    sha256_file,
    stable_id,
    utc_now,
    write_json_atomic,
)

logger = logging.getLogger(__name__)


def flush_counts(
    repository: NgramCountRepository,
    counts: Counter[NgramKey],
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


def flush_tagged_counts(
    repository: NgramCountRepository,
    counts: Counter[TaggedNgramKey],
    command: ExtractNgramsCommand,
) -> None:
    if not counts:
        return
    logger.info(
        "Flushing %d unique tagged n-grams after %d pending occurrences",
        len(counts),
        counts.total(),
    )
    repository.add_tagged_counts(
        counts,
        lang=command.policy.lang,
        corpus=command.corpus,
        fold_nasal_letters=command.policy.fold_nasal_letters,
    )
    counts.clear()


def count_corpus(
    command: ExtractNgramsCommand, repository: NgramCountRepository
) -> int:
    if not hasattr(repository, "prepare_extraction"):
        raise TypeError("Repository does not support idempotent extraction")
    if command.input_path is None:
        raise ValueError("Extraction requires an input path")

    input_manifest = None
    if manifest_path(command.input_path).exists():
        input_manifest = read_complete_manifest(command.input_path)
    elif (
        command.input_format == "ud-jsonl"
        and not command.allow_incomplete_input
    ):
        read_complete_manifest(command.input_path)
    artifact_id = (
        input_manifest["artifact_id"]
        if input_manifest
        else compute_artifact_id(command.input_path)
    )
    policy_value = {
        **asdict(command.policy),
        "normalization_version": NORMALIZATION_VERSION,
        "surface_version": "document-span-v2",
        "input_format": command.input_format,
        "text_field": command.text_field,
        "limit_docs": command.limit_docs,
    }
    policy_hash = stable_id("policy", policy_value)
    dataset_id = stable_id(
        "ngram-dataset",
        {
            "artifact_id": artifact_id,
            "policy_hash": policy_hash,
            "lang": command.policy.lang,
            "corpus": command.corpus,
        },
    )
    run_id = stable_id("extraction-run", {"dataset_id": dataset_id})
    state = repository.prepare_extraction(
        dataset_id=dataset_id,
        run_id=run_id,
        artifact_id=artifact_id,
        policy_hash=policy_hash,
        lang=command.policy.lang,
        corpus=command.corpus,
        input_format=command.input_format,
        policy=policy_value,
        sample=bool(command.limit_docs),
        restart=command.reset,
    )
    if state["status"] == "complete":
        logger.info("Extraction is already complete; replay is a no-op")
        return repository.finalize_extraction(
            dataset_id=dataset_id, run_id=run_id
        )

    completed_documents = int(state["completed_documents"])
    tagged = command.input_format == "ud-jsonl"
    if tagged:
        documents = (
            (document.doc_id, document.text, document)
            for document in iter_annotated_documents(command.input_path)
        )
        description = "Extracting annotated corpus"
    else:
        documents = (
            (str(index), text, text)
            for index, text in enumerate(
                iter_texts(
                    command.input_path,
                    command.input_format,
                    command.text_field,
                ),
                1,
            )
        )
        description = "Extracting corpus"

    committed_chunks = generated = 0
    progress = tqdm(documents, desc=description, unit="doc")
    for doc_index, (doc_id, text, document) in enumerate(progress, 1):
        if command.limit_docs and doc_index > command.limit_docs:
            break
        if doc_index <= completed_documents:
            continue
        iterator = (
            iter_ngrams_from_annotated_document(document, command.policy)
            if tagged
            else iter_ngrams_from_text(text, command.policy)
        )
        pending = Counter()
        segment = 0

        def commit(*, final: bool) -> None:
            nonlocal pending, segment, committed_chunks, generated
            chunk_id = f"document-{doc_index:012d}-segment-{segment:06d}"
            digest = stable_id(
                "ngram-chunk",
                {
                    "artifact_id": artifact_id,
                    "doc_id": doc_id,
                    "document_ordinal": doc_index,
                    "text_digest": stable_id("text", text),
                    "segment": segment,
                    "final": final,
                    "policy_hash": policy_hash,
                },
            )
            inserted = repository.commit_extraction_chunk(
                dataset_id=dataset_id,
                run_id=run_id,
                chunk_id=chunk_id,
                digest=digest,
                document_ordinal=doc_index,
                segment=segment,
                final_segment=final,
                counts=pending,
                lang=command.policy.lang,
                corpus=command.corpus,
                fold_nasal_letters=command.policy.fold_nasal_letters,
                tagged=tagged,
            )
            if inserted:
                committed_chunks += 1
                generated += pending.total()
            pending.clear()
            segment += 1

        for ngram in iterator:
            pending[ngram] += 1
            if len(pending) >= command.flush_unique_ngrams:
                commit(final=False)
        commit(final=True)
        progress.set_postfix(
            chunks=committed_chunks,
            occurrences=generated,
            unique_pending=len(pending),
            refresh=False,
        )

    return repository.finalize_extraction(dataset_id=dataset_id, run_id=run_id)


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
        dataset_id=command.dataset_id,
    )

    with ArtifactLock(command.output_path):
        with atomic_output(command.output_path) as f:
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
                    "has_punctuation",
                    "upos_counts",
                    "cross_sentence_count",
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
                        "has_punctuation": row.has_punctuation,
                        "upos_counts": json.dumps(
                            dict(row.upos_counts),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        "cross_sentence_count": row.cross_sentence_count,
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
        digest = sha256_file(command.output_path)
        manifest = {
            "schema": "semordnilap.ngram-tsv",
            "schema_version": 1,
            "status": "complete",
            "created_at": utc_now(),
            "sha256": digest,
            "artifact_id": stable_id("ngram-tsv", {"sha256": digest}),
            "lang": command.policy.lang,
            "corpus": command.corpus,
            "rows": exported,
        }
        write_json_atomic(manifest_path(command.output_path), manifest)

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
            compacted = count_corpus(command, repository)
            if command.compact_after_count and not getattr(
                repository, "generation_storage", False
            ):
                compacted = compact_all_counts(command, repository)
                if command.export_source == "auto":
                    export_source_override = "compact"
            elif not command.compact_after_count:
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
