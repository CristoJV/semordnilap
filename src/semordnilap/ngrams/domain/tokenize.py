"""Lightweight corpus tokenization for Latin-script corpora."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator

from semordnilap.utils.text import clean_corpus_text

TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿĀ-ſ]+")


def iter_sentence_chunks(text: str):
    """Yield chunks separated by any Unicode punctuation character."""
    text = clean_corpus_text(text)
    chunk: list[str] = []
    for char in text:
        if unicodedata.category(char).startswith("P"):
            value = "".join(chunk).strip()
            if value:
                yield value
            chunk.clear()
        else:
            chunk.append(char)
    value = "".join(chunk).strip()
    if value:
        yield value


def is_letter_token(token: str) -> bool:
    return all(unicodedata.category(c).startswith("L") for c in token)


def tokenize_sentence(sentence: str) -> list[str]:
    tokens = []
    for match in TOKEN_RE.finditer(sentence.lower()):
        token = match.group(0)
        if is_letter_token(token):
            tokens.append(token)
    return tokens


def iter_text_windows(
    text: str, max_size: int
) -> Iterator[tuple[tuple[str, ...], str]]:
    """Yield lexical tokens and their punctuation-preserving surface.

    Punctuation is retained verbatim in the cleaned surface, but never becomes
    a token or contributes to n-gram size.
    """
    cleaned = clean_corpus_text(text)
    matches = list(TOKEN_RE.finditer(cleaned))

    for size in range(1, max_size + 1):
        for start in range(0, len(matches) - size + 1):
            window = matches[start : start + size]
            tokens = tuple(match.group(0).lower() for match in window)
            surface_start = 0 if start == 0 else window[0].start()
            next_index = start + size
            surface_end = (
                matches[next_index].start()
                if next_index < len(matches)
                else len(cleaned)
            )
            surface = cleaned[surface_start:surface_end].strip().lower()
            yield tokens, surface
