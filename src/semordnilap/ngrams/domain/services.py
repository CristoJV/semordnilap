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
from semordnilap.utils.text import canonical_surface, normalize_spacing


def extract_counts_from_text(
    text: str, policy: NgramExtractionPolicy
) -> Counter[NgramKey]:
    return Counter(iter_ngrams_from_text(text, policy))


def iter_ngrams_from_text(
    text: str, policy: NgramExtractionPolicy
) -> Iterator[ExtractedNgram]:
    windows: Iterator[
        tuple[tuple[str, ...], tuple[str, ...] | tuple[str, str]]
    ]

    if policy.filter_punctuation_boundaries:
        windows = (
            (window, (" ".join(window), " ".join(window)))
            for sentence in iter_sentence_chunks(text)
            for window in sliding_windows(
                tokenize_sentence(sentence), policy.max_n
            )
        )
    else:
        windows = (
            (tokens, (surface_key, surface_display))
            for tokens, surface_key, surface_display in iter_text_windows(
                text, policy.max_n
            )
        )

    for lexical_tokens, surface in windows:
        if is_valid_ngram(
            lexical_tokens,
            lang=policy.lang,
            min_token_len=policy.filter_min_token_len,
            max_token_len=policy.filter_max_token_len,
            min_norm_len=policy.filter_min_norm_len,
            filter_all_stopword_ngrams=policy.filter_all_stopword_ngrams,
            preserve_nasal_letters=policy.preserve_nasal_letters,
        ):
            key: NgramKey
            surface_key, surface_display = surface
            key = ExtractedNgram(
                tokens=lexical_tokens,
                surface_key=canonical_surface(surface_key),
                surface_display=normalize_spacing(surface_display),
            )
            yield key


def build_ngram_count(
    tokens: NgramKey,
    *,
    count: int,
    lang: str,
    corpus: str,
    preserve_nasal_letters: bool = False,
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
            text, preserve_nasal_letters=preserve_nasal_letters
        ),
        has_punctuation=has_punctuation(text),
    )
