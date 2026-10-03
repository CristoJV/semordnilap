"""Scoring formulas shared by search and phrase generation."""

from __future__ import annotations

import math
from collections.abc import Iterable


def score_semordnilap_pair(source_count: int, target_count: int) -> float:
    """Score one bilingual reversible pair from corpus frequencies."""
    score = math.log(source_count + 1) + math.log(target_count + 1)
    return round(score, 6)


def score_semordnilap_sequence(pair_scores: Iterable[float]) -> float:
    """Score a sequence of reversible pieces using their shared pair scores."""
    scores = list(pair_scores)
    if not scores:
        return 0.0
    return (sum(scores) / len(scores)) + (0.25 * min(scores))
