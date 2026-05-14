"""Domain model for reviewing semordnilap search results."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewRow:
    source_text: str
    target_text: str
    pair_score: float
    source_count: int
    target_count: int
    source_n: int
    target_n: int
    source_norm_key: str
    target_norm_key: str
    source_lang: str = ""
    target_lang: str = ""
    source_corpus: str = ""
    target_corpus: str = ""

    @property
    def reversed_source_key(self) -> str:
        return self.source_norm_key[::-1]

    @property
    def key_matches(self) -> bool:
        return self.reversed_source_key == self.target_norm_key


@dataclass(frozen=True)
class ReviewFilters:
    source_contains: str = ""
    target_contains: str = ""
    min_pair_score: float = 0.0
    min_source_count: int = 0
    min_target_count: int = 0
    source_n: int | None = None
    target_n: int | None = None
    limit: int = 500

    def matches(self, row: ReviewRow) -> bool:
        source_query = self.source_contains.strip().casefold()
        target_query = self.target_contains.strip().casefold()

        if source_query and source_query not in row.source_text.casefold():
            return False
        if target_query and target_query not in row.target_text.casefold():
            return False
        if row.pair_score < self.min_pair_score:
            return False
        if row.source_count < self.min_source_count:
            return False
        if row.target_count < self.min_target_count:
            return False
        if self.source_n is not None and row.source_n != self.source_n:
            return False
        if self.target_n is not None and row.target_n != self.target_n:
            return False
        return True

