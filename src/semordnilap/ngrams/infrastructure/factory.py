"""Repository factory for n-gram infrastructure adapters."""

from __future__ import annotations

from pathlib import Path

from semordnilap.ngrams.infrastructure.repositories import DuckDbNgramCountRepository


def build_repository(db_path: Path):
    return DuckDbNgramCountRepository(db_path)
