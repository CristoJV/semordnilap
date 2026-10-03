"""Infrastructure adapters for phrase plausibility scoring."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


class NullPlausibilityScorer:
    def score(self, text: str, lang: str) -> float:
        return 0.0


class CompositePlausibilityScorer:
    def __init__(self, scorers) -> None:
        self._scorers = list(scorers)

    @lru_cache(maxsize=100_000)
    def score(self, text: str, lang: str) -> float:
        return sum(scorer.score(text, lang) for scorer in self._scorers)


class KenLmPlausibilityScorer:
    def __init__(self, models: dict[str, Path]) -> None:
        try:
            import kenlm
        except ImportError as exc:
            raise RuntimeError(
                "KenLM plausibility scoring requires `kenlm`. "
                "Install it in the environment and pass --source-lm/--target-lm."
            ) from exc

        self._models = {
            lang: kenlm.Model(str(path)) for lang, path in models.items()
        }

    @lru_cache(maxsize=100_000)
    def score(self, text: str, lang: str) -> float:
        model = self._models.get(lang)
        if model is None:
            return 0.0

        tokens = [token for token in text.split() if token.strip()]
        if not tokens:
            return 0.0

        # KenLM returns log10 probability. Divide by length so longer
        # candidates are not punished merely for having more tokens.
        return model.score(text, bos=True, eos=True) / len(tokens)


def build_plausibility_scorer(
    *,
    source_lang: str,
    source_lm: Path | None,
    target_lang: str,
    target_lm: Path | None,
):
    scorers = []
    lm_models = {}
    if source_lm is not None:
        lm_models[source_lang] = source_lm
    if target_lm is not None:
        lm_models[target_lang] = target_lm
    if lm_models:
        missing = []
        if source_lm is None:
            missing.append(f"{source_lang}=missing")
        if target_lm is None:
            missing.append(f"{target_lang}=missing")
        if missing:
            logger.warning(
                "Partial KenLM setup: %s. Missing sides get plausibility=0.0, "
                "which affects the fluency term.",
                ", ".join(missing),
            )
        logger.info(
            "Loading KenLM plausibility models for languages: %s",
            ", ".join(sorted(lm_models)),
        )
        scorers.append(KenLmPlausibilityScorer(lm_models))

    if not scorers:
        logger.warning(
            "No KenLM models loaded; plausibility=0.0 and fluency does not "
            "affect ranking."
        )
        return NullPlausibilityScorer()
    if len(scorers) == 1:
        return scorers[0]
    return CompositePlausibilityScorer(scorers)
