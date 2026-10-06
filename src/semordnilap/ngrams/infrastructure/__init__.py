"""N-gram extraction infrastructure layer."""

from semordnilap.ngrams.infrastructure.corpus_adapters import (
    SOURCE_ADAPTERS,
    ResolvedCorpusInput,
    resolve_corpus_input,
)
from semordnilap.ngrams.infrastructure.factory import build_repository
from semordnilap.ngrams.infrastructure.repositories import (
    DuckDbNgramCountRepository,
)

__all__ = [
    "DuckDbNgramCountRepository",
    "ResolvedCorpusInput",
    "SOURCE_ADAPTERS",
    "build_repository",
    "resolve_corpus_input",
]
