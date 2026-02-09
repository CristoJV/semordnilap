import re
from collections.abc import Callable


def should_filter_ngram(ngram: str, filters: set[str]) -> bool:
    ngram = ngram.lower()

    for f in filters:
        f = f.lower()

        pattern = r"\b" + re.escape(f) + r"\b"

        if re.search(pattern, ngram):
            return True
    return False


def filter_semordnilaps_sources(
    semordnilaps: dict[str, dict[int, set[str]]], filters: set[str]
) -> dict[str, dict[int, set[str]]]:

    result: dict[str, dict[int, set[str]]] = {}

    for word, by_length in semordnilaps.items():
        if not should_filter_ngram(word, filters):
            result[word] = by_length

    return result


def filter_semordnilaps_targets(
    semordnilaps: dict[str, dict[int, set[str]]], filters: set[str]
) -> dict[str, dict[int, set[str]]]:

    result: dict[str, dict[int, set[str]]] = {}

    for word, by_length in semordnilaps.items():
        new_by_length: dict[int, set[str]] = {}

        for length, phrases in by_length.items():
            filtered_phrases = {
                p for p in phrases if not should_filter_ngram(p, filters)
            }
            if filtered_phrases:
                new_by_length[length] = filtered_phrases
        if new_by_length:
            result[word] = new_by_length

    return result


def filter_pairs_sources(
    pairs: list[str, str],
    words: set[str],
    on_progress: Callable[[int, int], None] | None = None,
) -> list[tuple[str, str]]:
    kept = []
    total = len(pairs)
    for i, (s, t) in enumerate(pairs, start=1):
        if should_filter_ngram(s, words):
            kept.append((s, t))
        if on_progress and i % 100 == 0:
            on_progress(i, total)

    if on_progress:
        on_progress(total, total)
    return kept


def filter_pairs_targets(
    pairs: list[str, str],
    words: set[str],
    on_progress: Callable[[int, int], None] | None = None,
) -> list[tuple[str, str]]:
    kept = []
    total = len(pairs)
    for i, (s, t) in enumerate(pairs, start=1):
        if should_filter_ngram(t, words):
            kept.append((s, t))
        if on_progress and i % 100 == 0:
            on_progress(i, total)

    if on_progress:
        on_progress(total, total)
    return kept


def filter_pairs_incremental(
    pairs: list[tuple[str, str]],
    words: set[str],
    *,
    axis: str,  # "source" | "target"
):
    total = len(pairs)

    for i, (source, target) in enumerate(pairs, start=1):
        text = source if axis == "source" else target

        if not should_filter_ngram(text, words):
            yield i, total, (source, target)
        else:
            yield i, total, None
