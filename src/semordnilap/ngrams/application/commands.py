"""Application commands for n-gram extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from semordnilap.ngrams.domain import NgramExtractionPolicy


@dataclass(frozen=True)
class ExtractNgramsCommand:
    input_path: Path | None
    output_path: Path
    corpus: str
    input_format: str
    text_field: str
    min_count: int
    max_results: int
    export_n: int
    min_export_norm_len: int
    max_export_norm_len: int
    export_source: str
    export_log_every: int
    limit_docs: int
    chunk_docs: int
    flush_unique_ngrams: int
    reset: bool
    export_only: bool
    export_after_count: bool
    delete_only: bool
    compact_only: bool
    compact_n: int
    compact_after_count: bool
    policy: NgramExtractionPolicy
    dataset_id: str | None = None
    source_adapter: str = "raw"
    input_files: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        if not self.corpus.strip():
            raise ValueError("corpus cannot be empty")
        if self.limit_docs < 0:
            raise ValueError("limit_docs cannot be negative")
        if self.chunk_docs < 1:
            raise ValueError("chunk_docs must be at least 1")
        if self.flush_unique_ngrams < 1:
            raise ValueError("flush_unique_ngrams must be at least 1")
