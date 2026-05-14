"""Application services for phrase generation."""

from __future__ import annotations

import logging

from semordnilap.phrases.application.commands import GeneratePhrasesCommand
from semordnilap.phrases.domain import (
    PhrasePlausibilityScorer,
    generate_phrase_candidates,
)

logger = logging.getLogger(__name__)


def run_generation(
    command: GeneratePhrasesCommand,
    repository,
    plausibility_scorer: PhrasePlausibilityScorer | None = None,
) -> int:
    pieces = repository.load_pieces(command.input_path)
    logger.info("Loaded %d phrase pieces", len(pieces))

    candidates = generate_phrase_candidates(
        pieces,
        command.policy,
        plausibility_scorer=plausibility_scorer,
    )
    logger.info("Generated %d phrase candidates", len(candidates))

    repository.save_candidates(command.output_path, candidates)
    logger.info("Wrote phrase candidates to %s", command.output_path)
    return len(candidates)
