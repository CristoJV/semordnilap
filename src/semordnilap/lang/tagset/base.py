from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureSpec:
    slot: int
    values: tuple[str, ...]


@dataclass(frozen=True)
class POSSpec:
    features: dict[str, FeatureSpec]
