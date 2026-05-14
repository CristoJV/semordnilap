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
    compact_only: bool
    compact_n: int
    compact_after_count: bool
    policy: NgramExtractionPolicy
