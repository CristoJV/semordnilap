"""Domain services for corpus n-gram extraction."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Iterator

from semordnilap.ngrams.domain.model import (
    ExtractedNgram,
    NgramCount,
    NgramExtractionPolicy,
    NgramKey,
    TaggedNgramKey,
)
from semordnilap.ngrams.domain.filters import is_valid_ngram
from semordnilap.ngrams.domain.normalize import (
    has_punctuation,
    normalize_ngram,
)
from semordnilap.ngrams.domain.tokenize import (
    is_letter_token,
    iter_sentence_chunks,
    iter_text_windows,
    tokenize_sentence,
)
from semordnilap.utils.iterables import sliding_windows
from semordnilap.utils.text import canonical_surface, normalize_spacing
from semordnilap.tagging.domain import AnnotatedDocument


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

    if policy.omit_punctuation:
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
            min_token_len=policy.min_token_len,
            max_token_len=policy.max_token_len,
            min_norm_len=policy.min_norm_len,
            include_all_stopword_ngrams=(policy.include_all_stopword_ngrams),
            fold_nasal_letters=policy.fold_nasal_letters,
        ):
            key: NgramKey
            surface_key, surface_display = surface
            key = ExtractedNgram(
                tokens=lexical_tokens,
                surface_key=canonical_surface(surface_key),
                surface_display=normalize_spacing(surface_display),
            )
            yield key


def extract_counts_from_annotated_document(
    document: AnnotatedDocument,
    policy: NgramExtractionPolicy,
) -> Counter[TaggedNgramKey]:
    """Extract tagged n-grams without changing the annotated tokenization."""
    return Counter(iter_ngrams_from_annotated_document(document, policy))


def iter_ngrams_from_annotated_document(
    document: AnnotatedDocument,
    policy: NgramExtractionPolicy,
) -> Iterator[TaggedNgramKey]:
    if document.lang != policy.lang:
        raise ValueError(
            f"Annotated document language {document.lang!r} does not match "
            f"extraction language {policy.lang!r}"
        )

    lexical = deque(maxlen=policy.max_n)
    for sentence in document.sentences:
        for token in sentence.tokens:
            if token.is_punctuation or not is_letter_token(token.text):
                continue
            lexical.append((token, sentence.index))
            available = tuple(lexical)
            for size in range(1, len(available) + 1):
                window = available[-size:]
                first_token = window[0][0]
                last_token = window[-1][0]
                exact_surface = document.text[
                    first_token.start_char : last_token.end_char
                ]
                if policy.omit_punctuation and has_punctuation(exact_surface):
                    continue

                lexical_tokens = tuple(
                    item.text.casefold() for item, _sentence_index in window
                )
                if not is_valid_ngram(
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
                    continue

                display = (
                    " ".join(lexical_tokens)
                    if policy.omit_punctuation
                    else normalize_spacing(exact_surface)
                )
                ngram = ExtractedNgram(
                    tokens=lexical_tokens,
                    surface_key=canonical_surface(display),
                    surface_display=display,
                )
                yield TaggedNgramKey(
                    ngram=ngram,
                    upos_pattern=" ".join(
                        item.upos_slot for item, _sentence_index in window
                    ),
                    crosses_sentence=(window[0][1] != window[-1][1]),
                )


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
        norm_key=normalize_ngram(text, fold_nasal_letters=fold_nasal_letters),
        has_punctuation=has_punctuation(text),
    )
