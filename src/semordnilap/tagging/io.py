"""Input and JSONL adapters for annotated corpora."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from semordnilap.tagging.domain import AnnotatedDocument, SourceDocument
from semordnilap.utils.io import (
    detect_text_format,
    iter_corpus_files,
    open_binary,
    open_text,
)


@dataclass(frozen=True)
class SourceCursor:
    """Position immediately after one completed source document."""

    path: str
    line_number: int
    byte_offset: int

    def to_dict(self) -> dict[str, str | int]:
        return {
            "path": self.path,
            "line_number": self.line_number,
            "byte_offset": self.byte_offset,
        }

    @classmethod
    def from_dict(cls, value: dict) -> SourceCursor:
        return cls(
            path=str(value["path"]),
            line_number=int(value["line_number"]),
            byte_offset=int(value["byte_offset"]),
        )


@dataclass(frozen=True)
class SourceRecord:
    document: SourceDocument
    next_cursor: SourceCursor


@dataclass(frozen=True)
class AnnotatedDocumentRecord:
    document: AnnotatedDocument
    next_byte_offset: int


def count_source_documents(
    path: Path,
    requested_format: str = "auto",
) -> int:
    """Count source records for progress reporting without parsing them."""
    total = 0
    for corpus_file in iter_corpus_files(path, requested_format):
        input_format = detect_text_format(corpus_file, requested_format)
        if input_format == "txt":
            total += int(corpus_file.stat().st_size > 0)
        elif input_format == "jsonl":
            with open_binary(corpus_file) as stream:
                total += sum(1 for line in stream if line.strip())
        else:
            raise ValueError(f"Unsupported input format: {input_format}")
    return total


def iter_source_documents(
    path: Path,
    requested_format: str = "auto",
    text_field: str = "text",
    id_field: str = "id",
) -> Iterator[SourceDocument]:
    for record in iter_source_records(
        path,
        requested_format,
        text_field,
        id_field,
    ):
        yield record.document


def iter_source_records(
    path: Path,
    requested_format: str = "auto",
    text_field: str = "text",
    id_field: str = "id",
    *,
    start_cursor: SourceCursor | None = None,
) -> Iterator[SourceRecord]:
    """Yield documents with a byte-addressable cursor for the next record."""
    cursor_file_found = start_cursor is None
    for corpus_file in iter_corpus_files(path, requested_format):
        corpus_file_name = str(corpus_file)
        if not cursor_file_found:
            if corpus_file_name != start_cursor.path:
                continue
            cursor_file_found = True

        input_format = detect_text_format(corpus_file, requested_format)
        if input_format == "txt":
            file_size = corpus_file.stat().st_size
            if start_cursor and corpus_file_name == start_cursor.path:
                if start_cursor.byte_offset >= file_size:
                    continue
                raise ValueError(
                    "A text source cursor must point to the end of its file"
                )
            with open_text(corpus_file) as stream:
                text = stream.read()
            if text:
                yield SourceRecord(
                    document=SourceDocument(
                        doc_id=corpus_file_name,
                        text=text,
                        metadata={"source_path": corpus_file_name},
                    ),
                    next_cursor=SourceCursor(
                        path=corpus_file_name,
                        line_number=1,
                        byte_offset=file_size,
                    ),
                )
            continue
        if input_format != "jsonl":
            raise ValueError(f"Unsupported input format: {input_format}")

        with open_binary(corpus_file) as stream:
            line_number = 0
            if start_cursor and corpus_file_name == start_cursor.path:
                stream.seek(start_cursor.byte_offset)
                line_number = start_cursor.line_number
            while raw_line := stream.readline():
                line_number += 1
                next_offset = stream.tell()
                if not raw_line.strip():
                    continue
                try:
                    value = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"Invalid JSONL at {corpus_file}:{line_number}"
                    ) from exc
                text = value.get(text_field)
                if not text:
                    continue
                doc_id = value.get(id_field)
                if doc_id is None:
                    doc_id = f"{corpus_file}:{line_number}"
                metadata = {
                    key: item
                    for key, item in value.items()
                    if key not in {text_field, id_field}
                }
                metadata["source_path"] = corpus_file_name
                metadata["source_line"] = line_number
                yield SourceRecord(
                    document=SourceDocument(str(doc_id), str(text), metadata),
                    next_cursor=SourceCursor(
                        path=corpus_file_name,
                        line_number=line_number,
                        byte_offset=next_offset,
                    ),
                )

    if not cursor_file_found:
        raise ValueError(
            f"Source cursor file is not present in the input: "
            f"{start_cursor.path}"
        )


def iter_annotated_documents(path: Path) -> Iterator[AnnotatedDocument]:
    for record in iter_annotated_document_records(path):
        yield record.document


def iter_annotated_document_records(
    path: Path,
    *,
    start_byte_offset: int = 0,
) -> Iterator[AnnotatedDocumentRecord]:
    """Yield annotated documents and the byte offset after each JSONL row."""
    files = (
        [path]
        if path.is_file()
        else sorted({*path.rglob("*.jsonl"), *path.rglob("*.jsonl.gz")})
    )
    if not files:
        raise FileNotFoundError(path)
    if start_byte_offset and len(files) != 1:
        raise ValueError("A byte offset can only resume one annotated file")
    for corpus_file in files:
        with open_binary(corpus_file) as stream:
            if start_byte_offset:
                stream.seek(start_byte_offset)
            record_number = 0
            while raw_line := stream.readline():
                record_number += 1
                next_offset = stream.tell()
                if not raw_line.strip():
                    continue
                try:
                    value = json.loads(raw_line)
                    yield AnnotatedDocumentRecord(
                        document=AnnotatedDocument.from_dict(value),
                        next_byte_offset=next_offset,
                    )
                except (
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                    KeyError,
                    TypeError,
                    ValueError,
                ) as exc:
                    raise ValueError(
                        "Invalid annotated JSONL at "
                        f"{corpus_file} after byte {start_byte_offset}, "
                        f"record {record_number}"
                    ) from exc
