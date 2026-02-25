import unicodedata
from collections import defaultdict


def apply_rules(word, rules, removed, **kwargs):

    passed = True

    for rule in rules:
        if not rule(word, removed, **kwargs):
            passed = False

    return passed


def apply_filters(lexicon, form_rules, **kwargs):

    valid: list[str] = []
    removed: dict[str, list[str]] = defaultdict(list)

    for word in lexicon:
        form_ok = apply_rules(word, form_rules, removed)

        if form_ok:
            valid.append(word)

    return valid, removed


# ============================================================
# FORM RULES
# ============================================================


def reject_hyphenated(word: str, removed: dict[str, list[str]], **_) -> bool:
    if "-" in word:
        removed["hyphenated"].append(word)
        return False
    return True


def reject_dotted(word: str, removed: dict[str, list[str]], **_) -> bool:
    if "." in word:
        removed["dotted"].append(word)
        return False
    return True


def reject_non_alphanumeric(
    word: str, removed: dict[str, list[str]], **_
) -> bool:
    """
    Reject tokens containing symbols or strange Unicode categories.

    Allowed:
        - Letters (L*)
        - Numbers (N*)
        - Spaces (Z*)
    """
    if all(unicodedata.category(c).startswith(("L", "N", "Z")) for c in word):
        return True

    removed["unicode_symbol"].append(word)
    return False
