"""Restartable compact tagged-artifact writer."""

from __future__ import annotations

import gzip
import json
import logging
import os
import re
import shutil
import threading
from dataclasses import replace
from pathlib import Path
from time import monotonic
from typing import Any

from tqdm import tqdm

from semordnilap.tagging.domain import (
    CURRENT_SCHEMA_VERSION,
    SCHEMA_NAME,
    AnnotatedDocument,
    AnnotatedSentence,
    PosTagger,
    SourceDocument,
)
from semordnilap.tagging.io import (
    SourceCursor,
    count_source_documents,
    iter_source_records,
)
from semordnilap.utils.artifacts import (
    fsync_directory,
    read_complete_manifest,
    sha256_file,
    stable_id,
    utc_now,
    write_json_atomic,
)

logger = logging.getLogger(__name__)
_BOUNDARY = re.compile(r"(?:\n\s*\n|\n|[.!?…][\"'»”)]*\s+|\s+)")


def _source_snapshot(command) -> list[dict[str, Any]]:
    from semordnilap.tagging.application import _source_snapshot as snapshot

    return snapshot(command)


def _source_artifact_id(command, snapshot: list[dict[str, Any]]) -> str:
    from semordnilap.tagging.application import _source_artifact_id as identity

    return identity(command, snapshot)


def _partial_dir(output: Path) -> Path:
    return output.with_name(output.name + ".part")


def _config(command, tagger: PosTagger) -> dict[str, Any]:
    return {
        "schema": SCHEMA_NAME,
        "schema_version": CURRENT_SCHEMA_VERSION,
        "encoding": "jsonl+gzip-shards",
        "profile": command.profile,
        "lang": command.lang,
        "input": str(command.input_path),
        "reader": {
            "input_format": command.input_format,
            "text_field": command.text_field,
            "id_field": command.id_field,
            "limit_docs": command.limit_docs,
        },
        "shard_docs": command.shard_docs,
        "max_document_chars": command.max_document_chars,
        "on_document_error": command.on_document_error,
        "tagger": tagger.metadata,
    }


def _split_ranges(text: str, maximum: int) -> list[tuple[int, int]]:
    if not maximum or len(text) <= maximum:
        return [(0, len(text))]
    ranges = []
    start = 0
    while len(text) - start > maximum:
        ceiling = start + maximum
        candidates = list(_BOUNDARY.finditer(text, start, ceiling))
        if not candidates:
            raise ValueError(
                "document contains an unsplittable span longer than "
                f"{maximum} characters"
            )
        end = candidates[-1].end()
        if end <= start:
            raise ValueError("long-document splitter made no progress")
        ranges.append((start, end))
        start = end
    if start < len(text):
        ranges.append((start, len(text)))
    return ranges


def _shift_sentence(
    sentence: AnnotatedSentence, *, offset: int, index: int
) -> AnnotatedSentence:
    tokens = tuple(
        replace(
            token,
            start_char=token.start_char + offset,
            end_char=token.end_char + offset,
        )
        for token in sentence.tokens
    )
    return replace(
        sentence,
        index=index,
        start_char=sentence.start_char + offset,
        end_char=sentence.end_char + offset,
        tokens=tokens,
    )


def _call_with_heartbeat(
    tagger: PosTagger,
    source: SourceDocument,
    *,
    heartbeat_seconds: float,
) -> AnnotatedDocument:
    stopped = threading.Event()
    started = monotonic()

    def report() -> None:
        while not stopped.wait(heartbeat_seconds):
            logger.info(
                "Still tagging document %s: chars=%d elapsed=%.1fs",
                source.doc_id,
                len(source.text),
                monotonic() - started,
            )

    thread = None
    if heartbeat_seconds > 0:
        thread = threading.Thread(target=report, daemon=True)
        thread.start()
    try:
        return tagger.annotate(source)
    finally:
        stopped.set()
        if thread is not None:
            thread.join(timeout=min(heartbeat_seconds, 0.1))


