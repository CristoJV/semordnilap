"""Small, inspectable scoring functions for phrase search.

The search uses two scores:

* ``growth_score``: prefix viability while the beam expands.
* ``score``: final quality once a candidate has enough pieces.

Both scores are intentionally made from a few model-backed or corpus-backed
signals. There are no language-specific token lists here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from semordnilap.phrases.domain.model import (
    GeneratePhrasePolicy,
    PieceSyntax,
    PhrasePiece,
    TextSyntax,
    TokenSyntax,
)
from semordnilap.phrases.domain.syntax import CONTENT_POS

OPEN_POS = {"ADP", "AUX", "CCONJ", "DET", "PART", "SCONJ"}
AGREEMENT_HEAD_POS = {"NOUN", "PRON", "PROPN"}
AGREEMENT_MODIFIER_POS = {"ADJ", "DET", "NUM"}
SUBJECT_DEPS = {"csubj", "csubj:pass", "expl", "nsubj", "nsubj:pass"}


@dataclass(frozen=True)
class PhraseScoringContext:
    piece_syntax: dict[int, PieceSyntax]

    @classmethod
    def from_pieces(
        cls,
        pieces: list[PhrasePiece],
        piece_syntax: dict[int, PieceSyntax] | None = None,
    ) -> "PhraseScoringContext":
        return cls(piece_syntax=piece_syntax or {})


@dataclass(frozen=True)
class NeedEstimate:
    label: str
    confidence: float = 0.0


@dataclass(frozen=True)
class PhraseDiagnostics:
    source_partial_viability: float = 0.0
    target_partial_viability: float = 0.0
    bilingual_partial_viability: float = 0.0
    source_completion_score: float = 0.0
    target_completion_score: float = 0.0
    bilingual_completion_score: float = 0.0
    source_boundary_score: float = 0.0
    target_boundary_score: float = 0.0
    source_dead_end_score: float = 0.0
    target_dead_end_score: float = 0.0
    bilingual_dead_end_score: float = 0.0
    source_need: NeedEstimate = NeedEstimate("unknown", 0.0)
    target_need: NeedEstimate = NeedEstimate("unknown", 0.0)
    edge_compatibility_score: float = 0.0
    source_edge_compatibility: float = 0.0
    target_edge_compatibility: float = 0.0
    diagnostic_flags: dict[str, float] = field(default_factory=dict)


def tokens(text: str) -> list[str]:
    return [token.casefold() for token in text.split() if token.strip()]


def phrase_langs(pieces: tuple[PhrasePiece, ...]) -> tuple[str, str]:
    source_lang = pieces[0].source_lang or "source"
    target_lang = pieces[0].target_lang or "target"
    return source_lang, target_lang


def phrase_texts(pieces: tuple[PhrasePiece, ...]) -> tuple[str, str]:
    source_phrase = " ".join(piece.source_text for piece in pieces)
    target_phrase = " ".join(piece.target_text for piece in reversed(pieces))
    return source_phrase, target_phrase


def pair_quality(pieces: tuple[PhrasePiece, ...]) -> float:
    if not pieces:
        return 0.0
    return sum(piece.pair_score for piece in pieces) / len(pieces)


def boundary_score(left_tokens: list[str], right_tokens: list[str]) -> float:
    if not left_tokens or not right_tokens:
        return 0.0
    if left_tokens[-1] == right_tokens[0]:
        return -1.0
    return 0.0


def bilingual_min(source_score: float, target_score: float) -> float:
    return min(source_score, target_score)


def edge_compatibility_score(
    left_text: str,
    right_text: str,
    left_syntax: TextSyntax | None = None,
    right_syntax: TextSyntax | None = None,
) -> float:
    score = boundary_score(tokens(left_text), tokens(right_text))
    if left_syntax is not None and right_syntax is not None:
        score += _syntax_boundary_score(left_syntax, right_syntax)
    return round(score, 6)


def right_edge_compatibility(
    previous: tuple[PhrasePiece, ...],
    piece: PhrasePiece,
    context: PhraseScoringContext | None = None,
) -> tuple[float, float]:
    if not previous:
        return 0.0, 0.0
    previous_syntax = _syntax_for_piece(context, previous[-1])
    piece_syntax = _syntax_for_piece(context, piece)
    source = edge_compatibility_score(
        previous[-1].source_text,
        piece.source_text,
        previous_syntax.source if previous_syntax is not None else None,
        piece_syntax.source if piece_syntax is not None else None,
    )
    target = edge_compatibility_score(
        piece.target_text,
        previous[-1].target_text,
        piece_syntax.target if piece_syntax is not None else None,
        previous_syntax.target if previous_syntax is not None else None,
    )
    return source, target


def left_edge_compatibility(
    previous: tuple[PhrasePiece, ...],
    piece: PhrasePiece,
    context: PhraseScoringContext | None = None,
) -> tuple[float, float]:
    if not previous:
        return 0.0, 0.0
    previous_syntax = _syntax_for_piece(context, previous[0])
    piece_syntax = _syntax_for_piece(context, piece)
    source = edge_compatibility_score(
        piece.source_text,
        previous[0].source_text,
        piece_syntax.source if piece_syntax is not None else None,
        previous_syntax.source if previous_syntax is not None else None,
    )
    target = edge_compatibility_score(
        previous[0].target_text,
        piece.target_text,
        previous_syntax.target if previous_syntax is not None else None,
        piece_syntax.target if piece_syntax is not None else None,
    )
    return source, target


def _syntax_for_piece(
    context: PhraseScoringContext | None,
    piece: PhrasePiece,
) -> PieceSyntax | None:
    if context is None:
        return None
    return context.piece_syntax.get(piece.id)


def right_transition_score(
    previous: tuple[PhrasePiece, ...],
    piece: PhrasePiece,
    context: PhraseScoringContext | None = None,
    syntax_weight: float = 1.0,
) -> float:
    if not previous:
        return 0.0
    source = boundary_score(
        tokens(previous[-1].source_text),
        tokens(piece.source_text),
    )
    target = boundary_score(
        tokens(piece.target_text),
        tokens(previous[-1].target_text),
    )
    return source + target + syntax_weight * _right_syntax_score(
        previous,
        piece,
        context,
    )


def left_transition_score(
    previous: tuple[PhrasePiece, ...],
    piece: PhrasePiece,
    context: PhraseScoringContext | None = None,
    syntax_weight: float = 1.0,
) -> float:
    if not previous:
        return 0.0
    source = boundary_score(
        tokens(piece.source_text),
        tokens(previous[0].source_text),
    )
    target = boundary_score(
        tokens(previous[0].target_text),
        tokens(piece.target_text),
    )
    return source + target + syntax_weight * _left_syntax_score(
        previous,
        piece,
        context,
    )


def phrase_transition_score(
    pieces: tuple[PhrasePiece, ...],
    context: PhraseScoringContext | None = None,
    syntax_weight: float = 1.0,
) -> float:
    return sum(
        right_transition_score(
            pieces[:index],
            pieces[index],
            context,
            syntax_weight,
        )
        for index in range(1, len(pieces))
    )


def _right_syntax_score(
    previous: tuple[PhrasePiece, ...],
    piece: PhrasePiece,
    context: PhraseScoringContext | None,
) -> float:
    if context is None:
        return 0.0
    previous_syntax = context.piece_syntax.get(previous[-1].id)
    piece_syntax = context.piece_syntax.get(piece.id)
    if previous_syntax is None or piece_syntax is None:
        return 0.0
    return _syntax_boundary_score(previous_syntax.source, piece_syntax.source) + (
        _syntax_boundary_score(piece_syntax.target, previous_syntax.target)
    )


def _left_syntax_score(
    previous: tuple[PhrasePiece, ...],
    piece: PhrasePiece,
    context: PhraseScoringContext | None,
) -> float:
    if context is None:
        return 0.0
    previous_syntax = context.piece_syntax.get(previous[0].id)
    piece_syntax = context.piece_syntax.get(piece.id)
    if previous_syntax is None or piece_syntax is None:
        return 0.0
    return _syntax_boundary_score(piece_syntax.source, previous_syntax.source) + (
        _syntax_boundary_score(previous_syntax.target, piece_syntax.target)
    )


def _syntax_boundary_score(left: TextSyntax, right: TextSyntax) -> float:
    if not left.tokens or not right.tokens:
        return 0.0
    left_pos = left.tokens[-1].pos
    right_pos = right.tokens[0].pos
    if left_pos == right_pos and left_pos not in CONTENT_POS:
        return -1.0
    if left_pos in OPEN_POS and right_pos in OPEN_POS:
        return -0.75
    if left_pos in OPEN_POS and right_pos in CONTENT_POS:
        return 0.5
    return 0.0


def phrase_syntax_score(
    pieces: tuple[PhrasePiece, ...],
    context: PhraseScoringContext,
    *,
    complete: bool = False,
) -> float:
    source_tokens, target_tokens = syntax_tokens(pieces, context)
    return round(
        _side_syntax_score(source_tokens, complete=complete)
        + _side_syntax_score(target_tokens, complete=complete),
        6,
    )


def syntax_tokens(
    pieces: tuple[PhrasePiece, ...],
    context: PhraseScoringContext,
) -> tuple[list[TokenSyntax], list[TokenSyntax]]:
    source_tokens: list[TokenSyntax] = []
    target_tokens: list[TokenSyntax] = []
    for piece in pieces:
        syntax = context.piece_syntax.get(piece.id)
        if syntax is not None:
            source_tokens.extend(syntax.source.tokens)
    for piece in reversed(pieces):
        syntax = context.piece_syntax.get(piece.id)
        if syntax is not None:
            target_tokens.extend(syntax.target.tokens)
    return source_tokens, target_tokens


def _side_syntax_score(
    syntax_tokens: list[TokenSyntax],
    *,
    complete: bool,
) -> float:
    if not syntax_tokens:
        return 0.0
    positions = [token.pos for token in syntax_tokens]
    score = 0.2 * sum(pos in CONTENT_POS for pos in positions)
    if positions[-1] in OPEN_POS:
        score -= 0.75 if complete else 0.25
    if complete:
        if not any(pos in CONTENT_POS for pos in positions):
            score -= 1.0
        if positions[0] in OPEN_POS:
            score -= 0.5
        if has_clause_shape(syntax_tokens):
            score += 1.0
    return score


def has_clause_shape(syntax_tokens: list[TokenSyntax]) -> bool:
    has_subject = any(token.dep.lower() in SUBJECT_DEPS for token in syntax_tokens)
    has_verb = any(token.pos in {"AUX", "VERB"} for token in syntax_tokens)
    has_content = sum(token.pos in CONTENT_POS for token in syntax_tokens) >= 2
    return has_verb and (has_subject or has_content)


def boundary_completion_score(syntax_tokens: list[TokenSyntax]) -> float:
    if not syntax_tokens:
        return 0.0
    positions = [token.pos for token in syntax_tokens]
    score = 0.0
    if any(pos in CONTENT_POS for pos in positions):
        score += 0.35
    if positions[-1] in CONTENT_POS:
        score += 0.2
    if has_clause_shape(syntax_tokens):
        score += 0.6
    if positions[-1] in OPEN_POS:
        score -= 0.45
    if positions[0] in OPEN_POS:
        score -= 0.2
    if not any(pos in CONTENT_POS for pos in positions):
        score -= 0.35
    return round(score, 6)


def partial_viability_score(syntax_tokens: list[TokenSyntax]) -> float:
    if not syntax_tokens:
        return 0.0
    positions = [token.pos for token in syntax_tokens]
    content_count = sum(pos in CONTENT_POS for pos in positions)
    score = min(0.6, 0.15 * content_count)
    if content_count:
        score += 0.2
    else:
        score -= 0.1
    if positions[-1] in OPEN_POS:
        score += 0.2
    if has_clause_shape(syntax_tokens):
        score += 0.4
    if len(positions) > 1 and positions[-1] == positions[-2] in OPEN_POS:
        score -= 0.35
    return round(score, 6)


def completion_score(syntax_tokens: list[TokenSyntax]) -> float:
    if not syntax_tokens:
        return 0.0
    score = boundary_completion_score(syntax_tokens)
    if any(token.pos in CONTENT_POS for token in syntax_tokens):
        score += 0.25
    else:
        score -= 0.25
    if has_clause_shape(syntax_tokens):
        score += 0.4
    return round(score, 6)


def infer_open_need(syntax_tokens: list[TokenSyntax]) -> NeedEstimate:
    if not syntax_tokens:
        return NeedEstimate("unknown", 0.0)
    positions = [token.pos for token in syntax_tokens]
    if positions[-1] in OPEN_POS:
        return NeedEstimate("needs_continuation", 0.75)
    if not any(pos in CONTENT_POS for pos in positions):
        return NeedEstimate("needs_nominal_head", 0.65)
    if not any(pos in {"AUX", "VERB"} for pos in positions):
        return NeedEstimate("likely_complete", 0.5)
    if has_clause_shape(syntax_tokens):
        return NeedEstimate("likely_complete", 0.8)
    return NeedEstimate("needs_predicate", 0.55)


def build_phrase_diagnostics(
    *,
    pieces: tuple[PhrasePiece, ...],
    context: PhraseScoringContext,
    source_edge_compatibility: float = 0.0,
    target_edge_compatibility: float = 0.0,
) -> PhraseDiagnostics:
    source_tokens, target_tokens = syntax_tokens(pieces, context)
    source_partial = partial_viability_score(source_tokens)
    target_partial = partial_viability_score(target_tokens)
    source_completion = completion_score(source_tokens)
    target_completion = completion_score(target_tokens)
    source_boundary = boundary_completion_score(source_tokens)
    target_boundary = boundary_completion_score(target_tokens)
    source_dead_end = max(0.0, -source_partial) + 0.5 * max(
        0.0,
        -source_edge_compatibility,
    )
    target_dead_end = max(0.0, -target_partial) + 0.5 * max(
        0.0,
        -target_edge_compatibility,
    )
    edge_score = bilingual_min(
        source_edge_compatibility,
        target_edge_compatibility,
    )
    flags: dict[str, float] = {}
    _add_flag(flags, "low_source_partial_viability", -source_partial)
    _add_flag(flags, "low_target_partial_viability", -target_partial)
    _add_flag(flags, "low_source_completion", -source_completion)
    _add_flag(flags, "low_target_completion", -target_completion)
    _add_flag(flags, "weak_source_edge", -source_edge_compatibility)
    _add_flag(flags, "weak_target_edge", -target_edge_compatibility)
    return PhraseDiagnostics(
        source_partial_viability=source_partial,
        target_partial_viability=target_partial,
        bilingual_partial_viability=bilingual_min(source_partial, target_partial),
        source_completion_score=source_completion,
        target_completion_score=target_completion,
        bilingual_completion_score=bilingual_min(
            source_completion,
            target_completion,
        ),
        source_boundary_score=source_boundary,
        target_boundary_score=target_boundary,
        source_dead_end_score=round(source_dead_end, 6),
        target_dead_end_score=round(target_dead_end, 6),
        bilingual_dead_end_score=round(max(source_dead_end, target_dead_end), 6),
        source_need=infer_open_need(source_tokens),
        target_need=infer_open_need(target_tokens),
        edge_compatibility_score=edge_score,
        source_edge_compatibility=source_edge_compatibility,
        target_edge_compatibility=target_edge_compatibility,
        diagnostic_flags=flags,
    )


def _add_flag(flags: dict[str, float], label: str, value: float) -> None:
    if value > 0:
        flags[label] = round(value, 6)


def morphology_agreement_penalty(
    pieces: tuple[PhrasePiece, ...],
    context: PhraseScoringContext,
    features: tuple[str, ...],
) -> float:
    source_tokens, target_tokens = syntax_tokens(pieces, context)
    return round(
        _side_morphology_agreement_penalty(source_tokens, features)
        + _side_morphology_agreement_penalty(target_tokens, features),
        6,
    )


def _side_morphology_agreement_penalty(
    syntax_tokens: list[TokenSyntax],
    features: tuple[str, ...],
) -> float:
    penalty = 0.0
    for index, token in enumerate(syntax_tokens):
        if token.pos not in AGREEMENT_MODIFIER_POS:
            continue
        head = _nearest_agreement_head(syntax_tokens, index)
        if head is not None:
            penalty += _morph_mismatch_penalty(token, head, features)
    return penalty


def _nearest_agreement_head(
    syntax_tokens: list[TokenSyntax],
    index: int,
) -> TokenSyntax | None:
    for distance in range(1, 4):
        right_index = index + distance
        if (
            right_index < len(syntax_tokens)
            and syntax_tokens[right_index].pos in AGREEMENT_HEAD_POS
        ):
            return syntax_tokens[right_index]
        left_index = index - distance
        if left_index >= 0 and syntax_tokens[left_index].pos in AGREEMENT_HEAD_POS:
            return syntax_tokens[left_index]
    return None


def _morph_mismatch_penalty(
    modifier: TokenSyntax,
    head: TokenSyntax,
    features: tuple[str, ...],
) -> float:
    penalty = 0.0
    for feature in features:
        modifier_values = _morph_values(modifier, feature)
        head_values = _morph_values(head, feature)
        if modifier_values and head_values and modifier_values.isdisjoint(head_values):
            penalty += 1.0
    return penalty


def _morph_values(token: TokenSyntax, feature: str) -> set[str]:
    for key, values in token.morph:
        if key == feature:
            return set(values)
    return set()


def repeated_piece_penalty(pieces: tuple[PhrasePiece, ...]) -> float:
    seen = set()
    penalty = 0.0
    for piece in pieces:
        if piece.id in seen:
            penalty += 1.0
        seen.add(piece.id)
    return penalty


def score_growth(
    *,
    pieces: tuple[PhrasePiece, ...],
    policy: GeneratePhrasePolicy,
    context: PhraseScoringContext,
    plausibility_delta: float,
    transition: float,
    diagnostics: PhraseDiagnostics | None = None,
) -> float:
    diagnostics = diagnostics or build_phrase_diagnostics(
        pieces=pieces,
        context=context,
    )
    boundary = bilingual_min(
        diagnostics.source_boundary_score,
        diagnostics.target_boundary_score,
    )
    score = (
        policy.pair_weight * pair_quality(pieces)
        + policy.fluency_weight * plausibility_delta
        + transition
        + policy.syntax_weight * phrase_syntax_score(pieces, context)
        + policy.partial_viability_weight
        * diagnostics.bilingual_partial_viability
        + policy.edge_compatibility_weight
        * diagnostics.edge_compatibility_score
        + policy.boundary_weight * boundary
        - policy.dead_end_weight * diagnostics.bilingual_dead_end_score
        - policy.morphology_weight
        * morphology_agreement_penalty(
            pieces,
            context,
            policy.morphology_agreement_features,
        )
        - policy.repeat_penalty * repeated_piece_penalty(pieces)
    )
    return round(score, 6)


def score_final(
    *,
    pieces: tuple[PhrasePiece, ...],
    policy: GeneratePhrasePolicy,
    context: PhraseScoringContext,
    source_plausibility: float,
    target_plausibility: float,
    diagnostics: PhraseDiagnostics | None = None,
) -> float:
    diagnostics = diagnostics or build_phrase_diagnostics(
        pieces=pieces,
        context=context,
    )
    fluency = min(source_plausibility, target_plausibility)
    boundary = bilingual_min(
        diagnostics.source_boundary_score,
        diagnostics.target_boundary_score,
    )
    score = (
        policy.pair_weight * pair_quality(pieces)
        + policy.fluency_weight * fluency
        + policy.syntax_weight
        * phrase_syntax_score(pieces, context, complete=True)
        + policy.completion_weight * diagnostics.bilingual_completion_score
        + policy.boundary_weight * boundary
        - policy.dead_end_weight * diagnostics.bilingual_dead_end_score
        + policy.complete_bonus * max(0, len(pieces) - policy.min_pieces + 1)
        - policy.morphology_weight
        * morphology_agreement_penalty(
            pieces,
            context,
            policy.morphology_agreement_features,
        )
        - policy.repeat_penalty * repeated_piece_penalty(pieces)
    )
    return round(score, 6)
