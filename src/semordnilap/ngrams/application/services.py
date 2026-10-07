"""Application services for n-gram extraction."""

from __future__ import annotations

import csv
import logging
from dataclasses import asdict
from collections import Counter
from time import perf_counter

from tqdm import tqdm

from semordnilap.ngrams.application.commands import ExtractNgramsCommand
from semordnilap.ngrams.domain import (
    NgramCountRepository,
    iter_ngrams_from_text,
)
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
    if command.source_adapter != "raw":
        policy_value["source_adapter"] = command.source_adapter
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
    source_paths = command.input_files or (command.input_path,)
    documents = (
        (str(index), text)
        for index, text in enumerate(
            (
                text
                for source_path in source_paths
                for text in iter_texts(
                    source_path,
                    command.input_format,
                    command.text_field,
                )
            ),
            1,
        )
    )

    committed_chunks = generated = 0
    progress = tqdm(documents, desc="Extracting corpus", unit="doc")
    for doc_index, (doc_id, text) in enumerate(progress, 1):
        if command.limit_docs and doc_index > command.limit_docs:
            break
        if doc_index <= completed_documents:
            continue
        iterator = iter_ngrams_from_text(text, command.policy)
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
                preserve_nasal_letters=command.policy.preserve_nasal_letters,
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
) -> int:
    command.output_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = perf_counter()
    rows = repository.iter_counts(
        lang=command.policy.lang,
        corpus=command.corpus,
        min_count=command.min_count,
        max_results=command.max_results,
        export_n=command.export_n,
        min_norm_len=command.min_export_norm_len,
        max_norm_len=command.max_export_norm_len,
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
            "schema_version": 2,
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
        if command.export_only:
            logger.info(
                "Export-only mode: using existing DuckDB counts for "
                "lang=%s corpus=%s",
                command.policy.lang,
                command.corpus,
            )
        else:
            final_rows = count_corpus(command, repository)
            if not command.export_after_count:
                logger.info(
                    "Skipping TSV export after extraction for lang=%s corpus=%s",
                    command.policy.lang,
                    command.corpus,
                )
                return final_rows
        return export_tsv(command, repository)
    finally:
        repository.close()