def annotate_bounded(
    tagger: PosTagger,
    source: SourceDocument,
    *,
    maximum_chars: int,
    heartbeat_seconds: float,
) -> AnnotatedDocument:
    ranges = _split_ranges(source.text, maximum_chars)
    sentences = []
    for part, (start, end) in enumerate(ranges):
        local = SourceDocument(
            doc_id=f"{source.doc_id}#part-{part + 1}",
            text=source.text[start:end],
            metadata=source.metadata,
        )
        annotated = _call_with_heartbeat(
            tagger, local, heartbeat_seconds=heartbeat_seconds
        )
        if annotated.lang != getattr(tagger, "lang", annotated.lang):
            raise ValueError("Tagger returned inconsistent languages")
        for sentence in annotated.sentences:
            sentences.append(
                _shift_sentence(
                    sentence, offset=start, index=len(sentences)
                )
            )
    metadata = dict(source.metadata)
    if len(ranges) > 1:
        metadata["tagging_chunks"] = [
            {"start_char": start, "end_char": end}
            for start, end in ranges
        ]
    lang = sentences and annotated.lang or getattr(tagger, "lang", "")
    return AnnotatedDocument(
        doc_id=source.doc_id,
        lang=lang,
        text=source.text,
        sentences=tuple(sentences),
        metadata=metadata,
    )


def _write_shard(
    directory: Path,
    index: int,
    documents: list[tuple[int, AnnotatedDocument]],
    profile: str,
) -> dict[str, Any]:
    name = f"shard-{index:06d}.ud.jsonl.gz"
    final = directory / name
    partial = directory / f"{name}.tmp"
    with partial.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            for ordinal, document in documents:
                value = document.to_dict(
                    schema_version=2,
                    profile=profile,
                    ordinal=ordinal,
                )
                compressed.write(
                    (json.dumps(value, ensure_ascii=False) + "\n").encode(
                        "utf-8"
                    )
                )
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(partial, final)
    fsync_directory(directory)
    return {
        "path": name,
        "documents": len(documents),
        "first_ordinal": documents[0][0],
        "last_ordinal": documents[-1][0],
        "bytes": final.stat().st_size,
        "sha256": sha256_file(final),
    }


def _checkpoint(
    directory: Path,
    *,
    config: dict[str, Any],
    source_snapshot: list[dict[str, Any]],
    source_artifact_id: str,
    documents: int,
    sentences: int,
    tokens: int,
    quarantined: int,
    cursor: SourceCursor | None,
    shards: list[dict[str, Any]],
    quarantine: list[dict[str, Any]],
    status: str = "writing",
) -> dict[str, Any]:
    value = {
        **config,
        "status": status,
        "updated_at": utc_now(),
        "documents": documents,
        "sentences": sentences,
        "tokens": tokens,
        "quarantined_documents": quarantined,
        "source_cursor": cursor.to_dict() if cursor else None,
        "source_snapshot": source_snapshot,
        "source_artifact_id": source_artifact_id,
        "shards": shards,
        "quarantine": quarantine,
    }
    write_json_atomic(directory / "manifest.json", value)
    return value


def _quarantine(
    directory: Path,
    ordinal: int,
    source: SourceDocument,
    error: BaseException,
) -> dict[str, Any]:
    relative = Path("quarantine") / f"document-{ordinal:012d}.json"
    path = directory / relative
    write_json_atomic(
        path,
        {
            "ordinal": ordinal,
            "doc_id": source.doc_id,
            "chars": len(source.text),
            "error_type": type(error).__name__,
            "error": str(error),
            "metadata": source.metadata,
        },
    )
    return {
        "path": str(relative),
        "ordinal": ordinal,
        "doc_id": source.doc_id,
        "sha256": sha256_file(path),
    }


