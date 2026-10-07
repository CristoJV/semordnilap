"""Domain model for semordnilap search over corpus n-grams."""

from __future__ import annotations

from dataclasses import dataclass

from semordnilap.scoring import score_semordnilap_pair
from semordnilap.utils.artifacts import stable_id
from semordnilap.utils.text import canonical_surface


@dataclass(frozen=True)
class SearchPolicy:
    source_lang: str
    target_lang: str
    source_corpus: str
    target_corpus: str
    filter_min_source_count: int = 1
    filter_min_target_count: int = 1
    filter_max_results: int | None = None
    filter_source_n: int | None = None
    filter_target_n: int | None = None
    filter_min_norm_len: int | None = None
    filter_max_norm_len: int | None = None
    filter_exclude_palindromes: bool = False
    filter_exclude_identical_text: bool = False
    filter_exclude_punctuation: bool = False
    filter_exclude_all_stopword_ngrams: bool = False
    source_dataset_id: str | None = None
    target_dataset_id: str | None = None

    def __post_init__(self) -> None:
        if self.filter_min_source_count < 1:
            raise ValueError("filter_min_source_count must be at least 1")
        if self.filter_min_target_count < 1:
            raise ValueError("filter_min_target_count must be at least 1")
        if self.filter_max_results is not None and self.filter_max_results < 1:
            raise ValueError("filter_max_results must be at least 1")
        for name, value in (
            ("filter_source_n", self.filter_source_n),
            ("filter_target_n", self.filter_target_n),
        ):
            if value is not None and value not in {1, 2, 3}:
                raise ValueError(f"{name} must be one of: 1, 2, 3")
        for name, value in (
            ("filter_min_norm_len", self.filter_min_norm_len),
            ("filter_max_norm_len", self.filter_max_norm_len),
        ):
            if value is not None and value < 1:
                raise ValueError(f"{name} must be at least 1")
        if (
            self.filter_min_norm_len is not None
            and self.filter_max_norm_len is not None
            and self.filter_min_norm_len > self.filter_max_norm_len
        ):
            raise ValueError(
                "filter_min_norm_len cannot be greater than "
                "filter_max_norm_len"
            )


@dataclass(frozen=True)
class SemordnilapPair:
    source_lang: str
    source_corpus: str
    source_text: str
    source_n: int
    source_count: int
    source_norm_key: str
    source_has_punctuation: bool
    target_lang: str
    target_corpus: str
    target_text: str
    target_n: int
    target_count: int
    target_norm_key: str
    target_has_punctuation: bool
    source_dataset_id: str | None = None
    target_dataset_id: str | None = None

    def _identity(self, *, include_corpus: bool) -> dict:
        """Return the versioned, count-independent identity payload."""

        source = {
            "lang": self.source_lang.casefold(),
            "text": canonical_surface(self.source_text),
            "n": self.source_n,
        }
        target = {
            "lang": self.target_lang.casefold(),
            "text": canonical_surface(self.target_text),
            "n": self.target_n,
        }
        if include_corpus:
            source["corpus"] = self.source_corpus
            target["corpus"] = self.target_corpus
        return {"source": source, "target": target}

    @property
    def pair_id(self) -> str:
        """Identify this directed pair in its source and target corpora."""

        return stable_id(
            "semordnilap-pair-v1",
            self._identity(include_corpus=True),
        )

    @property
    def lexical_pair_id(self) -> str:
        """Identify this directed lexical pair independently of corpora."""

        return stable_id(
            "semordnilap-lexical-pair-v1",
            self._identity(include_corpus=False),
        )

    @property
    def pair_score(self) -> float:
        return score_semordnilap_pair(
            self.source_count,
            self.target_count,
        )
