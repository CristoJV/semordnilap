"""Application services for semordnilap search."""

from __future__ import annotations

import csv
import logging
from collections import Counter
from dataclasses import asdict
from time import perf_counter

from semordnilap.search.application.commands import FindSemordnilapsCommand
from semordnilap.utils.artifacts import (
    ArtifactLock,
    atomic_output,
    manifest_path,
    sha256_file,
    stable_id,
    utc_now,
    write_json_atomic,
)

logger = logging.getLogger(__name__)

PAIR_FIELDS = [
    "pair_id",
    "lexical_pair_id",
    "source_lang",
    "source_corpus",
    "source_dataset_id",
    "source_text",
    "source_n",
    "source_count",
    "source_norm_key",
    "source_has_punctuation",
    "target_lang",
    "target_corpus",
    "target_dataset_id",
    "target_text",
    "target_n",
    "target_count",
    "target_norm_key",
    "target_has_punctuation",
    "pair_score",
]


def export_pairs_tsv(command: FindSemordnilapsCommand, repository) -> int:
    if command.output_path is None:
        raise ValueError("Search export requires an output path")
    command.output_path.parent.mkdir(parents=True, exist_ok=True)
    selection = repository.describe_selection(command.policy)
    pairs = repository.iter_pairs(command.policy)
    started_at = perf_counter()
    combinations: Counter[tuple[int, int]] = Counter()
    punctuated_pairs = 0
    score_total = 0.0
    min_score: float | None = None
    max_score: float | None = None

    with ArtifactLock(command.output_path):
        with atomic_output(command.output_path) as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=PAIR_FIELDS,
                delimiter="\t",
            )
            writer.writeheader()
            exported = 0
            for pair in pairs:
                score = pair.pair_score
                writer.writerow(
                    {
                        "pair_id": pair.pair_id,
                        "lexical_pair_id": pair.lexical_pair_id,
                        "source_lang": pair.source_lang,
                        "source_corpus": pair.source_corpus,
                        "source_dataset_id": pair.source_dataset_id,
                        "source_text": pair.source_text,
                        "source_n": pair.source_n,
                        "source_count": pair.source_count,
                        "source_norm_key": pair.source_norm_key,
                        "source_has_punctuation": pair.source_has_punctuation,
                        "target_lang": pair.target_lang,
                        "target_corpus": pair.target_corpus,
                        "target_dataset_id": pair.target_dataset_id,
                        "target_text": pair.target_text,
                        "target_n": pair.target_n,
                        "target_count": pair.target_count,
                        "target_norm_key": pair.target_norm_key,
                        "target_has_punctuation": pair.target_has_punctuation,
                        "pair_score": score,
                    }
                )
                exported += 1
                combinations[(pair.source_n, pair.target_n)] += 1
                punctuated_pairs += int(
                    pair.source_has_punctuation
                    or pair.target_has_punctuation
                )
                score_total += score
                min_score = score if min_score is None else min(min_score, score)
                max_score = score if max_score is None else max(max_score, score)
                if (
                    command.progress_every
                    and exported % command.progress_every == 0
                ):
                    logger.info(
                        "Exported %d semordnilap pairs in %.2fs",
                        exported,
                        perf_counter() - started_at,
                    )

        digest = sha256_file(command.output_path)
        manifest = {
            "schema": "semordnilap.pair-tsv",
            "schema_version": 1,
            "status": "complete",
            "created_at": utc_now(),
            "sha256": digest,
            "artifact_id": stable_id(
                "semordnilap-pairs",
                {
                    "sha256": digest,
                    "selection": selection,
                    "policy": asdict(command.policy),
                },
            ),
            "rows": exported,
            "selection": selection,
            "policy": asdict(command.policy),
            "ordering": [
                "source_count + target_count DESC",
                "source_text ASC",
                "target_text ASC",
            ],
            "score": "ln(source_count + 1) + ln(target_count + 1)",
            "combinations": [
                {
                    "source_n": source_n,
                    "target_n": target_n,
                    "rows": rows,
                }
                for (source_n, target_n), rows in sorted(combinations.items())
            ],
            "punctuated_pairs": punctuated_pairs,
            "score_summary": {
                "min": min_score,
                "max": max_score,
                "mean": round(score_total / exported, 6) if exported else None,
            },
        }
        write_json_atomic(manifest_path(command.output_path), manifest)

    logger.info(
        "Finished pair export: rows=%d punctuated=%d elapsed=%.2fs",
        exported,
        punctuated_pairs,
        perf_counter() - started_at,
    )
    for (source_n, target_n), rows in sorted(combinations.items()):
        logger.info(
            "Pair distribution: source_n=%d target_n=%d rows=%d",
            source_n,
            target_n,
            rows,
        )
    if exported:
        logger.info(
            "Pair score summary: min=%.6f mean=%.6f max=%.6f",
            min_score,
            score_total / exported,
            max_score,
        )
    return exported


def estimate_pairs(command: FindSemordnilapsCommand, repository) -> int:
    estimate = repository.estimate_pairs(command.policy)
    logger.info(
        "Dry-run datasets: source=%s generation=%s target=%s generation=%s",
        estimate["source_dataset_id"],
        estimate["source_generation"],
        estimate["target_dataset_id"],
        estimate["target_generation"],
    )
    logger.info(
        "Dry-run candidates: source=%d target=%d matching_pairs=%d "
        "output_pairs=%d",
        estimate["source_candidates"],
        estimate["target_candidates"],
        estimate["matching_pairs"],
        estimate["output_pairs"],
    )
    for source_n, target_n, rows in estimate["combinations"]:
        logger.info(
            "Dry-run matching distribution before result limit: "
            "source_n=%d target_n=%d pairs=%d",
            source_n,
            target_n,
            rows,
        )
    return estimate["output_pairs"]


def run_search(command: FindSemordnilapsCommand, repository) -> int:
    try:
        if command.dry_run:
            return estimate_pairs(command, repository)
        return export_pairs_tsv(command, repository)
    finally:
        repository.close()
