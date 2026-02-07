class AppState:
    semordnilaps: dict[str, dict[int, set[str]]] = None
    source_words_filter: set[str] | None = None
    target_words_filter: set[str] | None = None
