"""N-gram extraction domain layer."""

from semordnilap.ngrams.domain.model import (
    ExtractedNgram,
    NgramCount,
    NgramCountRepository,
    NgramExtractionPolicy,
    NgramKey,
    TaggedNgramKey,
)
from semordnilap.ngrams.domain.services import (
    build_ngram_count,
    extract_counts_from_annotated_document,
    extract_counts_from_text,
    iter_ngrams_from_annotated_document,
    iter_ngrams_from_text,
)

__all__ = [
    "NgramCount",
    "NgramCountRepository",
    "NgramExtractionPolicy",
    "NgramKey",
    "TaggedNgramKey",
    "ExtractedNgram",
    "build_ngram_count",
    "extract_counts_from_annotated_document",
    "extract_counts_from_text",
    "iter_ngrams_from_annotated_document",
    "iter_ngrams_from_text",
]
