"""Streaming Unicode tokenization shared by corpus adapters."""

from __future__ import annotations

import re
import unicodedata
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass

from semordnilap.utils.text import canonical_surface, clean_corpus_text

TOKEN_RE = re.compile(r"[^\W\d_]+(?:[-'’ʼ][^\W\d_]+)*", re.UNICODE)


@dataclass(frozen=True)
class LexicalMatch:
    text: str
    start: int
    end: int


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
    return bool(TOKEN_RE.fullmatch(unicodedata.normalize("NFC", token)))


def iter_lexical_matches(text: str) -> Iterator[LexicalMatch]:
    for match in TOKEN_RE.finditer(text):
        yield LexicalMatch(match.group(0), match.start(), match.end())


def tokenize_sentence(sentence: str) -> list[str]:
    cleaned = clean_corpus_text(sentence)
    return [match.text.casefold() for match in iter_lexical_matches(cleaned)]


def iter_text_windows(
    text: str, max_size: int
) -> Iterator[tuple[tuple[str, ...], str, str]]:
    """Yield lexical tokens, canonical key and display surface incrementally."""
    cleaned = clean_corpus_text(text)
    recent: deque[LexicalMatch] = deque(maxlen=max_size)
    for match in iter_lexical_matches(cleaned):
        recent.append(match)
        window = tuple(recent)
        for size in range(1, len(window) + 1):
            suffix = window[-size:]
            display = " ".join(
                cleaned[suffix[0].start : suffix[-1].end].split()
            )
            yield (
                tuple(item.text.casefold() for item in suffix),
                canonical_surface(display),
                display,
            )
