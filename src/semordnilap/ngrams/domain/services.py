"""Domain services for corpus n-gram extraction."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator

from semordnilap.ngrams.domain.model import (
    ExtractedNgram,
    NgramCount,
    NgramExtractionPolicy,
    NgramKey,
)
from semordnilap.ngrams.domain.filters import is_valid_ngram
from semordnilap.ngrams.domain.normalize import (
    has_punctuation,
    normalize_ngram,
)
from semordnilap.ngrams.domain.tokenize import (
    iter_sentence_chunks,
    iter_text_windows,
    tokenize_sentence,
)
from semordnilap.utils.iterables import sliding_windows


def extract_counts_from_text(
    text: str, policy: NgramExtractionPolicy
) -> Counter[NgramKey]:
    counts: Counter[NgramKey] = Counter()
    windows: Iterator[tuple[tuple[str, ...], tuple[str, ...] | str]]

    if policy.omit_punctuation:
        windows = (
            (window, window)
            for sentence in iter_sentence_chunks(text)
            for window in sliding_windows(
                tokenize_sentence(sentence), policy.max_n
            )
        )
    else:
        windows = iter_text_windows(text, policy.max_n)

    for lexical_tokens, surface in windows:
        if is_valid_ngram(
            lexical_tokens,
            lang=policy.lang,
            min_token_len=policy.min_token_len,
            max_token_len=policy.max_token_len,
            min_norm_len=policy.min_norm_len,
            include_all_stopword_ngrams=(
                policy.include_all_stopword_ngrams
            ),
            fold_nasal_letters=policy.fold_nasal_letters,
        ):
            key: NgramKey
            if isinstance(surface, str):
                key = ExtractedNgram(tokens=lexical_tokens, text=surface)
            else:
                key = surface
            counts[key] += 1

    return counts


def build_ngram_count(
    tokens: NgramKey,
    *,
    count: int,
    lang: str,
    corpus: str,
    fold_nasal_letters: bool,
) -> NgramCount:
    if isinstance(tokens, ExtractedNgram):
        lexical_tokens = tokens.tokens
        text = tokens.text
    else:
        lexical_tokens = tokens
        text = " ".join(tokens)
    return NgramCount(
        lang=lang,
        corpus=corpus,
        text=text,
        n=len(lexical_tokens),
        count=count,
        norm_key=normalize_ngram(
            text, fold_nasal_letters=fold_nasal_letters
        ),
        has_punctuation=has_punctuation(text),
    )
