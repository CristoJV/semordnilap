"""Domain services for phrase generation."""

from __future__ import annotations

import math

from semordnilap.phrases.domain.model import (
    GeneratePhrasePolicy,
    PhraseCandidate,
    PhrasePlausibilityScorer,
    PhrasePiece,
)

try:
    from wordfreq import zipf_frequency
except ImportError:  # pragma: no cover - optional dependency fallback
    zipf_frequency = None

WEAK_FINAL_TOKENS = {
    "es": {
        "a",
        "al",
        "con",
        "contra",
        "de",
        "del",
        "desde",
        "durante",
        "e",
        "el",
        "en",
        "entre",
        "hacia",
        "hasta",
        "la",
        "las",
        "le",
        "lo",
        "los",
        "me",
        "o",
        "para",
        "por",
        "que",
        "se",
        "sin",
        "sobre",
        "su",
        "te",
        "un",
        "una",
        "y",
    },
    "pt": {
        "a",
        "ao",
        "as",
        "com",
        "da",
        "das",
        "de",
        "do",
        "dos",
        "e",
        "em",
        "na",
        "nas",
        "no",
        "nos",
        "o",
        "os",
        "ou",
        "para",
        "por",
        "que",
        "se",
        "um",
        "uma",
    },
}

WEAK_INITIAL_TOKENS = {
    "es": {"al", "con", "de", "del", "e", "en", "o", "para", "por", "y"},
    "pt": {"ao", "com", "da", "de", "do", "e", "em", "ou", "para", "por"},
}

FUNCTION_TOKENS = {
    lang: weak_final | WEAK_INITIAL_TOKENS.get(lang, set())
    for lang, weak_final in WEAK_FINAL_TOKENS.items()
}


def piece_quality(piece: PhrasePiece) -> float:
    return (
        piece.pair_score
        + math.log(piece.source_count + 1)
        + math.log(piece.target_count + 1)
    )


def filter_pieces(
    pieces: list[PhrasePiece], policy: GeneratePhrasePolicy
) -> list[PhrasePiece]:
    filtered = [
        piece
        for piece in pieces
        if piece.formal_ok
        and piece.source_count >= policy.min_source_count
        and piece.target_count >= policy.min_target_count
        and piece.pair_score >= policy.min_pair_score
        and piece.source_n <= policy.max_source_n
        and piece.target_n <= policy.max_target_n
    ]
    filtered.sort(key=piece_quality, reverse=True)
    return filtered[: policy.piece_limit]


def _tokens(text: str) -> list[str]:
    return [token.casefold() for token in text.split() if token.strip()]


def _wordfreq_score(text: str, lang: str) -> float:
    if zipf_frequency is None:
        return 0.0
    tokens = _tokens(text)
    if not tokens:
        return 0.0
    return sum(zipf_frequency(token, lang) for token in tokens) / len(tokens)


def edge_penalty(pieces: tuple[PhrasePiece, ...], policy: GeneratePhrasePolicy) -> float:
    if not pieces:
        return 0.0

    source_tokens = _tokens(" ".join(piece.source_text for piece in pieces))
    target_tokens = _tokens(
        " ".join(piece.target_text for piece in reversed(pieces))
    )
    penalty = 0.0
    if source_tokens:
        penalty += _boundary_penalty(
            source_tokens,
            pieces[0].source_lang or "es",
            policy,
        )
    if target_tokens:
        penalty += _boundary_penalty(
            target_tokens,
            pieces[-1].target_lang or "pt",
            policy,
        )
    return penalty


def _boundary_penalty(
    tokens: list[str], lang: str, policy: GeneratePhrasePolicy
) -> float:
    penalty = 0.0
    if tokens[0] in WEAK_INITIAL_TOKENS.get(lang, set()):
        penalty += policy.edge_penalty * 0.5
    if tokens[-1] in WEAK_FINAL_TOKENS.get(lang, set()):
        penalty += policy.edge_penalty
    return penalty


def reciprocal_penalty(
    pieces: tuple[PhrasePiece, ...], policy: GeneratePhrasePolicy
) -> float:
    penalty = 0.0
    seen = set()
    for piece in pieces:
        key = (piece.source_norm_key, piece.target_norm_key)
        reverse_key = (piece.target_norm_key, piece.source_norm_key)
        if reverse_key in seen:
            penalty += policy.reciprocal_penalty
        seen.add(key)
    return penalty


def fragment_penalty(
    pieces: tuple[PhrasePiece, ...], policy: GeneratePhrasePolicy
) -> float:
    penalty = 0.0
    for piece in pieces:
        penalty += _piece_fragment_penalty(
            piece.source_text,
            piece.source_lang or "es",
            policy,
        )
        penalty += _piece_fragment_penalty(
            piece.target_text,
            piece.target_lang or "pt",
            policy,
        )
    return penalty


def _piece_fragment_penalty(
    text: str, lang: str, policy: GeneratePhrasePolicy
) -> float:
    tokens = _tokens(text)
    if not tokens:
        return policy.fragment_penalty

    penalty = 0.0
    function_tokens = FUNCTION_TOKENS.get(lang, set())
    if all(token in function_tokens for token in tokens):
        penalty += policy.fragment_penalty
    if tokens[-1] in WEAK_FINAL_TOKENS.get(lang, set()):
        penalty += policy.fragment_penalty * 0.5
    if tokens[0] in WEAK_INITIAL_TOKENS.get(lang, set()):
        penalty += policy.fragment_penalty * 0.25
    return penalty


def _phrase_langs(pieces: tuple[PhrasePiece, ...]) -> tuple[str, str]:
    source_lang = pieces[0].source_lang or "es"
    target_lang = pieces[0].target_lang or "pt"
    return source_lang, target_lang


def _phrase_texts(pieces: tuple[PhrasePiece, ...]) -> tuple[str, str]:
    source_phrase = " ".join(piece.source_text for piece in pieces)
    target_phrase = " ".join(piece.target_text for piece in reversed(pieces))
    return source_phrase, target_phrase


def score_plausibility(
    pieces: tuple[PhrasePiece, ...],
    scorer: PhrasePlausibilityScorer | None,
) -> tuple[float, float]:
    if scorer is None:
        return 0.0, 0.0

    source_phrase, target_phrase = _phrase_texts(pieces)
    source_lang, target_lang = _phrase_langs(pieces)
    return (
        scorer.score(source_phrase, source_lang),
        scorer.score(target_phrase, target_lang),
    )


def score_candidate(
    pieces: tuple[PhrasePiece, ...],
    policy: GeneratePhrasePolicy,
    source_plausibility: float = 0.0,
    target_plausibility: float = 0.0,
) -> float:
    size = len(pieces)
    pair_score = sum(piece.pair_score for piece in pieces) / size
    source_count_score = sum(
        math.log(piece.source_count + 1) for piece in pieces
    ) / size
    target_count_score = sum(
        math.log(piece.target_count + 1) for piece in pieces
    ) / size
    min_count_score = min(
        math.log(piece.source_count + 1)
        + math.log(piece.target_count + 1)
        for piece in pieces
    )
    source_phrase, target_phrase = _phrase_texts(pieces)
    source_lang, target_lang = _phrase_langs(pieces)
    lexical_score = policy.wordfreq_weight * (
        _wordfreq_score(source_phrase, source_lang)
        + _wordfreq_score(target_phrase, target_lang)
    )
    repeated = len(pieces) - len({piece.id for piece in pieces})
    length_penalty = 0.75 * max(size - 2, 0)
    repeat_penalty = 10.0 * repeated
    score = (
        pair_score
        + source_count_score
        + target_count_score
        + 0.25 * min_count_score
        + lexical_score
        + policy.plausibility_weight
        * (source_plausibility + target_plausibility)
        - length_penalty
        - repeat_penalty
        - reciprocal_penalty(pieces, policy)
        - edge_penalty(pieces, policy)
        - fragment_penalty(pieces, policy)
    )
    return round(score, 6)


def extend_candidate(
    candidate: PhraseCandidate,
    piece: PhrasePiece,
    policy: GeneratePhrasePolicy,
    plausibility_scorer: PhrasePlausibilityScorer | None,
) -> PhraseCandidate:
    pieces = (*candidate.pieces, piece)
    source_plausibility, target_plausibility = score_plausibility(
        pieces,
        plausibility_scorer,
    )
    return PhraseCandidate(
        pieces=pieces,
        score=score_candidate(
            pieces,
            policy,
            source_plausibility=source_plausibility,
            target_plausibility=target_plausibility,
        ),
        source_plausibility=source_plausibility,
        target_plausibility=target_plausibility,
    )


def empty_candidate() -> PhraseCandidate:
    return PhraseCandidate(pieces=(), score=0.0)


def _candidate_key(candidate: PhraseCandidate) -> tuple[str, str]:
    return candidate.source_norm_key, candidate.target_norm_key


def _result_key(
    candidate: PhraseCandidate, policy: GeneratePhrasePolicy
) -> tuple:
    if policy.collapse_permutations:
        return tuple(sorted(piece.id for piece in candidate.pieces))
    return _candidate_key(candidate)


def generate_phrase_candidates(
    pieces: list[PhrasePiece],
    policy: GeneratePhrasePolicy,
    plausibility_scorer: PhrasePlausibilityScorer | None = None,
) -> list[PhraseCandidate]:
    usable_pieces = filter_pieces(pieces, policy)
    beam = [empty_candidate()]
    results: list[PhraseCandidate] = []

    for size in range(1, policy.max_pieces + 1):
        expanded: list[PhraseCandidate] = []
        for candidate in beam:
            used_ids = {piece.id for piece in candidate.pieces}
            for piece in usable_pieces:
                if (
                    not policy.allow_repeated_pieces
                    and piece.id in used_ids
                ):
                    continue
                next_candidate = extend_candidate(
                    candidate,
                    piece,
                    policy,
                    plausibility_scorer,
                )
                if next_candidate.formal_ok:
                    expanded.append(next_candidate)

        expanded.sort(key=lambda item: item.score, reverse=True)
        beam = expanded[: policy.beam_size]
        if size >= policy.min_pieces:
            results.extend(beam)

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
    return ranked[: policy.max_results]
