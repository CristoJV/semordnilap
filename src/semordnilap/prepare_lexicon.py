import argparse
import json
import unicodedata
from collections import defaultdict


def lexicon_to_words(lexicon: dict) -> dict:
    """
    Convert a lexicon dictionary into {"words": [list of keys]}.
    """
    return list(lexicon.keys())


def remove_hyphenated_words(
    words: list[str], removed: dict[str, list[str]]
) -> list[str]:
    """
    Remove words containing hyphens.
    """
    out = []
    for w in words:
        if "-" in w:
            removed["hyphenated"].append(w)
        else:
            out.append(w)
    return out


def remove_dotted_words(
    words: list[str], removed: dict[str, list[str]]
) -> list[str]:
    """
    Remove words containing dots (e.g. 'q. d. g.').
    """
    out = []
    for w in words:
        if "." in w:
            removed["dotted"].append(w)
        else:
            out.append(w)
    return out


def remove_non_alphanumeric_words(
    words: list[str], removed: dict[str, list[str]]
) -> list[str]:
    """
    Remove words containing non-letter / non-digit / non-space characters
    (e.g. ℆, @, †, §).
    """
    out = []
    for w in words:
        if all(unicodedata.category(c).startswith(("L", "N", "Z")) for c in w):
            out.append(w)
        else:
            removed["unicode_symbol"].append(w)
    return out


def sort_by_ngram_count_and_length(words: list[str]) -> list[str]:
    """
    Sort words by number of n-grams (space-separated tokens).
    """
    return sorted(words, key=lambda w: (len(w.split()), len(w)))


def main():
    parser = argparse.ArgumentParser(
        description="Extract list of words from lexicon"
    )
    parser.add_argument("-l", "--lexicon", required=True)
    parser.add_argument("-o", "--out", required=True)

    args = parser.parse_args()

    with open(args.lexicon, "r", encoding="utf-8") as f:
        lexicon = json.load(f)

    removed: dict[str, list[str]] = defaultdict(list)
    words = lexicon_to_words(lexicon)
    words = remove_hyphenated_words(words, removed)
    words = remove_dotted_words(words, removed)
    words = remove_non_alphanumeric_words(words, removed)
    words = sort_by_ngram_count_and_length(words)

    with open(args.out, "w", encoding="utf-8") as f:
        for word in words:
            f.write(f"{word}\n")

    with open(f"{args.out}.removed.json", "w", encoding="utf-8") as f:
        json.dump(removed, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
