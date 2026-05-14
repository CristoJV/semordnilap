"""Domain model for corpus n-gram extraction."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from semordnilap.ngrams.domain.scoring import score_ngram


@dataclass(frozen=True)
class NgramExtractionPolicy:
    lang: str
    max_n: int = 3
    min_token_len: int = 2
    max_token_len: int = 30
    min_norm_len: int = 3
    include_all_stopword_ngrams: bool = False
    fold_nasal_letters: bool = False


@dataclass(frozen=True)
class NgramCount:
    lang: str
    corpus: str
    text: str
    n: int
    count: int
    norm_key: str

    @property
    def tokens(self) -> tuple[str, ...]:
        return tuple(self.text.split())

    def score(self, policy: NgramExtractionPolicy) -> float:
        return score_ngram(
            self.tokens,
            count=self.count,
            lang=policy.lang,
            fold_nasal_letters=policy.fold_nasal_letters,
        )


class NgramCountRepository(Protocol):
    def add_counts(
        self,
        counts: Counter[tuple[str, ...]],
        *,
        lang: str,
        corpus: str,
        fold_nasal_letters: bool,
    ) -> None:
        raise NotImplementedError

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
        source: str = "auto",
    ) -> Iterable[NgramCount]:
        raise NotImplementedError

    def count_entries(self, *, lang: str, corpus: str) -> int:
        raise NotImplementedError

    def compact_counts(self, *, lang: str, corpus: str, n: int) -> int:
        raise NotImplementedError

    def reset_counts(self, *, lang: str, corpus: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError
