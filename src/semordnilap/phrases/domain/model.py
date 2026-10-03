"""Domain model for phrase generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
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
class TokenSyntax:
    text: str
    lemma: str
    pos: str
    dep: str = ""
    morph: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class TextSyntax:
    tokens: tuple[TokenSyntax, ...]

    @property
    def pos_sequence(self) -> tuple[str, ...]:
        return tuple(token.pos for token in self.tokens)


@dataclass(frozen=True)
class PieceSyntax:
    piece_id: int
    source: TextSyntax
    target: TextSyntax

    @property
    def annotated(self) -> bool:
        return bool(self.source.tokens or self.target.tokens)


@dataclass(frozen=True)
class PhraseCandidate:
    pieces: tuple[PhrasePiece, ...]
    score: float
    growth_score: float = 0.0
    growth_mode: str = "right"
    source_plausibility: float = 0.0
    target_plausibility: float = 0.0
    transition_score: float = 0.0
    syntax_score: float = 0.0
    last_expansion_side: str = ""
    source_partial_viability: float = 0.0
    target_partial_viability: float = 0.0
    bilingual_partial_viability: float = 0.0
    source_completion_score: float = 0.0
    target_completion_score: float = 0.0
    bilingual_completion_score: float = 0.0
    source_boundary_score: float = 0.0
    target_boundary_score: float = 0.0
    source_dead_end_score: float = 0.0
    target_dead_end_score: float = 0.0
    bilingual_dead_end_score: float = 0.0
    source_need_label: str = "unknown"
    source_need_confidence: float = 0.0
    target_need_label: str = "unknown"
    target_need_confidence: float = 0.0
    edge_compatibility_score: float = 0.0
    source_edge_compatibility: float = 0.0
    target_edge_compatibility: float = 0.0
    left_piece_ids: tuple[int, ...] = ()
    center_piece_ids: tuple[int, ...] = ()
    right_piece_ids: tuple[int, ...] = ()
    diagnostic_flags: dict[str, float] = field(default_factory=dict)

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
    max_pieces: int = 4
    beam_size: int = 1000
    candidate_pool_size: int | None = None
    max_results: int = 500
    allow_repeated_pieces: bool = False
    collapse_permutations: bool = True
    pair_weight: float = 1.0
    fluency_weight: float = 1.0
    syntax_weight: float = 1.0
    morphology_weight: float = 0.0
    repeat_penalty: float = 8.0
    complete_bonus: float = 2.0
    morphology_agreement_features: tuple[str, ...] = ("Gender", "Number")
    expand_sides: str = "right"
    partial_viability_weight: float = 1.0
    completion_weight: float = 1.0
    dead_end_weight: float = 1.0
    boundary_weight: float = 1.0
    edge_compatibility_weight: float = 1.0
    min_completion_score: float = 0.0
    min_partial_viability: float = float("-inf")
    forbid_low_completion_final: bool = True
    center_seed_limit: int = 500
    source_boundary_model: Path | None = None
    target_boundary_model: Path | None = None
    source_transition_model: Path | None = None
    target_transition_model: Path | None = None


class PhrasePlausibilityScorer(Protocol):
    def score(self, text: str, lang: str) -> float:
        raise NotImplementedError


class PhraseSyntaxAnnotator(Protocol):
    def annotate(self, pieces: list[PhrasePiece]) -> dict[int, PieceSyntax]:
        raise NotImplementedError
