from collections.abc import Iterator
from pathlib import Path


class AppState:
    semordnilaps: dict[str, dict[int, set[str]]] = None
    source_words_filter: set[str] | None = None
    source_words_filter_path: Path | None = None
    target_words_filter: set[str] | None = None
    target_words_filter_path: Path | None = None

    pairs: list[tuple[str, str]]
    pairs_idx: int
    current_source_word: str | None = None
    current_target_word: str | None = None