def tag_corpus_sharded(command, tagger: PosTagger) -> dict[str, Any]:
    output = command.output_path
    partial = _partial_dir(output)
    config = _config(command, tagger)
    source_snapshot = _source_snapshot(command)
    source_artifact_id = _source_artifact_id(command, source_snapshot)
    if output.exists() and command.resume and not command.overwrite:
        manifest = read_complete_manifest(output)
        for key, expected in config.items():
            if manifest.get(key) != expected:
                raise ValueError(f"Completed artifact does not match {key}")
        if manifest.get("source_snapshot") != source_snapshot:
            raise ValueError("Completed artifact source corpus changed")
        logger.info("Tagged artifact is already complete: %s", output)
        return manifest
    if output.exists() and not command.overwrite:
        raise FileExistsError(f"{output} already exists. Use --force.")
    if command.overwrite:
        if partial.is_dir():
            shutil.rmtree(partial)
        elif partial.exists():
            partial.unlink()
        if output.is_dir():
            shutil.rmtree(output)
        elif output.exists():
            output.unlink()
    if partial.exists() and not command.resume:
        raise FileExistsError(
            f"Incomplete artifact exists at {partial}; use --resume or --force"
        )

    if command.resume:
        manifest_path = partial / "manifest.json"
        if not manifest_path.exists():
            raise ValueError("Cannot resume sharded output without manifest")
        state = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key, expected in config.items():
            if state.get(key) != expected:
                raise ValueError(f"Cannot resume: {key} changed")
        if state.get("source_snapshot") != source_snapshot:
            raise ValueError("Cannot resume: source corpus changed")
        documents = int(state["documents"])
        sentences = int(state["sentences"])
        tokens = int(state["tokens"])
        quarantined = int(state.get("quarantined_documents", 0))
        cursor_value = state.get("source_cursor")
        cursor = SourceCursor.from_dict(cursor_value) if cursor_value else None
        shards = list(state.get("shards") or [])
        quarantine = list(state.get("quarantine") or [])
    else:
        partial.mkdir(parents=True)
        documents = sentences = tokens = quarantined = 0
        cursor = None
        shards = []
        quarantine = []
        _checkpoint(
            partial,
            config=config,
            source_snapshot=source_snapshot,
            source_artifact_id=source_artifact_id,
            documents=0,
            sentences=0,
            tokens=0,
            quarantined=0,
            cursor=None,
            shards=[],
            quarantine=[],
        )

    total = count_source_documents(command.input_path, command.input_format)
    if command.limit_docs:
        total = min(total, command.limit_docs)
    pending: list[tuple[int, AnnotatedDocument]] = []
    pending_cursor = cursor

    def flush() -> None:
        nonlocal cursor
        if not pending:
            return
        shards.append(
            _write_shard(partial, len(shards) + 1, pending, command.profile)
        )
        cursor = pending_cursor
        pending.clear()
        _checkpoint(
            partial,
            config=config,
            source_snapshot=source_snapshot,
            source_artifact_id=source_artifact_id,
            documents=documents,
            sentences=sentences,
            tokens=tokens,
            quarantined=quarantined,
            cursor=cursor,
            shards=shards,
            quarantine=quarantine,
        )

    sources = iter_source_records(
        command.input_path,
        command.input_format,
        command.text_field,
        command.id_field,
        start_cursor=cursor,
    )
    with tqdm(
        total=total,
        initial=documents,
        desc="Tagging corpus",
        unit="doc",
        dynamic_ncols=True,
    ) as progress:
        for record in sources:
            if command.limit_docs and documents >= command.limit_docs:
                break
            ordinal = documents + 1
            try:
                document = annotate_bounded(
                    tagger,
                    record.document,
                    maximum_chars=command.max_document_chars,
                    heartbeat_seconds=command.heartbeat_seconds,
                )
                if document.lang != command.lang:
                    raise ValueError(
                        f"Tagger returned {document.lang}, expected "
                        f"{command.lang}"
                    )
            except Exception as exc:
                if command.on_document_error == "fail":
                    raise
                flush()
                quarantine.append(
                    _quarantine(partial, ordinal, record.document, exc)
                )
                documents += 1
                quarantined += 1
                cursor = record.next_cursor
                _checkpoint(
                    partial,
                    config=config,
                    source_snapshot=source_snapshot,
                    source_artifact_id=source_artifact_id,
                    documents=documents,
                    sentences=sentences,
                    tokens=tokens,
                    quarantined=quarantined,
                    cursor=cursor,
                    shards=shards,
                    quarantine=quarantine,
                )
                logger.warning(
                    "Quarantined document %s: %s", record.document.doc_id, exc
                )
            else:
                pending.append((ordinal, document))
                pending_cursor = record.next_cursor
                sentences += len(document.sentences)
                tokens += sum(len(item.tokens) for item in document.sentences)
                documents += 1
                if len(pending) >= command.shard_docs:
                    # Storage failures are fatal and must never be mislabeled
                    # as document/tagger failures.
                    flush()
            progress.update(1)
            progress.set_postfix(
                tokens=f"{tokens:,}",
                shards=len(shards),
                quarantined=quarantined,
                refresh=False,
            )
    flush()

    content = {
        "shards": [item["sha256"] for item in shards],
        "quarantine": [item["sha256"] for item in quarantine],
    }
    manifest = _checkpoint(
        partial,
        config=config,
        source_snapshot=source_snapshot,
        source_artifact_id=source_artifact_id,
        documents=documents,
        sentences=sentences,
        tokens=tokens,
        quarantined=quarantined,
        cursor=cursor,
        shards=shards,
        quarantine=quarantine,
        status="complete",
    )
    manifest["sha256"] = stable_id("tagged-content", content).split(":", 1)[1]
    manifest["artifact_id"] = stable_id(
        "tagged",
        {
            "source_artifact_id": manifest["source_artifact_id"],
            "content": content,
            "config": config,
        },
    )
    manifest["completed_at"] = utc_now()
    write_json_atomic(partial / "manifest.json", manifest)
    os.replace(partial, output)
    fsync_directory(output.parent)
    return manifest
