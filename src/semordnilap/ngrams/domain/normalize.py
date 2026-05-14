"""Normalization helpers for semordnilap n-gram matching."""

from __future__ import annotations

from semordnilap.utils.text import normalize_compact_text


def normalize_ngram(text: str, *, fold_nasal_letters: bool = False) -> str:
    """Build the compact comparison key used by semordnilap lookup."""
    return normalize_compact_text(
        text, fold_nasal_letters=fold_nasal_letters
    )

