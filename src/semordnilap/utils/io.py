"""Reusable text input helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def iter_corpus_files(path: Path, requested_format: str = "auto"):
    if path.is_file():
        yield path
        return

    if not path.is_dir():
        raise FileNotFoundError(path)

    if requested_format == "jsonl":
        patterns = ("*.jsonl",)
    elif requested_format == "txt":
        patterns = ("*.txt",)
    else:
        patterns = ("*.jsonl", "*.txt")

    for pattern in patterns:
        yield from sorted(
            path.rglob(pattern),
            key=lambda p: (len(p.relative_to(path).parts), str(p)),
        )


def detect_text_format(path: Path, requested_format: str) -> str:
    if requested_format != "auto":
        return requested_format
    if path.suffix.lower() == ".jsonl":
        return "jsonl"
    return "txt"


def iter_texts_from_txt(path: Path) -> Iterable[str]:
    with path.open("r", encoding="utf-8") as f:
        yield from f


def iter_texts_from_jsonl(path: Path, text_field: str) -> Iterable[str]:
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at line {lineno}") from exc
            text = row.get(text_field)
            if text:
                yield text


def iter_texts(
    path: Path, requested_format: str = "auto", text_field: str = "text"
) -> Iterable[str]:
    for corpus_file in iter_corpus_files(path, requested_format):
        input_format = detect_text_format(corpus_file, requested_format)
        if input_format == "txt":
            yield from iter_texts_from_txt(corpus_file)
        elif input_format == "jsonl":
            yield from iter_texts_from_jsonl(corpus_file, text_field)
        else:
            raise ValueError(f"Unsupported input format: {input_format}")
