from collections.abc import Iterator


def iter_source_target_pairs(
    semordnilaps: dict[str, dict[int, str]],
) -> Iterator[tuple[str, str]]:
    for source_word, by_length in semordnilaps.items():
        for _length, target_words in by_length.items():
            for target_word in target_words:
                yield source_word, target_word
