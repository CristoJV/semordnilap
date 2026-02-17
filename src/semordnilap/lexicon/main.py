import argparse
import json
import unicodedata
from collections import defaultdict

from semordnilap.tagging.freeling import freeling_pos_to_human


def extract_words(dictionary: dict) -> list[str]:
    return list(dictionary.keys())


# ------------------------- Form filters ------------------------------#


def reject_hyphenated(word, removed, **_):
    if "-" in word:
        removed["hyphenated"].append(word)
        return False
    return True


def reject_dotted(word, removed, **_):
    if "." in word:
        removed["dotted"].append(word)
        return False
    return True


def reject_non_alphanumeric(word, removed, **_):
    if all(unicodedata.category(c).startswith(("L", "N", "Z")) for c in word):
        return True

    removed["unicode_symbol"].append(word)
    return False


def check_original_exists(word, removed, lexicon, **_):
    if not lexicon[word].get("original"):
        removed["missing_original"].append(word)
        return False
    return True


def check_estimate_exists(word, removed, lexicon, **_):
    if not lexicon[word].get("estimated"):
        removed["missing_estimate"].append(word)
        return False
    return True


def rule_pos_consistency(word, removed, lexicon, **_):

    info = lexicon.get(word, {})

    original = info.get("original", {})
    estimated = info.get("estimated", {})

    original_pos_list = original.get("pos")
    estimated_pos = estimated.get("pos")

    if not original_pos_list:
        removed["missing_original_pos"].append(word)
        return False

    if "forma" in original_pos_list:
        return True

    if not estimated_pos:
        removed["missing_estimated_pos"].append(word)
        return False

    human_estimated = freeling_pos_to_human(estimated_pos)

    if not human_estimated:
        removed["invalid_estimated_pos"].append(word)
        return False

    if human_estimated not in original_pos_list:
        removed["pos_mismatch"].append(word)
        return False

    return True


def rule_confidence_threshold(
    word, removed, lexicon, confidence_threshold, **_
):

    info = lexicon.get(word, {})
    estimated = info.get("estimated", {})

    conf = estimated.get("conf")

    if conf is None:
        removed["missing_confidence"].append(word)
        return False

    if confidence_threshold is not None and conf < confidence_threshold:
        removed[f"low_confidence_{confidence_threshold:.2f}"].append(word)
        return False

    return True


def sort_by_ngram_count_and_length(words: list[str]) -> list[str]:
    """
    Sort words by number of n-grams (space-separated tokens).
    """
    return sorted(words, key=lambda w: (len(w.split()), len(w)))


def apply_rules(word, rules, removed, **kwargs):

    passed = True

    for rule in rules:
        if not rule(word, removed, **kwargs):
            passed = False

    return passed


def main():
    parser = argparse.ArgumentParser(
        description="Extract list of words (lexicon) from dict"
    )
    parser.add_argument("-d", "--dict", required=True)
    parser.add_argument("-o", "--out", required=True)
    parser.add_argument("-th", "--threshold", required=False, type=float)

    args = parser.parse_args()

    with open(args.dict, "r", encoding="utf-8") as f:
        lexicon = json.load(f)

    filtered = []
    removed: dict[str, list[str]] = defaultdict(list)

    form_rules = [
        reject_hyphenated,
        reject_dotted,
        reject_non_alphanumeric,
    ]

    linguistic_rules = [
        rule_pos_consistency,
        rule_confidence_threshold,
    ]

    for word in lexicon:
        form_ok = apply_rules(word, form_rules, removed)
        linguistic_ok = apply_rules(
            word,
            linguistic_rules,
            removed,
            lexicon=lexicon,
            confidence_threshold=args.threshold,
        )

        if form_ok and linguistic_ok:
            filtered.append(word)

    filtered = sort_by_ngram_count_and_length(filtered)

    removed_set = set()
    for key, values in removed.items():
        values_set = set(values)
        removed_set = removed_set | values_set

    with open(args.out, "w", encoding="utf-8") as f:
        for word in filtered:
            f.write(f"{word}\n")

    with open(f"{args.out}.removed.json", "w", encoding="utf-8") as f:
        json.dump(removed, f, indent=2, ensure_ascii=False)

    with open(f"{args.out}.automatic.filter", "w", encoding="utf-8") as f:
        for r in removed_set:
            f.write(f"{r}\n")

    total = len(lexicon)
    print(
        f"Total: {len(filtered)} + {len(removed_set)} = {len(filtered) + len(removed_set)}/{total}"
    )
    for key, values in removed.items():
        print(f"{key}: {len(values)}/{total}")


if __name__ == "__main__":
    main()
