"""TSV-backed review repository."""

from __future__ import annotations

import csv
from pathlib import Path

from semordnilap.review.domain import ReviewRow


def parse_int(value: str | None, default: int = 0) -> int:
    if value is None or value == "":
        return default
    return int(float(value))


def parse_float(value: str | None, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    return float(value)


class TsvReviewRepository:
    def load(self, path: Path) -> list[ReviewRow]:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            return [self._row_from_record(record) for record in reader]

    def _row_from_record(self, record: dict[str, str]) -> ReviewRow:
        return ReviewRow(
            source_text=record.get("source_text", ""),
            target_text=record.get("target_text", ""),
            pair_score=parse_float(record.get("pair_score")),
            source_count=parse_int(record.get("source_count")),
            target_count=parse_int(record.get("target_count")),
            source_n=parse_int(record.get("source_n")),
            target_n=parse_int(record.get("target_n")),
            source_norm_key=record.get("source_norm_key", ""),
            target_norm_key=record.get("target_norm_key", ""),
            source_lang=record.get("source_lang", ""),
            target_lang=record.get("target_lang", ""),
            source_corpus=record.get("source_corpus", ""),
            target_corpus=record.get("target_corpus", ""),
        )

