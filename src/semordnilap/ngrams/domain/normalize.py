"""Normalization helpers for semordnilap n-gram matching."""

from __future__ import annotations

import unicodedata

from semordnilap.utils.text import normalize_compact_text

NORMALIZATION_VERSION = "unicode-nfc-casefold-v2"


def normalize_ngram(text: str, *, preserve_nasal_letters: bool = False) -> str:
    """Build the letters-only compact semordnilap comparison key."""
    normalized = normalize_compact_text(
        text, preserve_nasal_letters=preserve_nasal_letters
    )
    return "".join(
        char
        for char in normalized
        if unicodedata.category(char).startswith("L")
    )


def has_punctuation(text: str) -> bool:
    """Return whether text contains any Unicode punctuation character."""
    return any(unicodedata.category(char).startswith("P") for char in text)
