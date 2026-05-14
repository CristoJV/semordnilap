"""Application commands for semordnilap search."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from semordnilap.search.domain import SearchPolicy


@dataclass(frozen=True)
class FindSemordnilapsCommand:
    db_path: Path
    output_path: Path
    policy: SearchPolicy

