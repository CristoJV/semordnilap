"""Domain model for phrase generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PhrasePiece:
    id: int
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

    @property
    def formal_ok(self) -> bool:
        return self.source_norm_key == self.target_norm_key[::-1]

    @property
    def label(self) -> str:
        return f"{self.source_text} / {self.target_text}"


@dataclass(frozen=True)
class PhraseCandidate:
    pieces: tuple[PhrasePiece, ...]
    score: float
    source_plausibility: float = 0.0
    target_plausibility: float = 0.0

    @property
    def source_phrase(self) -> str:
        return " ".join(piece.source_text for piece in self.pieces)

    @property
    def target_phrase(self) -> str:
        return " ".join(piece.target_text for piece in reversed(self.pieces))

    @property
    def source_norm_key(self) -> str:
        return "".join(piece.source_norm_key for piece in self.pieces)

    @property
    def target_norm_key(self) -> str:
        return "".join(
            piece.target_norm_key for piece in reversed(self.pieces)
        )

    @property
    def formal_ok(self) -> bool:
        return self.source_norm_key == self.target_norm_key[::-1]

    @property
    def piece_count(self) -> int:
        return len(self.pieces)

    @property
    def pair_score_sum(self) -> float:
        return round(sum(piece.pair_score for piece in self.pieces), 6)

    @property
    def source_count_sum(self) -> int:
        return sum(piece.source_count for piece in self.pieces)

    @property
    def target_count_sum(self) -> int:
        return sum(piece.target_count for piece in self.pieces)

    @property
    def min_source_count(self) -> int:
        return min(piece.source_count for piece in self.pieces)

    @property
    def min_target_count(self) -> int:
        return min(piece.target_count for piece in self.pieces)


@dataclass(frozen=True)
class GeneratePhrasePolicy:
    min_source_count: int = 100
    min_target_count: int = 100
    min_pair_score: float = 0.0
    max_source_n: int = 3
    max_target_n: int = 3
    piece_limit: int = 1000
    min_pieces: int = 2
    max_pieces: int = 2
    beam_size: int = 500
    max_results: int = 500
    allow_repeated_pieces: bool = False
    collapse_permutations: bool = True
    reciprocal_penalty: float = 12.0
    edge_penalty: float = 3.0
    fragment_penalty: float = 6.0
    wordfreq_weight: float = 0.35
    plausibility_weight: float = 0.0


class PhrasePlausibilityScorer(Protocol):
    def score(self, text: str, lang: str) -> float:
        raise NotImplementedError
