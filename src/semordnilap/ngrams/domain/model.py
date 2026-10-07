"""Domain model for corpus n-gram extraction."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from semordnilap.ngrams.domain.scoring import score_ngram


@dataclass(frozen=True)
class ExtractedNgram:
    """Lexical tokens together with their punctuation-preserving surface."""

    tokens: tuple[str, ...]
    surface_key: str
    surface_display: str = field(default="", compare=False, hash=False)

    @property
    def text(self) -> str:
        return self.surface_key


NgramKey = tuple[str, ...] | ExtractedNgram


@dataclass(frozen=True)
class NgramExtractionPolicy:
    lang: str
    max_n: int = 3
    filter_min_token_len: int = 2
    filter_max_token_len: int = 30
    filter_min_norm_len: int = 2
    filter_all_stopword_ngrams: bool = False
    preserve_nasal_letters: bool = False
    filter_punctuation_boundaries: bool = False

    def __post_init__(self) -> None:
        if not self.lang.strip():
            raise ValueError("lang cannot be empty")
        if not 1 <= self.max_n <= 3:
            raise ValueError("max_n must be between 1 and 3")
        if self.filter_min_token_len < 1:
            raise ValueError("filter_min_token_len must be at least 1")
        if self.filter_max_token_len < self.filter_min_token_len:
            raise ValueError(
                "filter_max_token_len cannot be less than "
                "filter_min_token_len"
            )
        if self.filter_min_norm_len < 1:
            raise ValueError("filter_min_norm_len must be at least 1")


@dataclass(frozen=True)
class NgramCount:
    lang: str
    corpus: str
    text: str
    n: int
    count: int
    norm_key: str
    has_punctuation: bool = False

    @property
    def tokens(self) -> tuple[str, ...]:
        # Stored text may retain punctuation, while tokens are always lexical.
        from semordnilap.ngrams.domain.tokenize import tokenize_sentence

        return tuple(tokenize_sentence(self.text))

    def score(self, policy: NgramExtractionPolicy) -> float:
        return score_ngram(
            self.tokens,
            count=self.count,
            lang=policy.lang,
            preserve_nasal_letters=policy.preserve_nasal_letters,
        )


class NgramCountRepository(Protocol):
    def iter_counts(
        self,
        *,
        lang: str,
        corpus: str,
        min_count: int,
        max_results: int = 0,
        export_n: int = 0,
        min_norm_len: int = 0,
        max_norm_len: int = 0,
        dataset_id: str | None = None,
    ) -> Iterable[NgramCount]:
        raise NotImplementedError

    def delete_counts(self, *, lang: str, corpus: str) -> dict[str, int]:
        raise NotImplementedError

    def reset_counts(self, *, lang: str, corpus: str) -> dict[str, int]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError
