"""Reusable iterable helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


def sliding_windows(items: Sequence[T], max_size: int):
    for size in range(1, max_size + 1):
        for i in range(0, len(items) - size + 1):
            yield tuple(items[i : i + size])
