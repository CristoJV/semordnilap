"""Application services for semordnilap search."""

from __future__ import annotations

import csv
import logging

from semordnilap.search.application.commands import FindSemordnilapsCommand

logger = logging.getLogger(__name__)


def export_pairs_tsv(command: FindSemordnilapsCommand, repository) -> int:
    command.output_path.parent.mkdir(parents=True, exist_ok=True)
    pairs = repository.iter_pairs(command.policy)

    with command.output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
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
            ],
            delimiter="\t",
        )
        writer.writeheader()
        exported = 0
        for pair in pairs:
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
                    "pair_score": pair.pair_score,
                }
            )
            exported += 1

    logger.info("Exported %d semordnilap pairs", exported)
    return exported


def run_search(command: FindSemordnilapsCommand, repository) -> int:
    try:
        return export_pairs_tsv(command, repository)
    finally:
        repository.close()
