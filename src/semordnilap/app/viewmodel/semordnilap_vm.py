import bisect
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from semordnilap.app.logic.filtering import (
    build_inverse_index,
    get_candidate_indices,
    should_filter_ngram_fast,
)
from semordnilap.app.logic.iteration import build_source_target_pairs
from semordnilap.app.logic.loader import load_words_filter


class Axis(str, Enum):
    SOURCE = "source"
    TARGET = "target"


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

    def get_tokens(self) -> list[str]:
        return self._tokens

    def is_empty(self) -> bool:
        return not self._ngram

    def __bool__(self):
        return bool(self._ngram)

    def __repr__(self):
        return f"Ngram(ngram={self._ngram!r}, tokens= {self._tokens!r})"


@dataclass
class AxisState:
    persistent_filter_words: set[str] = field(default_factory=set)
    persistent_filter_path: str | None = None
    candidate_filter_words: set[str] = field(default_factory=set)
    ngram_size: int = 0
    inverse_index: dict = field(default_factory=dict)


class SemordnilapViewModel:
    def __init__(self):
        # Domain
        self.semordnilaps = None
        self.base_pairs: list = []
        self.active_indices: list[int] = []
        self.current_index: int = 0  # index withing active_indices

        self.axis = {Axis.SOURCE: AxisState(), Axis.TARGET: AxisState()}

    # -------------------------- Data loading ------------------------ #

    def set_semordnilaps(self, data):
        self.semordnilaps = data

    def semordnilaps_loaded(self):
        return bool(self.semordnilaps)

    def load_pairs(self):
        if not self.semordnilaps:
            raise ValueError("Semordnilaps nod loaded yet")

        self.base_pairs = build_source_target_pairs(self.semordnilaps)
        self.active_indices = list(range(len(self.base_pairs)))
        self.axis[Axis.SOURCE].inverse_index = build_inverse_index(
            self.base_pairs, axis=Axis.SOURCE
        )
        self.axis[Axis.TARGET].inverse_index = build_inverse_index(
            self.base_pairs, axis=Axis.TARGET
        )
        self.reset_cursor()

    def pairs_loaded(self):
        return bool(self.base_pairs)

    def len_base_pairs(self):
        return len(self.base_pairs)

    # -------------------------- Filtering --------------------------- #

    def set_ngram_size(self, ngram_size, axis: Axis):
        self.axis[axis].ngram_size = ngram_size

    def get_ngram_size(self, axis: Axis):
        return self.axis[axis].ngram_size

    def set_persistent_filter_words(
        self,
        source_persistent_filter_words: set[str],
        target_persistent_filter_words: set[str],
    ):
        self.axis[Axis.SOURCE].persistent_filter_words = (
            source_persistent_filter_words or set()
        )
        self.axis[Axis.TARGET].persistent_filter_words = (
            target_persistent_filter_words or set()
        )

    def get_pairs_view(self):
        return [self.base_pairs[i] for i in self.active_indices]

    def filter_by_ngram_size(self, axis: Axis):
        n = self.axis[axis].ngram_size
        if n <= 0:
            return

        removed = set()

        for idx in self.active_indices:
            source, target = self.base_pairs[idx]
            text = source if axis == Axis.SOURCE else target
            if len(text.split()) != n:
                removed.add(idx)
        self.active_indices = [
            idx for idx in self.active_indices if idx not in removed
        ]

    def _compute_removed_indices(self, words: set[str], axis: Axis):
        index = self.axis[axis].inverse_index
        candidates = get_candidate_indices(index, words)
        to_check = [idx for idx in self.active_indices if idx in candidates]
        removed = set()
        for idx in to_check:
            source, target = self.base_pairs[idx]
            text = source if axis == Axis.SOURCE else target

            if should_filter_ngram_fast(text, words):
                removed.add(idx)
        return removed

    def filter_words(self, words: set[str], axis: Axis):
        if not words or not self.active_indices:
            return

        current_base_index = self.active_indices[self.current_index]
        removed = self._compute_removed_indices(words, axis)
        self.active_indices = [
            idx for idx in self.active_indices if idx not in removed
        ]
        self._reposition_cursor(current_base_index)

    def _reposition_cursor(self, previous_base_index: int):
        if not self.active_indices:
            self.current_index = 0
            return

        if previous_base_index in self.active_indices:
            self.current_index = self.active_indices.index(previous_base_index)
            return

        pos = bisect.bisect_right(self.active_indices, previous_base_index)
        if pos < len(self.active_indices):
            self.set_current_index(pos)
        else:
            self.set_current_index(len(self.active_indices) - 1)

    def apply_all_filters(self):
        # Reset indices
        self.active_indices = list(range(len(self.base_pairs)))

        for axis in Axis:
            # Ngram count filter
            self.filter_by_ngram_size(axis)
            # Word-based filtering
            self.filter_words(self.axis[axis].persistent_filter_words, axis)

    # Cursor / Navigation
    def get_active_pair(self, idx):
        if idx < 0 or idx >= len(self.active_indices):
            return None
        else:
            return self.base_pairs[self.active_indices[idx]]

    def len_active_pairs(self):
        return len(self.active_indices)

    def reset_cursor(self):
        self.set_current_index(0)

    def set_current_index(self, index: int):
        if not self.active_indices:
            self.current_index = 0
        elif index < 0:
            self.current_index = 0
        elif index >= len(self.active_indices):
            self.current_index = len(self.active_indices) - 1
        else:
            self.current_index = index

    def get_current_pair(self):
        return self.get_active_pair(self.current_index)

    def get_current_ngram(self, axis: Axis) -> Ngram:
        pair = self.get_current_pair()
        if pair is None:
            return Ngram()
        source, target = pair
        value = source if axis == Axis.SOURCE else target
        return Ngram(value)

    def next_pair(self):
        self.set_current_index(self.current_index + 1)

    def load_filter_words(self, path: str, axis: Axis):
        words = load_words_filter(path)

        self.axis[axis].persistent_filter_words = words
        self.axis[axis].persistent_filter_path = path

    def persistent_filter_words_loaded(self, axis: Axis):
        return self.axis[axis].persistent_filter_path is not None

    def clear_candidate_filter_words(self, axis: Axis):
        self.axis[axis].candidate_filter_words = set()

    def add_candidate_filter_word(self, word: str, axis: Axis):
        self.axis[axis].candidate_filter_words.add(word)

    def get_candidate_filter_words(self, axis: Axis):
        return sorted(self.axis[axis].candidate_filter_words)

    def get_word_filter(self, axis: Axis):
        return self.axis[axis].persistent_filter_words, self.axis[
            axis
        ].persistent_filter_path
