from collections.abc import Iterator


class AppState:
    semordnilaps: dict[str, dict[int, set[str]]] = None
    source_words_filter: set[str] | None = None
    target_words_filter: set[str] | None = None
    iterator: Iterator[tuple[str, str]]
    current_source_word: str | None = None
    current_target_word: str | None = None
