"""Application services for contextual corpus tagging."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tqdm import tqdm

from semordnilap.tagging.domain import PosTagger, SCHEMA_NAME, SCHEMA_VERSION
from semordnilap.tagging.io import (
    SourceCursor,
    count_source_documents,
    iter_annotated_document_records,
    iter_source_records,
)
from semordnilap.utils.io import iter_corpus_files
from semordnilap.utils.artifacts import (
    ArtifactLock,
    read_complete_manifest,
    sha256_file,
    stable_id,
)

logger = logging.getLogger(__name__)

CHECKPOINT_VERSION = 2
RECOVERY_CHECKPOINT_DOCS = 100
RECOVERY_CHECKPOINT_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class TagCorpusCommand:
    input_path: Path
    output_path: Path
    lang: str
    input_format: str = "auto"
    text_field: str = "text"
    id_field: str = "id"
    limit_docs: int = 0
    overwrite: bool = False
    resume: bool = False
    checkpoint_docs: int = 10
    output_format: str = "ud-jsonl-v1"
    profile: str = "compact"
    shard_docs: int = 25
    max_document_chars: int = 250_000
    on_document_error: str = "quarantine"
    heartbeat_seconds: float = 30.0


@dataclass(frozen=True)
class ResumeState:
    documents: int = 0
    sentences: int = 0
    tokens: int = 0
    partial_byte_offset: int = 0
    source_cursor: SourceCursor | None = None


def manifest_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".meta.json")


def partial_output_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".part")


def partial_manifest_path(output_path: Path) -> Path:
    return partial_output_path(output_path).with_suffix(
        partial_output_path(output_path).suffix + ".meta.json"
    )


def _truncate_incomplete_line(path: Path) -> None:
    """Discard only a trailing partial JSONL record after a hard stop."""
    if not path.exists() or path.stat().st_size == 0:
        return
    with path.open("r+b") as stream:
        end = stream.seek(0, os.SEEK_END)
        stream.seek(end - 1)
        if stream.read(1) == b"\n":
            return

        position = end
        while position:
            chunk_size = min(position, 64 * 1024)
            position -= chunk_size
            stream.seek(position)
            chunk = stream.read(chunk_size)
            newline = chunk.rfind(b"\n")
            if newline >= 0:
                stream.truncate(position + newline + 1)
                return
        stream.truncate(0)


def _truncate_to_confirmed_offset(path: Path, offset: int) -> None:
    size = path.stat().st_size
    if offset < 0 or offset > size:
        raise ValueError(
            f"Invalid confirmed partial offset {offset} for {size}-byte file"
        )
    if offset:
        with path.open("rb") as stream:
            stream.seek(offset - 1)
            if stream.read(1) != b"\n":
                raise ValueError(
                    "Cannot resume: checkpoint offset is not at a JSONL "
                    "record boundary"
                )
    if size > offset:
        logger.warning(
            "Discarding %d uncheckpointed bytes from %s; those documents "
            "will be tagged again",
            size - offset,
            path,
        )
        with path.open("r+b") as stream:
            stream.truncate(offset)
            stream.flush()
            os.fsync(stream.fileno())


def _write_json_atomic(path: Path, value: dict) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp_path, path)
    if os.name == "posix":
        directory = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def _run_metadata(command: TagCorpusCommand, tagger: PosTagger) -> dict:
    return {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "lang": command.lang,
        "input": str(command.input_path),
        "output": str(command.output_path),
        "tagger": tagger.metadata,
    }


def _reader_metadata(command: TagCorpusCommand) -> dict[str, Any]:
    return {
        "input_format": command.input_format,
        "text_field": command.text_field,
        "id_field": command.id_field,
        "limit_docs": command.limit_docs,
    }


def _source_snapshot(command: TagCorpusCommand) -> list[dict[str, Any]]:
    snapshot = []
    for path in iter_corpus_files(command.input_path, command.input_format):
        stat = path.stat()
        snapshot.append(
            {
                "path": str(path),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha256_file(path),
            }
        )
    return snapshot


def _source_artifact_id(
    command: TagCorpusCommand, snapshot: list[dict[str, Any]]
) -> str:
    if manifest_path(command.input_path).exists():
        return str(read_complete_manifest(command.input_path)["artifact_id"])
    return stable_id("source", snapshot)


def _write_checkpoint(
    command: TagCorpusCommand,
    tagger: PosTagger,
    state: ResumeState,
    *,
    status: str = "in_progress",
    recovery_target_bytes: int | None = None,
    source_snapshot: list[dict[str, Any]] | None = None,
) -> None:
    checkpoint = {
        **_run_metadata(command, tagger),
        "checkpoint_version": CHECKPOINT_VERSION,
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "documents": state.documents,
        "sentences": state.sentences,
        "tokens": state.tokens,
        "partial_byte_offset": state.partial_byte_offset,
        "source_cursor": (
            state.source_cursor.to_dict() if state.source_cursor else None
        ),
        "reader": _reader_metadata(command),
        "source_snapshot": (
            source_snapshot
            if source_snapshot is not None
            else _source_snapshot(command)
        ),
        "source_artifact_id": _source_artifact_id(
            command, source_snapshot or _source_snapshot(command)
        ),
    }
    if recovery_target_bytes is not None:
        checkpoint["recovery_target_bytes"] = recovery_target_bytes
    _write_json_atomic(partial_manifest_path(command.output_path), checkpoint)


def _read_and_validate_checkpoint(
    command: TagCorpusCommand,
    tagger: PosTagger,
    source_snapshot: list[dict[str, Any]],
) -> dict:
    path = partial_manifest_path(command.output_path)
    if not path.exists():
        raise ValueError(
            "Cannot resume: partial output has no checkpoint metadata. "
            "Use --force to start again."
        )
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    expected = _run_metadata(command, tagger)
    for field in ("schema", "schema_version", "lang", "input"):
        if checkpoint.get(field) != expected[field]:
            raise ValueError(
                f"Cannot resume: checkpoint {field!r} does not match the "
                "current tagging run"
            )
    checkpoint_tagger = checkpoint.get("tagger") or {}
    expected_tagger = expected["tagger"]
    if checkpoint.get("checkpoint_version") == CHECKPOINT_VERSION:
        tagger_matches = checkpoint_tagger == expected_tagger
    else:
        tagger_matches = all(
            expected_tagger.get(key) == value
            for key, value in checkpoint_tagger.items()
        )
    if not tagger_matches:
        raise ValueError(
            "Cannot resume: checkpoint 'tagger' does not match the current "
            "tagging run"
        )
    if checkpoint.get("checkpoint_version") == CHECKPOINT_VERSION:
        if checkpoint.get("reader") != _reader_metadata(command):
            raise ValueError(
                "Cannot resume: input reader options do not match the "
                "checkpoint"
            )
        checkpoint_snapshot = checkpoint.get("source_snapshot") or []
        comparable_snapshot = [
            {key: current[key] for key in previous if key in current}
            for previous, current in zip(checkpoint_snapshot, source_snapshot)
        ]
        if (
            len(checkpoint_snapshot) != len(source_snapshot)
            or checkpoint_snapshot != comparable_snapshot
        ):
            raise ValueError(
                "Cannot resume: source corpus files changed after the "
                "checkpoint was written"
            )
    return checkpoint


def _state_from_checkpoint(checkpoint: dict) -> ResumeState:
    cursor_value = checkpoint.get("source_cursor")
    return ResumeState(
        documents=int(checkpoint.get("documents", 0)),
        sentences=int(checkpoint.get("sentences", 0)),
        tokens=int(checkpoint.get("tokens", 0)),
        partial_byte_offset=int(checkpoint.get("partial_byte_offset", 0)),
        source_cursor=(
            SourceCursor.from_dict(cursor_value) if cursor_value else None
        ),
    )


def _validated_fast_resume(
    partial_path: Path, checkpoint: dict
) -> ResumeState | None:
    """Return an O(1) resume state, or None when re-indexing is required."""
    if checkpoint.get("checkpoint_version") != CHECKPOINT_VERSION:
        return None
    if checkpoint.get("status") == "recovering":
        return None

    state = _state_from_checkpoint(checkpoint)
    size = partial_path.stat().st_size
    if size < state.partial_byte_offset:
        logger.warning(
            "Partial output is shorter than its checkpoint (%d < %d bytes); "
            "rebuilding resume offsets from the available data",
            size,
            state.partial_byte_offset,
        )
        return None
    if state.documents and state.source_cursor is None:
        logger.warning(
            "Checkpoint has no source cursor; rebuilding resume offsets"
        )
        return None
    _truncate_to_confirmed_offset(partial_path, state.partial_byte_offset)
    return state


def _index_partial_output(
    command: TagCorpusCommand,
    tagger: PosTagger,
    partial_path: Path,
    checkpoint: dict,
    source_snapshot: list[dict[str, Any]],
) -> ResumeState:
    """Build byte cursors for a legacy or interrupted recovery checkpoint."""
    _truncate_incomplete_line(partial_path)
    available_bytes = partial_path.stat().st_size

    can_continue_recovery = (
        checkpoint.get("checkpoint_version") == CHECKPOINT_VERSION
        and checkpoint.get("status") == "recovering"
    )
    if can_continue_recovery:
        state = _state_from_checkpoint(checkpoint)
        target_bytes = int(
            checkpoint.get("recovery_target_bytes", available_bytes)
        )
        if target_bytes != available_bytes:
            raise ValueError(
                "Cannot resume partial indexing because the partial output "
                "changed since recovery started"
            )
        if state.partial_byte_offset > target_bytes:
            raise ValueError(
                "Cannot resume: recovery checkpoint is beyond partial output"
            )
    else:
        state = ResumeState()
        target_bytes = available_bytes
        logger.info(
            "The partial output has no usable byte cursor. It will be "
            "validated and indexed once; future resumes will be immediate."
        )

    sources = iter_source_records(
        command.input_path,
        command.input_format,
        command.text_field,
        command.id_field,
        start_cursor=state.source_cursor,
    )
    annotated = iter_annotated_document_records(
        partial_path,
        start_byte_offset=state.partial_byte_offset,
    )
    last_checkpoint_docs = state.documents
    last_checkpoint_offset = state.partial_byte_offset

    with tqdm(
        total=target_bytes,
        initial=state.partial_byte_offset,
        desc="Indexing partial output",
        unit="B",
        unit_scale=True,
        dynamic_ncols=True,
    ) as progress:
        for record in annotated:
            try:
                source_record = next(sources)
            except StopIteration as exc:
                raise ValueError(
                    "Partial output contains more documents than the source "
                    "corpus"
                ) from exc

            document = record.document
            source = source_record.document
            if document.lang != command.lang:
                raise ValueError(
                    f"Partial output contains lang={document.lang!r}, "
                    f"expected {command.lang!r}"
                )
            if (
                document.doc_id != source.doc_id
                or document.text != source.text
            ):
                raise ValueError(
                    "Cannot resume: the source corpus differs at completed "
                    f"document {state.documents + 1}"
                )

            previous_offset = state.partial_byte_offset
            state = ResumeState(
                documents=state.documents + 1,
                sentences=state.sentences + len(document.sentences),
                tokens=state.tokens
                + sum(len(sentence.tokens) for sentence in document.sentences),
                partial_byte_offset=record.next_byte_offset,
                source_cursor=source_record.next_cursor,
            )
            progress.update(state.partial_byte_offset - previous_offset)
            progress.set_postfix(
                docs=f"{state.documents:,}",
                tokens=f"{state.tokens:,}",
                refresh=False,
            )

            checkpoint_due = (
                state.documents - last_checkpoint_docs
                >= RECOVERY_CHECKPOINT_DOCS
                or state.partial_byte_offset - last_checkpoint_offset
                >= RECOVERY_CHECKPOINT_BYTES
            )
            if checkpoint_due:
                _write_checkpoint(
                    command,
                    tagger,
                    state,
                    status="recovering",
                    recovery_target_bytes=target_bytes,
                    source_snapshot=source_snapshot,
                )
                last_checkpoint_docs = state.documents
                last_checkpoint_offset = state.partial_byte_offset

    if state.partial_byte_offset != target_bytes:
        raise ValueError(
            "Partial output indexing did not finish at the expected byte "
            "offset"
        )
    _write_checkpoint(command, tagger, state, source_snapshot=source_snapshot)
    logger.info(
        "Indexed and validated %d completed documents in %s",
        state.documents,
        partial_path,
    )
    return state


def _prepare_resume_state(
    command: TagCorpusCommand,
    tagger: PosTagger,
    partial_path: Path,
    checkpoint: dict,
    source_snapshot: list[dict[str, Any]],
) -> ResumeState:
    state = _validated_fast_resume(partial_path, checkpoint)
    if state is not None:
        logger.info(
            "Resume cursor loaded at document %d (partial byte %d); no "
            "deserialization scan is needed",
            state.documents,
            state.partial_byte_offset,
        )
        return state
    return _index_partial_output(
        command, tagger, partial_path, checkpoint, source_snapshot
    )


def _final_manifest(
    command: TagCorpusCommand,
    tagger: PosTagger,
    state: ResumeState,
    source_snapshot: list[dict[str, Any]],
) -> dict:
    manifest = {
        **_run_metadata(command, tagger),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "documents": state.documents,
        "sentences": state.sentences,
        "tokens": state.tokens,
        "status": "complete",
        "sha256": sha256_file(command.output_path),
        "source_artifact_id": _source_artifact_id(command, source_snapshot),
    }
    manifest["artifact_id"] = stable_id(
        "tagged",
        {
            "sha256": manifest["sha256"],
            "source_artifact_id": manifest["source_artifact_id"],
            "tagger": manifest["tagger"],
            "schema": manifest["schema"],
            "schema_version": manifest["schema_version"],
        },
    )
    return manifest


def _tag_corpus_unlocked(command: TagCorpusCommand, tagger: PosTagger) -> dict:
    partial_path = partial_output_path(command.output_path)
    checkpoint_path = partial_manifest_path(command.output_path)
    promoted_recovery = (
        command.resume
        and command.output_path.exists()
        and checkpoint_path.exists()
        and not partial_path.exists()
    )
    if promoted_recovery:
        logger.info("Recovering manifest after completed output promotion")
        source_snapshot = _source_snapshot(command)
        checkpoint = _read_and_validate_checkpoint(
            command, tagger, source_snapshot
        )
        state = _state_from_checkpoint(checkpoint)
        if command.output_path.stat().st_size != state.partial_byte_offset:
            raise ValueError(
                "Cannot finalize promoted output: size differs from checkpoint"
            )
        manifest = _final_manifest(command, tagger, state, source_snapshot)
        _write_json_atomic(manifest_path(command.output_path), manifest)
        checkpoint_path.unlink(missing_ok=True)
        return manifest
    if (
        command.output_path.exists()
        and not command.overwrite
        and not (command.resume and partial_path.exists())
    ):
        raise FileExistsError(
            f"{command.output_path} already exists. Use --force to overwrite it."
        )
    if command.checkpoint_docs < 1:
        raise ValueError("checkpoint_docs must be at least 1")
    command.output_path.parent.mkdir(parents=True, exist_ok=True)

    if command.overwrite:
        partial_path.unlink(missing_ok=True)
        checkpoint_path.unlink(missing_ok=True)
    elif partial_path.exists() and not command.resume:
        raise FileExistsError(
            f"Incomplete tagging output exists at {partial_path}. Use "
            "--resume to continue it or --force to start again."
        )

    logger.info("Hashing source artifact for reproducible resume metadata")
    source_snapshot = _source_snapshot(command)
    if command.resume:
        checkpoint = _read_and_validate_checkpoint(
            command, tagger, source_snapshot
        )
        if not partial_path.exists():
            raise ValueError(
                f"Cannot resume: partial output does not exist at {partial_path}"
            )
        state = _prepare_resume_state(
            command,
            tagger,
            partial_path,
            checkpoint,
            source_snapshot,
        )
    else:
        partial_path.touch()
        state = ResumeState()
        _write_checkpoint(
            command, tagger, state, source_snapshot=source_snapshot
        )

    logger.info("Counting source documents in %s", command.input_path)
    source_total = count_source_documents(
        command.input_path, command.input_format
    )
    if command.limit_docs:
        source_total = min(source_total, command.limit_docs)
    if state.documents > source_total:
        raise ValueError(
            f"Partial output has {state.documents} documents but the current "
            f"input has only {source_total}"
        )
    logger.info("Found %d source documents to tag", source_total)
    if state.documents:
        logger.info(
            "Resuming after %d completed documents from %s",
            state.documents,
            partial_path,
        )

    document_count = state.documents
    sentence_count = state.sentences
    token_count = state.tokens
    source_cursor = state.source_cursor
    try:
        with partial_path.open("a", encoding="utf-8") as output:
            sources = iter_source_records(
                command.input_path,
                command.input_format,
                command.text_field,
                command.id_field,
                start_cursor=source_cursor,
            )
            with tqdm(
                total=source_total,
                initial=document_count,
                desc="Tagging corpus",
                unit="doc",
                dynamic_ncols=True,
            ) as progress:
                for source_record in sources:
                    if (
                        command.limit_docs
                        and document_count >= command.limit_docs
                    ):
                        break
                    source = source_record.document
                    progress.set_postfix(
                        current=str(source.doc_id)[:32],
                        chars=f"{len(source.text):,}",
                        refresh=True,
                    )
                    document = tagger.annotate(source)
                    if document.lang != command.lang:
                        raise ValueError(
                            f"Tagger returned lang={document.lang!r}, "
                            f"expected {command.lang!r}"
                        )
                    output.write(
                        json.dumps(document.to_dict(), ensure_ascii=False)
                        + "\n"
                    )
                    document_count += 1
                    sentence_count += len(document.sentences)
                    token_count += sum(
                        len(sentence.tokens) for sentence in document.sentences
                    )
                    source_cursor = source_record.next_cursor
                    progress.update(1)
                    progress.set_postfix(
                        sentences=f"{sentence_count:,}",
                        tokens=f"{token_count:,}",
                        refresh=True,
                    )
                    if document_count % command.checkpoint_docs == 0:
                        output.flush()
                        os.fsync(output.fileno())
                        state = ResumeState(
                            document_count,
                            sentence_count,
                            token_count,
                            os.fstat(output.fileno()).st_size,
                            source_cursor,
                        )
                        _write_checkpoint(
                            command,
                            tagger,
                            state,
                            source_snapshot=source_snapshot,
                        )
            output.flush()
            os.fsync(output.fileno())
            state = ResumeState(
                document_count,
                sentence_count,
                token_count,
                os.fstat(output.fileno()).st_size,
                source_cursor,
            )
            _write_checkpoint(
                command, tagger, state, source_snapshot=source_snapshot
            )
    except BaseException:
        logger.warning(
            "Tagging interrupted after %d documents. Resume with --resume; "
            "partial output: %s",
            document_count,
            partial_path,
        )
        raise

    os.replace(partial_path, command.output_path)
    manifest = _final_manifest(
        command,
        tagger,
        ResumeState(
            document_count,
            sentence_count,
            token_count,
            command.output_path.stat().st_size,
            source_cursor,
        ),
        source_snapshot,
    )
    _write_json_atomic(manifest_path(command.output_path), manifest)
    checkpoint_path.unlink(missing_ok=True)
    return manifest


def tag_corpus(command: TagCorpusCommand, tagger: PosTagger) -> dict:
    with ArtifactLock(command.output_path):
        if command.output_format == "ud-jsonl-v2":
            from semordnilap.tagging.sharded import tag_corpus_sharded

            return tag_corpus_sharded(command, tagger)
        if command.output_format != "ud-jsonl-v1":
            raise ValueError(
                f"Unsupported tagging output format: {command.output_format}"
            )
        return _tag_corpus_unlocked(command, tagger)
