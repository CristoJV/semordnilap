"""Domain model for semordnilap search over corpus n-grams."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SearchPolicy:
    source_lang: str
    target_lang: str
    source_corpus: str
    target_corpus: str
    min_source_count: int = 3
    min_target_count: int = 3
    max_results: int = 0
    source_n: int = 0
    target_n: int = 0
    min_norm_len: int = 0
    max_norm_len: int = 0
    counts_source: str = "auto"
    include_palindromes: bool = False
    include_identical_text: bool = False


@dataclass(frozen=True)
class SemordnilapPair:
    source_lang: str
    source_corpus: str
    source_text: str
    source_n: int
    source_count: int
    source_norm_key: str
    target_lang: str
    target_corpus: str
    target_text: str
    target_n: int
    target_count: int
    target_norm_key: str

    @property
    def pair_score(self) -> float:
        score = math.log(self.source_count + 1) + math.log(
            self.target_count + 1
        )
        return round(score, 6)
