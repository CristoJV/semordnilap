"""OmegaConf configuration support for phrase generation."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from omegaconf import DictConfig, OmegaConf


DEFAULT_GENERATION_CONFIG: dict[str, Any] = {
    "input": None,
    "out": None,
    "language": {
        "source": "es",
        "target": "pt",
    },
    "search": {
        "min_source_count": 100,
        "min_target_count": 100,
        "min_pair_score": 0.0,
        "max_source_n": 3,
        "max_target_n": 3,
        "piece_limit": 1000,
        "min_pieces": 2,
        "max_pieces": 4,
        "beam_size": 1000,
        "candidate_pool_size": None,
        "max_results": 500,
        "expand_sides": "right",
        "center_seed_limit": 500,
        "allow_repeated_pieces": False,
        "keep_permutations": False,
    },
    "scoring": {
        "pair_weight": 1.0,
        "fluency_weight": None,
        "syntax_weight": 1.0,
        "morphology_weight": 0.0,
        "partial_viability_weight": 1.0,
        "completion_weight": 1.0,
        "dead_end_weight": 1.0,
        "boundary_weight": 1.0,
        "edge_compatibility_weight": 1.0,
        "min_completion_score": 0.0,
        "min_partial_viability": float("-inf"),
        "forbid_low_completion_final": True,
        "repeat_penalty": 8.0,
        "complete_bonus": 2.0,
        "morphology_agreement_features": ["Gender", "Number"],
    },
    "models": {
        "source_lm": None,
        "target_lm": None,
        "source_spacy_model": None,
        "target_spacy_model": None,
        "source_boundary_model": None,
        "target_boundary_model": None,
        "source_transition_model": None,
        "target_transition_model": None,
        "disable_syntax": False,
    },
    "output": {
        "trace_out": None,
        "trace_top_n": 25,
    },
    "logging": {
        "level": "info",
        "color": "auto",
    },
}


CLI_CONFIG_PATHS = {
    "input": "input",
    "out": "out",
    "source_lang": "language.source",
    "target_lang": "language.target",
    "min_source_count": "search.min_source_count",
    "min_target_count": "search.min_target_count",
    "min_pair_score": "search.min_pair_score",
    "max_source_n": "search.max_source_n",
    "max_target_n": "search.max_target_n",
    "piece_limit": "search.piece_limit",
    "min_pieces": "search.min_pieces",
    "max_pieces": "search.max_pieces",
    "beam_size": "search.beam_size",
    "candidate_pool_size": "search.candidate_pool_size",
    "max_results": "search.max_results",
    "expand_sides": "search.expand_sides",
    "center_seed_limit": "search.center_seed_limit",
    "allow_repeated_pieces": "search.allow_repeated_pieces",
    "keep_permutations": "search.keep_permutations",
    "pair_weight": "scoring.pair_weight",
    "fluency_weight": "scoring.fluency_weight",
    "syntax_weight": "scoring.syntax_weight",
    "morphology_weight": "scoring.morphology_weight",
    "partial_viability_weight": "scoring.partial_viability_weight",
    "completion_weight": "scoring.completion_weight",
    "dead_end_weight": "scoring.dead_end_weight",
    "boundary_weight": "scoring.boundary_weight",
    "edge_compatibility_weight": "scoring.edge_compatibility_weight",
    "min_completion_score": "scoring.min_completion_score",
    "min_partial_viability": "scoring.min_partial_viability",
    "forbid_low_completion_final": "scoring.forbid_low_completion_final",
    "repeat_penalty": "scoring.repeat_penalty",
    "complete_bonus": "scoring.complete_bonus",
    "morphology_agreement_features": (
        "scoring.morphology_agreement_features"
    ),
    "source_lm": "models.source_lm",
    "target_lm": "models.target_lm",
    "source_spacy_model": "models.source_spacy_model",
    "target_spacy_model": "models.target_spacy_model",
    "source_boundary_model": "models.source_boundary_model",
    "target_boundary_model": "models.target_boundary_model",
    "source_transition_model": "models.source_transition_model",
    "target_transition_model": "models.target_transition_model",
    "disable_syntax": "models.disable_syntax",
    "trace_out": "output.trace_out",
    "trace_top_n": "output.trace_top_n",
    "log_level": "logging.level",
    "log_color": "logging.color",
}


def resolve_generation_config(args: argparse.Namespace) -> DictConfig:
    config = OmegaConf.create(DEFAULT_GENERATION_CONFIG)
    config_path = getattr(args, "config", None)
    if config_path is not None:
        config = OmegaConf.merge(config, OmegaConf.load(config_path))

    for arg_name, config_path in CLI_CONFIG_PATHS.items():
        if not hasattr(args, arg_name):
            continue
        value = getattr(args, arg_name)
        if value is None:
            continue
        OmegaConf.update(
            config,
            config_path,
            _normalise_cli_value(arg_name, value),
            merge=True,
        )
    return config


def optional_path(value: Any) -> Path | None:
    if value is None or value == "":
        return None
    return Path(str(value))


def required_path(config: DictConfig, key: str) -> Path:
    value = OmegaConf.select(config, key)
    if value is None or value == "":
        raise ValueError(f"'{key}' must be set in YAML or via CLI")
    return Path(str(value))


def string_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return tuple(str(item).strip() for item in value if str(item).strip())


def _normalise_cli_value(arg_name: str, value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if arg_name == "morphology_agreement_features":
        return list(string_list(value))
    return value
