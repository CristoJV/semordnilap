"""Domain services for phrase generation."""

from __future__ import annotations

import logging

from semordnilap.phrases.domain.model import (
    GeneratePhrasePolicy,
    PhraseCandidate,
    PhrasePlausibilityScorer,
    PhrasePiece,
    PhraseSyntaxAnnotator,
)
from semordnilap.phrases.domain.scoring import (
    PhraseScoringContext,
    build_phrase_diagnostics,
    left_transition_score,
    left_edge_compatibility,
    phrase_langs,
    phrase_syntax_score,
    phrase_texts,
    right_edge_compatibility,
    right_transition_score,
    score_final,
    score_growth,
    tokens,
)
from semordnilap.phrases.domain.syntax import NullSyntaxAnnotator

logger = logging.getLogger(__name__)
TOP_LOG_LIMIT = 3
TRACE_TOP_LIMIT = 25


def piece_quality(piece: PhrasePiece) -> float:
    return piece.pair_score


def _basic_piece_filter(
    pieces: list[PhrasePiece],
    policy: GeneratePhrasePolicy,
) -> list[PhrasePiece]:
    return [
        piece
        for piece in pieces
        if piece.formal_ok
        and piece.source_count >= policy.min_source_count
        and piece.target_count >= policy.min_target_count
        and piece.pair_score >= policy.min_pair_score
        and piece.source_n <= policy.max_source_n
        and piece.target_n <= policy.max_target_n
    ]


def filter_pieces(
    pieces: list[PhrasePiece],
    policy: GeneratePhrasePolicy,
    context: PhraseScoringContext | None = None,
) -> list[PhrasePiece]:
    filtered = _basic_piece_filter(pieces, policy)
    filtered.sort(key=piece_quality, reverse=True)
    return filtered[: policy.piece_limit]


def score_plausibility(
    pieces: tuple[PhrasePiece, ...],
    scorer: PhrasePlausibilityScorer | None,
) -> tuple[float, float]:
    if scorer is None:
        return 0.0, 0.0

    source_phrase, target_phrase = phrase_texts(pieces)
    source_lang, target_lang = phrase_langs(pieces)
    return (
        scorer.score(source_phrase, source_lang),
        scorer.score(target_phrase, target_lang),
    )


def score_candidate(
    pieces: tuple[PhrasePiece, ...],
    policy: GeneratePhrasePolicy,
    context: PhraseScoringContext | None = None,
    source_plausibility: float = 0.0,
    target_plausibility: float = 0.0,
) -> float:
    context = context or PhraseScoringContext.from_pieces(list(pieces))
    return score_final(
        pieces=pieces,
        policy=policy,
        context=context,
        source_plausibility=source_plausibility,
        target_plausibility=target_plausibility,
    )


