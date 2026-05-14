"""Infrastructure adapters for phrase plausibility scoring."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


class NullPlausibilityScorer:
    def score(self, text: str, lang: str) -> float:
        return 0.0


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
    models = {}
    if source_lm is not None:
        models[source_lang] = source_lm
    if target_lm is not None:
        models[target_lang] = target_lm
    if not models:
        return NullPlausibilityScorer()
    return KenLmPlausibilityScorer(models)

