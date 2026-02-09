from collections.abc import Iterable
from pathlib import Path


class Ngram:
    def __init__(self, value: str | Iterable[str] | None = None):
        self._ngram: str | None = None
        self._tokens: list[str] = []

        if value is not None:
            self.set(value)

    def set(self, value: str | Iterable[str]):
        if isinstance(value, str):
            self._ngram = value
            self._tokens = value.split()

        elif isinstance(value, Iterable):
            tokens = list(value)
            if not all(isinstance(t, str) for t in tokens):
                raise TypeError("All tokens must be strings")

            self._ngram = " ".join(tokens)
            self._tokens = tokens
        else:
            raise TypeError("Ngram value must be str or Iterable[str]")

    def get_ngram(self) -> str:
        return self._ngram

    def get_tokens(self) -> str:
        return self._tokens

    def is_empty(self) -> bool:
        return not self._ngram

    def __bool__(self):
        return not self._ngram

    def __repr__(self):
        return f"Ngram(ngram={self._ngram!r}, tokens= {self._tokens!r})"


class AppState:
    semordnilaps: dict[str, dict[int, set[str]]] = None
    source_words_filter_path: Path | None = None
    target_words_filter_path: Path | None = None

    source_words_filter: set[str] | None = None
    target_words_filter: set[str] | None = None
    ngram_size_filter: int | None = None

    base_pairs: list[tuple[str, str]] | None = None
    base_pairs_active_indices: set[int] | None = None
    pairs_view: list[tuple[str, str]] | None = None

    source_reverse_index: dict[str, set[int]] | None = None
    target_reverse_index: dict[str, set[int]] | None = None

    current_source_ngram: Ngram = Ngram()
    current_target_ngram: Ngram = Ngram()
    current_pair_index: int = 0
