"""Reusable streaming input helpers and schema-aware format detection."""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, TextIO

UD_SCHEMA = "semordnilap.ud-jsonl"


def iter_corpus_files(path: Path, requested_format: str = "auto"):
    if path.is_file():
        yield path
        return
    if not path.is_dir():
        raise FileNotFoundError(path)

    if requested_format in {"jsonl", "ud-jsonl"}:
        patterns = ("*.jsonl", "*.jsonl.gz")
    elif requested_format == "txt":
        patterns = ("*.txt", "*.txt.gz")
    else:
        patterns = ("*.jsonl", "*.jsonl.gz", "*.txt", "*.txt.gz")

    found: set[Path] = set()
    for pattern in patterns:
        for candidate in sorted(
            path.rglob(pattern),
            key=lambda item: (len(item.relative_to(path).parts), str(item)),
        ):
            if candidate not in found:
                found.add(candidate)
                yield candidate


@contextmanager
def open_binary(path: Path) -> Iterator[BinaryIO]:
    if path.name.endswith(".gz"):
        with gzip.open(path, "rb") as stream:
            yield stream
    else:
        with path.open("rb") as stream:
            yield stream


@contextmanager
def open_text(path: Path) -> Iterator[TextIO]:
    if path.name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
            yield stream
    else:
        with path.open("r", encoding="utf-8", newline="") as stream:
            yield stream


def _first_json_value(path: Path) -> dict | None:
    with open_text(path) as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSONL while detecting {path}"
                ) from exc
            if not isinstance(value, dict):
                raise ValueError(f"JSONL records must be objects: {path}")
            return value
    return None


def detect_text_format(path: Path, requested_format: str) -> str:
    if requested_format != "auto":
        return requested_format
    name = path.name.lower()
    if name.endswith((".jsonl", ".jsonl.gz")):
        first = _first_json_value(path)
        if first and first.get("schema") == UD_SCHEMA:
            return "ud-jsonl"
        return "jsonl"
    return "txt"


def detect_corpus_format(path: Path, requested_format: str = "auto") -> str:
    if requested_format != "auto":
        return requested_format
    if not path.exists():
        name = path.name.lower()
        if name.endswith((".ud.jsonl", ".ud.jsonl.gz")):
            return "ud-jsonl"
        if name.endswith((".jsonl", ".jsonl.gz")):
            return "jsonl"
        return "txt"
    files = list(iter_corpus_files(path, "auto"))
    if not files:
        raise FileNotFoundError(f"No corpus files found in {path}")
    formats = {detect_text_format(candidate, "auto") for candidate in files}
    if len(formats) != 1:
        raise ValueError(
            f"Mixed corpus formats require an explicit --format: {formats}"
        )
    return formats.pop()


def iter_texts_from_txt(path: Path) -> Iterable[str]:
    with open_text(path) as stream:
        yield from stream


def iter_texts_from_jsonl(path: Path, text_field: str) -> Iterable[str]:
    with open_text(path) as stream:
        for lineno, line in enumerate(stream, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{lineno}") from exc
            text = row.get(text_field)
            if text:
                yield str(text)


def iter_texts(
    path: Path, requested_format: str = "auto", text_field: str = "text"
) -> Iterable[str]:
    for corpus_file in iter_corpus_files(path, requested_format):
        input_format = detect_text_format(corpus_file, requested_format)
        if input_format == "txt":
            yield from iter_texts_from_txt(corpus_file)
        elif input_format == "jsonl":
            yield from iter_texts_from_jsonl(corpus_file, text_field)
        elif input_format == "ud-jsonl":
            raise ValueError(
                "Annotated ud-jsonl is not a raw-text corpus format"
            )
        else:
            raise ValueError(f"Unsupported input format: {input_format}")
