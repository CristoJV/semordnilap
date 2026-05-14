"""N-gram extraction infrastructure layer."""

from semordnilap.ngrams.infrastructure.factory import build_repository
from semordnilap.ngrams.infrastructure.repositories import DuckDbNgramCountRepository

__all__ = [
    "DuckDbNgramCountRepository",
    "build_repository",
]
