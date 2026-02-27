from pathlib import Path


class AppState:
    semordnilaps: dict[str, dict[int, set[str]]] = None
    source_words_filter_path: Path | None = None
    target_words_filter_path: Path | None = None

    source_words_filter: set[str] | None = None
    target_words_filter: set[str] | None = None
    selected_source_words_filter: set[str] = set()
    seletect_target_words_filter: set[str] = set()
    source_ngram_size_filter: int = 0
    target_ngram_size_filter: int = 0

    base_pairs: list[tuple[str, str]] | None = None
    base_pairs_active_indices: set[int] | None = None
    pairs_view: list[tuple[str, str]] | None = None

    source_reverse_index: dict[str, set[int]] | None = None
    target_reverse_index: dict[str, set[int]] | None = None

    current_source_ngram: Ngram = Ngram()
    current_target_ngram: Ngram = Ngram()
    current_pair_index: int = 0
