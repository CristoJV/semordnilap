"""TSV-backed phrase repository."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from semordnilap.phrases.domain import PhraseCandidate, PhrasePiece


def parse_int(value: str | None, default: int = 0) -> int:
    if value is None or value == "":
        return default
    return int(float(value))


def parse_float(value: str | None, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    return float(value)


class TsvPhraseRepository:
    def load_pieces(self, path: Path) -> list[PhrasePiece]:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            return [
                self._piece_from_record(index, record)
                for index, record in enumerate(reader)
            ]

    def save_candidates(
        self, path: Path, candidates: list[PhraseCandidate]
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "source_phrase",
                    "target_phrase",
                    "phrase_score",
                    "source_plausibility",
                    "target_plausibility",
                    "piece_count",
                    "formal_ok",
                    "source_norm_key",
                    "target_norm_key",
                    "pair_score_sum",
                    "source_count_sum",
                    "target_count_sum",
                    "min_source_count",
                    "min_target_count",
                    "pieces",
                    "piece_ids",
                    "source_counts",
                    "target_counts",
                ],
                delimiter="\t",
            )
            writer.writeheader()
            for candidate in candidates:
                writer.writerow(self._candidate_record(candidate))

    def _piece_from_record(
        self, index: int, record: dict[str, str]
    ) -> PhrasePiece:
        return PhrasePiece(
            id=index,
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
        )

    def _candidate_record(self, candidate: PhraseCandidate) -> dict:
        return {
            "source_phrase": candidate.source_phrase,
            "target_phrase": candidate.target_phrase,
            "phrase_score": candidate.score,
            "source_plausibility": candidate.source_plausibility,
            "target_plausibility": candidate.target_plausibility,
            "piece_count": candidate.piece_count,
            "formal_ok": candidate.formal_ok,
            "source_norm_key": candidate.source_norm_key,
            "target_norm_key": candidate.target_norm_key,
            "pair_score_sum": candidate.pair_score_sum,
            "source_count_sum": candidate.source_count_sum,
            "target_count_sum": candidate.target_count_sum,
            "min_source_count": candidate.min_source_count,
            "min_target_count": candidate.min_target_count,
            "pieces": json.dumps(
                [piece.label for piece in candidate.pieces],
                ensure_ascii=False,
            ),
            "piece_ids": json.dumps(
                [piece.id for piece in candidate.pieces],
                ensure_ascii=False,
            ),
            "source_counts": json.dumps(
                [piece.source_count for piece in candidate.pieces],
                ensure_ascii=False,
            ),
            "target_counts": json.dumps(
                [piece.target_count for piece in candidate.pieces],
                ensure_ascii=False,
            ),
        }
