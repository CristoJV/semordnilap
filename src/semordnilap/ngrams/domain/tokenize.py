"""Lightweight corpus tokenization for Latin-script corpora."""

from __future__ import annotations

import re
import unicodedata

from semordnilap.utils.text import clean_corpus_text

SENTENCE_BOUNDARY_RE = re.compile(r"[.!?;:¡!¿?…]+")
TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿĀ-ſ]+")


def iter_sentence_chunks(text: str):
    """Yield chunks without crossing strong punctuation or line boundaries."""
    text = clean_corpus_text(text)
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for chunk in SENTENCE_BOUNDARY_RE.split(line):
            chunk = chunk.strip()
            if chunk:
                yield chunk


def is_letter_token(token: str) -> bool:
    return all(unicodedata.category(c).startswith("L") for c in token)


def tokenize_sentence(sentence: str) -> list[str]:
    tokens = []
    for match in TOKEN_RE.finditer(sentence.lower()):
        token = match.group(0)
        if is_letter_token(token):
            tokens.append(token)
    return tokens
