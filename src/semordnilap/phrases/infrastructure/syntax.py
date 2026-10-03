"""Infrastructure adapters for phrase syntax annotation."""

from __future__ import annotations

import logging

from semordnilap.phrases.domain.model import (
    PhrasePiece,
    PieceSyntax,
    TextSyntax,
    TokenSyntax,
)
from semordnilap.phrases.domain.syntax import (
    NullSyntaxAnnotator,
    empty_text_syntax,
)

logger = logging.getLogger(__name__)


class SpacyPieceSyntaxAnnotator:
    def __init__(self, models: dict[str, str]) -> None:
        try:
            import spacy
        except ImportError as exc:
            raise RuntimeError(
                "spaCy POS tagging requires `spacy`. Install it and pass "
                "--source-spacy-model/--target-spacy-model."
            ) from exc

        self._models = {
            lang: spacy.load(model_name)
            for lang, model_name in models.items()
        }

    def annotate(self, pieces: list[PhrasePiece]) -> dict[int, PieceSyntax]:
        by_text: dict[tuple[str, str], TextSyntax] = {}
        texts_by_lang: dict[str, set[str]] = {}
        for piece in pieces:
            texts_by_lang.setdefault(piece.source_lang or "es", set()).add(
                piece.source_text
            )
            texts_by_lang.setdefault(piece.target_lang or "pt", set()).add(
                piece.target_text
            )

        for lang, texts in texts_by_lang.items():
            model = self._models.get(lang)
            if model is None:
                continue
            ordered = sorted(texts)
            for text, doc in zip(ordered, model.pipe(ordered)):
                by_text[(lang, text)] = _syntax_from_doc(text, lang, doc)

        annotations = {}
        for piece in pieces:
            source_lang = piece.source_lang or "es"
            target_lang = piece.target_lang or "pt"
            annotations[piece.id] = PieceSyntax(
                piece_id=piece.id,
                source=by_text.get(
                    (source_lang, piece.source_text),
                    empty_text_syntax(),
                ),
                target=by_text.get(
                    (target_lang, piece.target_text),
                    empty_text_syntax(),
                ),
            )
        return annotations


def build_syntax_annotator(
    *,
    source_lang: str,
    target_lang: str,
    source_spacy_model: str | None = None,
    target_spacy_model: str | None = None,
    enabled: bool = True,
):
    if not enabled:
        logger.warning(
            "spaCy tagging disabled; syntax_score has no POS/dependency "
            "evidence and morphology penalties stay at 0.0."
        )
        return NullSyntaxAnnotator()

    models = {}
    if source_spacy_model is not None:
        models[source_lang] = source_spacy_model
    if target_spacy_model is not None:
        models[target_lang] = target_spacy_model
    if not models:
        logger.warning(
            "No spaCy tagging models loaded; syntax_score has no POS/"
            "dependency evidence and morphology penalties stay at 0.0."
        )
        return NullSyntaxAnnotator()
    missing = []
    if source_spacy_model is None:
        missing.append(f"{source_lang}=missing")
    if target_spacy_model is None:
        missing.append(f"{target_lang}=missing")
    if missing:
        logger.warning(
            "Partial spaCy setup: %s. Missing sides are unannotated, so their "
            "syntax and morphology signals are disabled.",
            ", ".join(missing),
        )
    logger.info(
        "Loading spaCy syntax models: %s",
        ", ".join(f"{lang}={model}" for lang, model in sorted(models.items())),
    )
    return SpacyPieceSyntaxAnnotator(models)


def _syntax_from_doc(text: str, lang: str, doc) -> TextSyntax:
    tokens = tuple(
        TokenSyntax(
            text=token.text.casefold(),
            lemma=(
                token.lemma_.casefold()
                if token.lemma_
                else token.text.casefold()
            ),
            pos=token.pos_ or "X",
            dep=token.dep_ or "",
            morph=_morph_features(token),
        )
        for token in doc
        if not token.is_space
    )
    return TextSyntax(tokens=tokens)


def _morph_features(token) -> tuple[tuple[str, tuple[str, ...]], ...]:
    features = []
    for key, value in sorted(token.morph.to_dict().items()):
        values = tuple(part for part in value.split(",") if part)
        if values:
            features.append((key, values))
    return tuple(features)
