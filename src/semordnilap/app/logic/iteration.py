def build_source_target_pairs(
    semordnilaps: dict[str, dict[int, set[str]]],
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []

    for source_word, by_length in semordnilaps.items():
        for _length, target_words in by_length.items():
            for target_word in target_words:
                pairs.append((source_word, target_word))
    return pairs
