import importlib

from semordnilap.lang import _LANGUAGE_MAP


def get_pos_feature_slots(language: str):

    if not language:
        raise ValueError("Language must be provided")

    normalized = _LANGUAGE_MAP.get(language.lower())

    if not normalized:
        raise ValueError(f"Unsupported language: {language}")

    module = importlib.import_module(
        f".{normalized}",
        package=__name__,
    )

    slots = getattr(module, "POS_FEATURE_SLOTS", None)

    if slots is None:
        raise ValueError(
            f"No POS_FEATURE_SLOTS defined for language: {language}"
        )

    return slots
