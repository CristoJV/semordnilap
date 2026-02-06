import argparse
import json


def lexicon_to_words(lexicon: dict) -> dict:
    """
    Convert a lexicon dictionary into {"words": [list of keys]}.
    """
    return list(lexicon.keys())


def remove_hyphenated_words(words: list[str]) -> list[str]:
    """
    Remove words containing hyphens.
    """
    return [word for word in words if "-" not in word]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract list of words from lexicon"
    )
    parser.add_argument("-l", "--lexicon", required=True)
    parser.add_argument("-o", "--out", required=True)

    args = parser.parse_args()

    with open(args.lexicon, "r", encoding="utf-8") as f:
        lexicon = json.load(f)
    words = lexicon_to_words(lexicon)
    words = remove_hyphenated_words(words)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"words": words}, f, indent=2, ensure_ascii=False)
