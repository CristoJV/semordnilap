import re


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
