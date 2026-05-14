"""Transparent first-pass scoring for extracted corpus n-grams."""

from __future__ import annotations

import math

from semordnilap.ngrams.domain.filters import is_all_stopwords
from semordnilap.ngrams.domain.normalize import normalize_ngram


def score_ngram(
    tokens: tuple[str, ...],
    *,
    count: int,
    lang: str,
    fold_nasal_letters: bool,
) -> float:
    score = math.log(count + 1)

    one_letter_count = sum(1 for token in tokens if len(token) == 1)
    score -= 0.5 * one_letter_count

    if len(tokens) == 3:
        score -= 0.25

    if is_all_stopwords(tokens, lang):
        score -= 0.75

    norm_len = len(
        normalize_ngram(
            " ".join(tokens), fold_nasal_letters=fold_nasal_letters
        )
    )
    if 4 <= norm_len <= 12:
        score += 0.2

    return round(score, 6)

