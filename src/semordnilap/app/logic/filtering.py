from collections import defaultdict


def build_inverse_index(
    pairs: list[tuple[str, str]],
    axis: str,  # "source" | "target"
) -> dict[str, set[int]]:
    index = defaultdict(set)

    for i, (source, target) in enumerate(pairs):
        text = source if axis == "source" else target
        for token in text.split():
            index[token].add(i)
    return index


def get_candidate_indices(
    index: dict[str, set[int]],
    filters: set[str],
) -> set[int]:
    candidates = set()
    for f in filters:
        for token in f.split():
            candidates |= index.get(token, set())
    return candidates


def should_filter_ngram_fast(ngram: str, filters: set[str]) -> bool:
    tokens = ngram.split()
    n = len(tokens)

    for size in range(1, n + 1):
        for i in range(n - size + 1):
            if " ".join(tokens[i : i + size]) in filters:
                return True
    return False
