"""Domain services for corpus n-gram extraction."""

from __future__ import annotations

from collections import Counter

from semordnilap.ngrams.domain.model import NgramCount, NgramExtractionPolicy
from semordnilap.ngrams.domain.filters import is_valid_ngram
from semordnilap.ngrams.domain.normalize import normalize_ngram
from semordnilap.ngrams.domain.tokenize import (
    iter_sentence_chunks,
    tokenize_sentence,
)
from semordnilap.utils.iterables import sliding_windows


def extract_counts_from_text(
    text: str, policy: NgramExtractionPolicy
) -> Counter[tuple[str, ...]]:
    counts: Counter[tuple[str, ...]] = Counter()

    for sentence in iter_sentence_chunks(text):
        tokens = tokenize_sentence(sentence)
        for window in sliding_windows(tokens, policy.max_n):
            if is_valid_ngram(
                window,
                lang=policy.lang,
                min_token_len=policy.min_token_len,
                max_token_len=policy.max_token_len,
                min_norm_len=policy.min_norm_len,
                include_all_stopword_ngrams=(
                    policy.include_all_stopword_ngrams
                ),
                fold_nasal_letters=policy.fold_nasal_letters,
            ):
                counts[window] += 1

    return counts


def build_ngram_count(
    tokens: tuple[str, ...],
    *,
    count: int,
    lang: str,
    corpus: str,
    fold_nasal_letters: bool,
) -> NgramCount:
    text = " ".join(tokens)
    return NgramCount(
        lang=lang,
        corpus=corpus,
        text=text,
        n=len(tokens),
        count=count,
        norm_key=normalize_ngram(
            text, fold_nasal_letters=fold_nasal_letters
        ),
    )