def extend_candidate(
    candidate: PhraseCandidate,
    piece: PhrasePiece,
    policy: GeneratePhrasePolicy,
    plausibility_scorer: PhrasePlausibilityScorer | None,
    context: PhraseScoringContext,
    side: str = "right",
) -> PhraseCandidate:
    if side == "left":
        pieces = (piece, *candidate.pieces)
        transition = left_transition_score(
            candidate.pieces,
            piece,
            context,
            policy.syntax_weight,
        )
        source_edge, target_edge = left_edge_compatibility(
            candidate.pieces,
            piece,
            context,
        )
    elif side == "right":
        pieces = (*candidate.pieces, piece)
        transition = right_transition_score(
            candidate.pieces,
            piece,
            context,
            policy.syntax_weight,
        )
        source_edge, target_edge = right_edge_compatibility(
            candidate.pieces,
            piece,
            context,
        )
    else:
        raise ValueError("side must be 'left' or 'right'")

    source_plausibility, target_plausibility = score_plausibility(
        pieces,
        plausibility_scorer,
    )
    previous_plausibility = (
        candidate.source_plausibility + candidate.target_plausibility
    )
    plausibility_delta = (
        source_plausibility + target_plausibility - previous_plausibility
    )
    diagnostics = build_phrase_diagnostics(
        pieces=pieces,
        context=context,
        source_edge_compatibility=source_edge,
        target_edge_compatibility=target_edge,
    )
    growth = score_growth(
        pieces=pieces,
        policy=policy,
        context=context,
        plausibility_delta=plausibility_delta,
        transition=transition,
        diagnostics=diagnostics,
    )
    final = score_final(
        pieces=pieces,
        policy=policy,
        context=context,
        source_plausibility=source_plausibility,
        target_plausibility=target_plausibility,
        diagnostics=diagnostics,
    )
    left_ids, center_ids, right_ids = _expanded_piece_groups(
        candidate,
        piece,
        side,
    )
    return PhraseCandidate(
        pieces=pieces,
        score=final,
        growth_score=growth,
        growth_mode=candidate.growth_mode,
        source_plausibility=source_plausibility,
        target_plausibility=target_plausibility,
        transition_score=transition,
        syntax_score=phrase_syntax_score(pieces, context),
        last_expansion_side=side,
        source_partial_viability=diagnostics.source_partial_viability,
        target_partial_viability=diagnostics.target_partial_viability,
        bilingual_partial_viability=diagnostics.bilingual_partial_viability,
        source_completion_score=diagnostics.source_completion_score,
        target_completion_score=diagnostics.target_completion_score,
        bilingual_completion_score=diagnostics.bilingual_completion_score,
        source_boundary_score=diagnostics.source_boundary_score,
        target_boundary_score=diagnostics.target_boundary_score,
        source_dead_end_score=diagnostics.source_dead_end_score,
        target_dead_end_score=diagnostics.target_dead_end_score,
        bilingual_dead_end_score=diagnostics.bilingual_dead_end_score,
        source_need_label=diagnostics.source_need.label,
        source_need_confidence=diagnostics.source_need.confidence,
        target_need_label=diagnostics.target_need.label,
        target_need_confidence=diagnostics.target_need.confidence,
        edge_compatibility_score=diagnostics.edge_compatibility_score,
        source_edge_compatibility=diagnostics.source_edge_compatibility,
        target_edge_compatibility=diagnostics.target_edge_compatibility,
        left_piece_ids=left_ids,
        center_piece_ids=center_ids,
        right_piece_ids=right_ids,
        diagnostic_flags=diagnostics.diagnostic_flags,
    )


def empty_candidate() -> PhraseCandidate:
    return PhraseCandidate(pieces=(), score=0.0)


def center_seed_candidate(
    piece: PhrasePiece,
    policy: GeneratePhrasePolicy,
    plausibility_scorer: PhrasePlausibilityScorer | None,
    context: PhraseScoringContext,
) -> PhraseCandidate:
    pieces = (piece,)
    source_plausibility, target_plausibility = score_plausibility(
        pieces,
        plausibility_scorer,
    )
    diagnostics = build_phrase_diagnostics(pieces=pieces, context=context)
    growth = score_growth(
        pieces=pieces,
        policy=policy,
        context=context,
        plausibility_delta=source_plausibility + target_plausibility,
        transition=0.0,
        diagnostics=diagnostics,
    )
    final = score_final(
        pieces=pieces,
        policy=policy,
        context=context,
        source_plausibility=source_plausibility,
        target_plausibility=target_plausibility,
        diagnostics=diagnostics,
    )
    return PhraseCandidate(
        pieces=pieces,
        score=final,
        growth_score=growth,
        growth_mode="center",
        source_plausibility=source_plausibility,
        target_plausibility=target_plausibility,
        syntax_score=phrase_syntax_score(pieces, context),
        last_expansion_side="center",
        source_partial_viability=diagnostics.source_partial_viability,
        target_partial_viability=diagnostics.target_partial_viability,
        bilingual_partial_viability=diagnostics.bilingual_partial_viability,
        source_completion_score=diagnostics.source_completion_score,
        target_completion_score=diagnostics.target_completion_score,
        bilingual_completion_score=diagnostics.bilingual_completion_score,
        source_boundary_score=diagnostics.source_boundary_score,
        target_boundary_score=diagnostics.target_boundary_score,
        source_dead_end_score=diagnostics.source_dead_end_score,
        target_dead_end_score=diagnostics.target_dead_end_score,
        bilingual_dead_end_score=diagnostics.bilingual_dead_end_score,
        source_need_label=diagnostics.source_need.label,
        source_need_confidence=diagnostics.source_need.confidence,
        target_need_label=diagnostics.target_need.label,
        target_need_confidence=diagnostics.target_need.confidence,
        edge_compatibility_score=diagnostics.edge_compatibility_score,
        source_edge_compatibility=diagnostics.source_edge_compatibility,
        target_edge_compatibility=diagnostics.target_edge_compatibility,
        center_piece_ids=(piece.id,),
        diagnostic_flags=diagnostics.diagnostic_flags,
    )


