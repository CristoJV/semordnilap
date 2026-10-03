"""Logging helpers for the phrase CLI."""

from __future__ import annotations

import logging
import sys

LEVEL_COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[35m",
}
RESET = "\033[0m"


class ColorFormatter(logging.Formatter):
    def __init__(self, *, use_color: bool) -> None:
        super().__init__("%(levelname)-7s %(message)s")
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        original = record.levelname
        if self._use_color:
            color = LEVEL_COLORS.get(original)
            if color is not None:
                record.levelname = f"{color}{original}{RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original


def configure_logging(level: str, color: str) -> None:
    use_color = color == "always" or (
        color == "auto" and sys.stderr.isatty()
    )
    handler = logging.StreamHandler()
    handler.setFormatter(ColorFormatter(use_color=use_color))
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        handlers=[handler],
        force=True,
    )
