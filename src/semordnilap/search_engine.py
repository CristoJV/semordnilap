# %%
import argparse
import json
import logging
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from tqdm import tqdm
from wordfreq import zipf_frequency

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def load_lexicon(json_filepath: Path) -> object:
    with open(json_filepath, "r", encoding="utf-8") as f:
        lexicon = json.load(f)
        return lexicon["words"]
    return None


def filter_common_words(
    words: list[str], language: str = "es", threshold: float = 3.0
):
    return [w for w in words if zipf_frequency(w, language) >= threshold]


def normalize_word(word: str):
    REMOVE_UNICODE_MARKS = set(
        [
            "\u0301",  # acute  ´
            "\u0300",  # grave  `
            "\u0302",  # circumflex ^
            "\u0308",  # diaeresis ¨
        ]
    )
    word = unicodedata.normalize("NFD", word)
    word = "".join(c for c in word if c not in REMOVE_UNICODE_MARKS)
    return unicodedata.normalize("NFC", word)


def decompositions_candidates(
    norm_target: str,
    norm_words: set[str],
    norm_to_origins: dict[str, set],
):
    solutions: list[list[str]] = []
    candidates: list[tuple[int, list[str]]] = [(0, [])]

    while candidates:
        i, phrase = candidates.pop()
        if i == len(norm_target):
            solutions.append(phrase)
            continue
        for j in range(i + 1, len(norm_target) + 1):
            frag = norm_target[i:j]
            if frag in norm_words:
                for orig in norm_to_origins[frag]:
                    candidates.append((j, phrase + [orig]))

    return solutions


def find_semordnilap(
    words: list[str], threshold: float = 3.0
) -> dict[str, set[str]]:
    norm_cache = {}
    norm_to_origins = defaultdict(set)

    for w in words:
        nw = norm_cache.setdefault(w, normalize_word(w))
        norm_to_origins[nw].add(w)
    norm_words = set(norm_to_origins.keys())

    semordnilaps = defaultdict(set)
    palindromes = defaultdict(set)

    for query_word in tqdm(words, desc="Analyzing words", total=len(words)):
        norm_word = norm_cache[query_word]
        r_query_word = norm_word[::-1]

        solutions = decompositions_candidates(
            r_query_word, norm_words, norm_to_origins
        )

        for sol in solutions:
            if zipf_frequency(" ".join(sol), "es") >= threshold:
                semordnilaps[query_word].add(" ".join(sol))

    return semordnilaps, palindromes


def save_semordnilaps(
    output_file: str,
    semordnilaps: dict[str, set[str]],
    palindromes: dict[str, set[str]],
):
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"Total semordnilaps: {len(semordnilaps)}\n\n")
        for word, matches in semordnilaps.items():
            f.write(f"{word} → {', '.join(sorted(matches))}\n")
        f.write(f"\nTotal palindromes: {len(palindromes)}\n\n")
        for word, matches in palindromes.items():
            f.write(f"{word} → {', '.join(sorted(matches))}\n")


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser("Find semordnilaps")
    parser.add_argument(
        "-l", "--lexicon", help="Lexicon filepath", required=True
    )
    parser.add_argument("-o", "--out", help="Output filepath", required=True)
    parser.add_argument(
        "-t",
        "--th",
        help="N-gram freq threshold (default th = 0.3)",
        required=False,
        default=0.3,
        type=float,
    )
    return parser


@dataclass
class SearchOptions:
    lexicon_filepath: str
    out_filepath: str
    freq_treshold: float = field(default=0.3)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = build_argparser().parse_args(argv)
    opts = SearchOptions(
        lexicon_filepath=args.lexicon,
        out_filepath=args.out,
        freq_treshold=args.th,
    )
    logger.info("Using: %s", opts)

    lexicon = load_lexicon(opts.lexicon_filepath)
    semordnilaps, palindromes = find_semordnilap(
        lexicon, threshold=opts.freq_treshold
    )
    semordnilaps = dict(
        sorted(semordnilaps.items(), key=lambda item: normalize_word(item[0]))
    )
    palindromes = dict(
        sorted(palindromes.items(), key=lambda item: normalize_word(item[0]))
    )

    save_semordnilaps(
        semordnilaps=semordnilaps,
        palindromes=palindromes,
        output_file=opts.out_filepath,
    )


if __name__ == "__main__":
    main()
