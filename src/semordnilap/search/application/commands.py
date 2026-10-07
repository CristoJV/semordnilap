"""Application commands for semordnilap search."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from semordnilap.search.domain import SearchPolicy


@dataclass(frozen=True)
class FindSemordnilapsCommand:
    db_path: Path
    output_path: Path | None
    policy: SearchPolicy
    dry_run: bool = False
    progress_every: int = 10_000

    def __post_init__(self) -> None:
        if not self.dry_run and self.output_path is None:
            raise ValueError("output_path is required unless dry_run is enabled")
        if self.progress_every < 0:
            raise ValueError("progress_every cannot be negative")
