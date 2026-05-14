"""Phrase generation application layer."""

from semordnilap.phrases.application.commands import GeneratePhrasesCommand
from semordnilap.phrases.application.services import run_generation

__all__ = ["GeneratePhrasesCommand", "run_generation"]