def _expanded_piece_groups(
    candidate: PhraseCandidate,
    piece: PhrasePiece,
    side: str,
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    if candidate.growth_mode != "center":
        return (), (), ()
    if side == "left":
        return (
            (piece.id, *candidate.left_piece_ids),
            candidate.center_piece_ids,
            candidate.right_piece_ids,
        )
    return (
        candidate.left_piece_ids,
        candidate.center_piece_ids,
        (*candidate.right_piece_ids, piece.id),
    )


class PhraseSearchTrace:
    def __init__(self, top_limit: int = TRACE_TOP_LIMIT) -> None:
        self.top_limit = top_limit
        self.search: dict = {}
        self.levels: list[dict] = []
        self.final: dict = {}

    def record_start(
        self,
        *,
        pieces_count: int,
        usable_count: int,
        syntax_annotated: int,
        policy: GeneratePhrasePolicy,
    ) -> None:
        self.search = {
            "pieces_count": pieces_count,
            "usable_count": usable_count,
            "syntax_annotated": syntax_annotated,
            "policy": {
                "min_pieces": policy.min_pieces,
                "max_pieces": policy.max_pieces,
                "beam_size": policy.beam_size,
                "candidate_pool_size": effective_candidate_pool_size(policy),
                "expand_sides": policy.expand_sides,
                "piece_limit": policy.piece_limit,
                "pair_weight": policy.pair_weight,
                "fluency_weight": policy.fluency_weight,
                "syntax_weight": policy.syntax_weight,
                "morphology_weight": policy.morphology_weight,
                "morphology_agreement_features": (
                    policy.morphology_agreement_features
                ),
                "repeat_penalty": policy.repeat_penalty,
                "complete_bonus": policy.complete_bonus,
                "partial_viability_weight": policy.partial_viability_weight,
                "completion_weight": policy.completion_weight,
                "dead_end_weight": policy.dead_end_weight,
                "boundary_weight": policy.boundary_weight,
                "edge_compatibility_weight": (
                    policy.edge_compatibility_weight
                ),
                "min_completion_score": policy.min_completion_score,
                "min_partial_viability": policy.min_partial_viability,
                "forbid_low_completion_final": (
                    policy.forbid_low_completion_final
                ),
                "center_seed_limit": policy.center_seed_limit,
                "source_boundary_model": (
                    str(policy.source_boundary_model)
                    if policy.source_boundary_model is not None
                    else None
                ),
                "target_boundary_model": (
                    str(policy.target_boundary_model)
                    if policy.target_boundary_model is not None
                    else None
                ),
                "source_transition_model": (
                    str(policy.source_transition_model)
                    if policy.source_transition_model is not None
                    else None
                ),
                "target_transition_model": (
                    str(policy.target_transition_model)
                    if policy.target_transition_model is not None
                    else None
                ),
            },
        }

    def record_level(
        self,
        *,
        level: int,
        input_beam_size: int,
        expanded: list[PhraseCandidate],
        beam: list[PhraseCandidate],
        policy: GeneratePhrasePolicy,
        context: PhraseScoringContext,
        expanded_count: int | None = None,
    ) -> None:
        top_growth = sorted(
            expanded,
            key=lambda item: item.growth_score,
            reverse=True,
        )[: self.top_limit]
        top_final = sorted(
            beam,
            key=lambda item: item.score,
            reverse=True,
        )[: self.top_limit]
        self.levels.append(
            {
                "level": level,
                "input_beam_size": input_beam_size,
                "expanded_count": expanded_count
                if expanded_count is not None
                else len(expanded),
                "expanded_pool_size": len(expanded),
                "selected_beam_size": len(beam),
                "top_growth": [
                    _candidate_trace(candidate, context)
                    for candidate in top_growth
                ],
                "selected_top_final": [
                    _candidate_trace(candidate, context)
                    for candidate in top_final
                ],
                "selected_frontier_edges": [
                    _candidate_edge(candidate)
                    for candidate in beam[: self.top_limit]
                ],
            }
        )

    def record_final(
        self,
        *,
        raw_results: int,
        deduplicated_count: int,
        returned: list[PhraseCandidate],
        policy: GeneratePhrasePolicy,
        context: PhraseScoringContext,
    ) -> None:
        self.final = {
            "raw_results": raw_results,
            "deduplicated_count": deduplicated_count,
            "returned_count": len(returned),
            "top_results": [
                _candidate_trace(candidate, context)
                for candidate in returned[: self.top_limit]
            ],
        }

    def to_dict(self) -> dict:
        return {
            "search": self.search,
            "levels": self.levels,
            "final": self.final,
        }


def expansion_sides(policy: GeneratePhrasePolicy) -> tuple[str, ...]:
    if policy.expand_sides == "both":
        return "right", "left"
    if policy.expand_sides == "center":
        return "left", "right"
    if policy.expand_sides in {"right", "left"}:
        return (policy.expand_sides,)
    raise ValueError("expand_sides must be one of: both, right, left, center")


def _candidate_summary(candidate: PhraseCandidate) -> str:
    return (
        f"{candidate.source_phrase!r} <> {candidate.target_phrase!r} "
        f"growth={candidate.growth_score:.3f} "
        f"final={candidate.score:.3f} "
        f"pieces={candidate.piece_count} "
        f"side={candidate.last_expansion_side or '-'}"
    )


def log_top_candidates(
    label: str,
    candidates: list[PhraseCandidate],
    *,
    key,
) -> None:
    if not candidates:
        logger.debug("%s: no candidates", label)
        return

    top = sorted(candidates, key=key, reverse=True)[:TOP_LOG_LIMIT]
    logger.debug(
        "%s top %d:\n%s",
        label,
        len(top),
        "\n".join(
            f"{index}. {_candidate_summary(candidate)}"
            for index, candidate in enumerate(top, 1)
        ),
    )


def _candidate_key(candidate: PhraseCandidate) -> tuple[str, str]:
    return candidate.source_norm_key, candidate.target_norm_key


def _sequence_key(candidate: PhraseCandidate) -> tuple[int, ...]:
    return tuple(piece.id for piece in candidate.pieces)


def _sequence_id(pieces: tuple[PhrasePiece, ...]) -> str:
    if not pieces:
        return "root"
    return "-".join(str(piece.id) for piece in pieces)


def _parent_pieces(candidate: PhraseCandidate) -> tuple[PhrasePiece, ...]:
    if not candidate.pieces:
        return ()
    if candidate.last_expansion_side == "left":
        return candidate.pieces[1:]
    return candidate.pieces[:-1]


def _added_piece(candidate: PhraseCandidate) -> PhrasePiece | None:
    if not candidate.pieces:
        return None
    if candidate.last_expansion_side == "left":
        return candidate.pieces[0]
    return candidate.pieces[-1]


def _candidate_edge(candidate: PhraseCandidate) -> dict:
    added = _added_piece(candidate)
    return {
        "from": _sequence_id(_parent_pieces(candidate)),
        "to": _sequence_id(candidate.pieces),
        "growth_mode": candidate.growth_mode,
        "side": candidate.last_expansion_side,
        "added_piece_id": added.id if added is not None else None,
        "added_piece": added.label if added is not None else "",
        "source_phrase": candidate.source_phrase,
        "target_phrase": candidate.target_phrase,
        "growth_score": candidate.growth_score,
        "final_score": candidate.score,
        "edge_compatibility_score": candidate.edge_compatibility_score,
    }


def _candidate_trace(
    candidate: PhraseCandidate,
    context: PhraseScoringContext,
) -> dict:
    source_phrase, target_phrase = phrase_texts(candidate.pieces)
    return {
        "source_phrase": source_phrase,
        "target_phrase": target_phrase,
        "growth_mode": candidate.growth_mode,
        "piece_ids": [piece.id for piece in candidate.pieces],
        "left_pieces": list(candidate.left_piece_ids),
        "center_pieces": list(candidate.center_piece_ids),
        "right_pieces": list(candidate.right_piece_ids),
        "pieces": [piece.label for piece in candidate.pieces],
        "growth_score": candidate.growth_score,
        "final_score": candidate.score,
        "transition_score": candidate.transition_score,
        "syntax_score": candidate.syntax_score,
        "source_plausibility": candidate.source_plausibility,
        "target_plausibility": candidate.target_plausibility,
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
        "source_need": {
            "label": candidate.source_need_label,
            "confidence": candidate.source_need_confidence,
        },
        "target_need": {
            "label": candidate.target_need_label,
            "confidence": candidate.target_need_confidence,
        },
        "edge_compatibility_score": candidate.edge_compatibility_score,
        "source_edge_compatibility": candidate.source_edge_compatibility,
        "target_edge_compatibility": candidate.target_edge_compatibility,
        "diagnostic_flags": candidate.diagnostic_flags,
        "source_tokens": tokens(source_phrase),
        "target_tokens": tokens(target_phrase),
    }


def _result_key(
    candidate: PhraseCandidate, policy: GeneratePhrasePolicy
) -> tuple:
    if policy.collapse_permutations:
        return tuple(sorted(piece.id for piece in candidate.pieces))
    return _candidate_key(candidate)


def deduplicate_candidates(
    candidates: list[PhraseCandidate],
    *,
    key,
    score_key,
) -> list[PhraseCandidate]:
    deduplicated = {}
    for candidate in candidates:
        candidate_key = key(candidate)
        current = deduplicated.get(candidate_key)
        if current is None or score_key(candidate) > score_key(current):
            deduplicated[candidate_key] = candidate
    return list(deduplicated.values())


def effective_candidate_pool_size(policy: GeneratePhrasePolicy) -> int:
    if policy.candidate_pool_size is not None:
        return max(policy.candidate_pool_size, policy.beam_size)
    return max(policy.beam_size, policy.beam_size * 4)


def prune_candidate_map(
    candidates: dict[tuple[int, ...], PhraseCandidate],
    *,
    limit: int,
) -> dict[tuple[int, ...], PhraseCandidate]:
    if len(candidates) <= limit:
        return candidates
    top = sorted(
        candidates.items(),
        key=lambda item: (item[1].growth_score, item[1].score),
        reverse=True,
    )[:limit]
    return dict(top)


def select_beam(
    candidates: list[PhraseCandidate], policy: GeneratePhrasePolicy
) -> list[PhraseCandidate]:
    if not candidates:
        return []

    return sorted(
        candidates,
        key=lambda item: (item.growth_score, item.score),
        reverse=True,
    )[: policy.beam_size]


def should_keep_partial(
    candidate: PhraseCandidate,
    policy: GeneratePhrasePolicy,
) -> bool:
    return candidate.bilingual_partial_viability >= policy.min_partial_viability


def should_keep_final(
    candidate: PhraseCandidate,
    policy: GeneratePhrasePolicy,
) -> bool:
    if not policy.forbid_low_completion_final:
        return True
    return candidate.bilingual_completion_score >= policy.min_completion_score


def generate_phrase_candidates(
    pieces: list[PhrasePiece],
    policy: GeneratePhrasePolicy,
    plausibility_scorer: PhrasePlausibilityScorer | None = None,
    syntax_annotator: PhraseSyntaxAnnotator | None = None,
    trace: PhraseSearchTrace | None = None,
) -> list[PhraseCandidate]:
    syntax_annotator = syntax_annotator or NullSyntaxAnnotator()
    prelim_pieces = _basic_piece_filter(pieces, policy)
    piece_syntax = syntax_annotator.annotate(prelim_pieces)
    prelim_context = PhraseScoringContext.from_pieces(
        prelim_pieces,
        piece_syntax,
    )
    usable_pieces = filter_pieces(pieces, policy, prelim_context)
    context = PhraseScoringContext.from_pieces(usable_pieces, piece_syntax)
    results: list[PhraseCandidate] = []
    sides = expansion_sides(policy)
    candidate_pool_size = effective_candidate_pool_size(policy)
    logger.info(
        "Loaded pieces: total=%d usable=%d syntax_annotated=%d",
        len(pieces),
        len(usable_pieces),
        len(piece_syntax),
    )
    if not usable_pieces:
        logger.warning("No usable phrase pieces after filtering")
        return []
    if trace is not None:
        trace.record_start(
            pieces_count=len(pieces),
            usable_count=len(usable_pieces),
            syntax_annotated=len(piece_syntax),
            policy=policy,
        )

    if policy.expand_sides == "center":
        seed_pieces = usable_pieces[: policy.center_seed_limit]
        beam = [
            center_seed_candidate(piece, policy, plausibility_scorer, context)
            for piece in seed_pieces
        ]
        beam = select_beam(
            [
                candidate
                for candidate in beam
                if candidate.formal_ok and should_keep_partial(candidate, policy)
            ],
            policy,
        )
        start_size = 2
        if policy.min_pieces <= 1:
            results.extend(
                candidate for candidate in beam if should_keep_final(candidate, policy)
            )
        if trace is not None:
            trace.record_level(
                level=1,
                input_beam_size=len(seed_pieces),
                expanded=beam,
                beam=beam,
                policy=policy,
                context=context,
                expanded_count=len(seed_pieces),
            )
    else:
        beam = [empty_candidate()]
        start_size = 1

    for size in range(start_size, policy.max_pieces + 1):
        input_beam_size = len(beam)
        logger.debug(
            "Phrase search level %d/%d started: beam=%d sides=%s",
            size,
            policy.max_pieces,
            input_beam_size,
            ",".join(sides),
        )
        expanded_by_key: dict[tuple[int, ...], PhraseCandidate] = {}
        expanded_count = 0
        for candidate in beam:
            used_ids = {piece.id for piece in candidate.pieces}
            candidate_sides = (
                sides
                if policy.expand_sides == "center" or candidate.pieces
                else ("right",)
            )
            for piece in usable_pieces:
                if (
                    not policy.allow_repeated_pieces
                    and piece.id in used_ids
                ):
                    continue
                for side in candidate_sides:
                    next_candidate = extend_candidate(
                        candidate,
                        piece,
                        policy,
                        plausibility_scorer,
                        context,
                        side=side,
                    )
                    if (
                        next_candidate.formal_ok
                        and should_keep_partial(next_candidate, policy)
                    ):
                        expanded_count += 1
                        candidate_key = _sequence_key(next_candidate)
                        current = expanded_by_key.get(candidate_key)
                        next_score = (
                            next_candidate.growth_score,
                            next_candidate.score,
                        )
                        current_score = (
                            (current.growth_score, current.score)
                            if current is not None
                            else None
                        )
                        if current_score is None or next_score > current_score:
                            expanded_by_key[candidate_key] = next_candidate
                        if len(expanded_by_key) > candidate_pool_size * 2:
                            expanded_by_key = prune_candidate_map(
                                expanded_by_key,
                                limit=candidate_pool_size,
                            )

        expanded_by_key = prune_candidate_map(
            expanded_by_key,
            limit=candidate_pool_size,
        )
        expanded = list(expanded_by_key.values())
        logger.debug(
            "Phrase search level %d expanded %d candidates; kept %d in pool",
            size,
            expanded_count,
            len(expanded),
        )
        expanded.sort(key=lambda item: item.growth_score, reverse=True)
        log_top_candidates(
            f"Phrase search level {size} growth",
            expanded,
            key=lambda item: item.growth_score,
        )
        beam = select_beam(expanded, policy)
        if trace is not None:
            trace.record_level(
                level=size,
                input_beam_size=input_beam_size,
                expanded=expanded,
                beam=beam,
                policy=policy,
                context=context,
                expanded_count=expanded_count,
            )
        if not beam:
            logger.warning(
                "Phrase search stopped at level %d because the beam is empty",
                size,
            )
            break
        if size >= policy.min_pieces:
            final_beam = [
                candidate
                for candidate in beam
                if should_keep_final(candidate, policy)
            ]
            results.extend(final_beam)
            level_best = max(candidate.score for candidate in beam)
            log_top_candidates(
                f"Phrase search level {size} final",
                final_beam,
                key=lambda item: item.score,
            )
            logger.debug(
                "Phrase search level %d best final score: %.3f",
                size,
                level_best,
            )

    deduplicated: dict[tuple[str, str], PhraseCandidate] = {}
    for candidate in results:
        key = _result_key(candidate, policy)
        current = deduplicated.get(key)
        if current is None or candidate.score > current.score:
            deduplicated[key] = candidate

    ranked = sorted(
        deduplicated.values(),
        key=lambda item: item.score,
        reverse=True,
    )
    final = ranked[: policy.max_results]
    if trace is not None:
        trace.record_final(
            raw_results=len(results),
            deduplicated_count=len(deduplicated),
            returned=final,
            policy=policy,
            context=context,
        )
    logger.info(
        "Search finished: raw=%d deduplicated=%d returned=%d",
        len(results),
        len(deduplicated),
        len(final),
    )
    log_top_candidates(
        "Phrase search final ranking",
        final,
        key=lambda item: item.score,
    )
    return final
