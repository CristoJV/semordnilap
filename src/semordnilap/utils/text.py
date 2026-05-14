"""Text normalization helpers shared across the project."""

from __future__ import annotations

import re
import unicodedata


ACCENT_MARKS = {
    "\u0301",  # acute
    "\u0300",  # grave
    "\u0302",  # circumflex
    "\u0303",  # tilde
    "\u0308",  # diaeresis
}
URL_RE = re.compile(r"https?://\S+|www\.\S+")
MARKER_RE = re.compile(r"\[\[?[^\]\n]+\]?\]|\{\{[^}\n]+\}\}")
WHITESPACE_RE = re.compile(r"\s+")
TRAILING_SENTENCE_PUNCTUATION = ".!?;:…"


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if c not in ACCENT_MARKS)
    return unicodedata.normalize("NFC", stripped)


def remove_urls(text: str) -> str:
    def replace(match: re.Match) -> str:
        url = match.group(0)
        trailing = ""
        while url and url[-1] in TRAILING_SENTENCE_PUNCTUATION:
            trailing = url[-1] + trailing
            url = url[:-1]
        return f" {trailing} "

    return URL_RE.sub(replace, text)


def remove_markers(text: str) -> str:
    """Remove common wiki/dataset markers that should not create tokens."""
    return MARKER_RE.sub(" ", text)


def normalize_spacing(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def clean_corpus_text(text: str) -> str:
    text = remove_urls(text)
    text = remove_markers(text)
    return normalize_spacing(text)


def normalize_compact_text(
    text: str, *, fold_nasal_letters: bool = False
) -> str:
    """Build a compact key: lowercase, de-accented, no whitespace."""
    normalized = strip_accents(text.lower())
    normalized = normalized.replace("ç", "c")
    if fold_nasal_letters:
        normalized = normalized.replace("ñ", "n")
    return "".join(c for c in normalized if not c.isspace())
