import importlib

from semordnilap.lang import _LANGUAGE_MAP


def get_agreement_rules(language: str):

    if not language:
        raise ValueError("Language must be provided")

    normalized = _LANGUAGE_MAP.get(language.lower())

    if not normalized:
        raise ValueError(f"Unsupported language: {language}")

    module = importlib.import_module(f".{normalized}", package=__name__)

    rules = getattr(module, "AGREEMENT_RULES", None)

    if rules is None:
        raise ValueError(
            f"No AGREEMENT_RULES defined for language: {language}"
        )

    return rules
