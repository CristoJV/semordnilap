"""Syntax annotation primitives for phrase graph search.

This module deliberately contains no POS guessing or language-specific
wordlists. If syntactic features are needed, they must come from a trained
model through an infrastructure annotator.
"""

from __future__ import annotations

from semordnilap.phrases.domain.model import (
    PhrasePiece,
    PieceSyntax,
    TextSyntax,
)

CONTENT_POS = {"ADJ", "ADV", "NOUN", "NUM", "PROPN", "VERB"}


class NullSyntaxAnnotator:
    def annotate(self, pieces: list[PhrasePiece]) -> dict[int, PieceSyntax]:
        return {}


def empty_text_syntax() -> TextSyntax:
    return TextSyntax(tokens=())
