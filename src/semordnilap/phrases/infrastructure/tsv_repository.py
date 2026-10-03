"""TSV-backed phrase repository."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from semordnilap.phrases.domain import PhraseCandidate, PhrasePiece
from semordnilap.scoring import score_semordnilap_pair


def parse_int(value: str | None, default: int = 0) -> int:
    if value is None or value == "":
        return default
    return int(float(value))


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
                    "growth_score",
                    "growth_mode",
                    "source_plausibility",
                    "target_plausibility",
                    "transition_score",
                    "syntax_score",
                    "source_partial_viability",
                    "target_partial_viability",
                    "bilingual_partial_viability",
                    "source_completion_score",
                    "target_completion_score",
                    "bilingual_completion_score",
                    "source_boundary_score",
                    "target_boundary_score",
                    "source_dead_end_score",
                    "target_dead_end_score",
                    "bilingual_dead_end_score",
                    "source_need_label",
                    "source_need_confidence",
                    "target_need_label",
                    "target_need_confidence",
                    "edge_compatibility_score",
                    "source_edge_compatibility",
                    "target_edge_compatibility",
                    "last_expansion_side",
                    "left_piece_ids",
                    "center_piece_ids",
                    "right_piece_ids",
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
        source_count = parse_int(record.get("source_count"))
        target_count = parse_int(record.get("target_count"))
        return PhrasePiece(
            id=index,
            source_text=record.get("source_text", ""),
            target_text=record.get("target_text", ""),
            pair_score=score_semordnilap_pair(source_count, target_count),
            source_count=source_count,
            target_count=target_count,
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
            "growth_score": candidate.growth_score,
            "growth_mode": candidate.growth_mode,
            "source_plausibility": candidate.source_plausibility,
            "target_plausibility": candidate.target_plausibility,
            "transition_score": candidate.transition_score,
            "syntax_score": candidate.syntax_score,
            "source_partial_viability": candidate.source_partial_viability,
            "target_partial_viability": candidate.target_partial_viability,
            "bilingual_partial_viability": candidate.bilingual_partial_viability,
            "source_completion_score": candidate.source_completion_score,
            "target_completion_score": candidate.target_completion_score,
            "bilingual_completion_score": candidate.bilingual_completion_score,
            "source_boundary_score": candidate.source_boundary_score,
            "target_boundary_score": candidate.target_boundary_score,
            "source_dead_end_score": candidate.source_dead_end_score,
            "target_dead_end_score": candidate.target_dead_end_score,
            "bilingual_dead_end_score": candidate.bilingual_dead_end_score,
            "source_need_label": candidate.source_need_label,
            "source_need_confidence": candidate.source_need_confidence,
            "target_need_label": candidate.target_need_label,
            "target_need_confidence": candidate.target_need_confidence,
            "edge_compatibility_score": candidate.edge_compatibility_score,
            "source_edge_compatibility": candidate.source_edge_compatibility,
            "target_edge_compatibility": candidate.target_edge_compatibility,
            "last_expansion_side": candidate.last_expansion_side,
            "left_piece_ids": json.dumps(
                list(candidate.left_piece_ids),
                ensure_ascii=False,
            ),
            "center_piece_ids": json.dumps(
                list(candidate.center_piece_ids),
                ensure_ascii=False,
            ),
            "right_piece_ids": json.dumps(
                list(candidate.right_piece_ids),
                ensure_ascii=False,
            ),
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
