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


def load_words(words_filepath: Path) -> object:
    with open(words_filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def filter_common_words(
    words: list[str], language: str = "es", threshold: float = 3.0
):
    return [w for w in words if zipf_frequency(w, language) >= threshold]


def normalize_word(word: str):
    remove_unicode_marks = set(
        [
            "\u0301",  # acute  ´
            "\u0300",  # grave  `
            "\u0302",  # circumflex ^
            "\u0308",  # diaeresis ¨
        ]
    )
    word = unicodedata.normalize("NFD", word)
    word = "".join(c for c in word if c not in remove_unicode_marks)
    return unicodedata.normalize("NFC", word)


def decompositions_candidates(
    norm_target: str,
    norm_ngrams: set[str],
    maximum_ngrams: int = 3,
):
    solutions: list[list[str]] = []
    candidates: list[tuple[int, list[str]]] = [(0, [])]

    while candidates:
        i, phrase = candidates.pop()

        if i == len(norm_target):
            solutions.append(phrase)
            continue

        if len(phrase) >= maximum_ngrams:  # Prune
            continue

        for j in range(i + 1, len(norm_target) + 1):
            frag = norm_target[i:j]
            if frag in norm_ngrams:
                candidates.append((j, phrase + [frag]))
    return solutions


def find_semordnilaps(
    src_ngrams: set[str], dst_ngrams: set[str], threshold: float = 3.0
) -> dict[str, dict[int, set[list[str]]]]:
    # Stores normalized versions for each ngram
    src_norm_cache = {}
    src_norm_to_origins_dict = defaultdict(set)
    dst_norm_cache = {}
    dst_norm_to_origins_dict = defaultdict(set)

    for g in src_ngrams:
        ng = src_norm_cache.setdefault(g, normalize_word(g))
        src_norm_to_origins_dict[ng].add(g)

    for g in dst_ngrams:
        ng = dst_norm_cache.setdefault(g, normalize_word(g))
        dst_norm_to_origins_dict[ng].add(g)

    dst_norm_ngrams = set(dst_norm_to_origins_dict.keys())

    semordnilaps: dict[str, dict[int, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )

    for query_ngram in tqdm(
        src_ngrams, desc="Analyzing words", total=len(src_ngrams)
    ):
        src_norm_ngram = src_norm_cache[query_ngram]
        reversed_ngram = src_norm_ngram[::-1]

        solutions = decompositions_candidates(
            reversed_ngram, dst_norm_ngrams, 1
        )

        for sol in solutions:
            phrase = " ".join(sol)
            word_count = len(sol)
            semordnilaps[query_ngram][word_count].add(phrase)

    return semordnilaps


def save_semordnilaps(
    output_file: str,
    semordnilaps: dict[str, set[str]],
):
    serializable = {
        word: {
            str(word_count): sorted(phrases)
            for word_count, phrases in by_count.items()
        }
        for word, by_count in semordnilaps.items()
    }
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False)


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser("Find semordnilaps")
    parser.add_argument(
        "-s",
        "--src",
        dest="source_lexicon",
        help="Source lexicon filepath",
        required=True,
    )
    parser.add_argument(
        "-t",
        "--tgt",
        dest="target_lexicon",
        help="Target lexicon filepath",
        required=False,
    )
    parser.add_argument("-o", "--out", help="Output filepath", required=True)
    parser.add_argument(
        "-th",
        "--threshold",
        help="N-gram freq threshold (default th = 0.3)",
        required=False,
        default=0.3,
        type=float,
    )
    return parser


@dataclass
class SearchOptions:
    source_lexicon_filepath: str
    target_lexicon_filepath: str
    out_filepath: str
    freq_treshold: float = field(default=0.3)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = build_argparser().parse_args(argv)

    opts = SearchOptions(
        source_lexicon_filepath=args.source_lexicon,
        target_lexicon_filepath=args.target_lexicon
        if args.target_lexicon
        else args.source_lexicon,
        out_filepath=args.out,
        freq_treshold=args.threshold,
    )
    logger.info("Using: %s", opts)

    logger.info(
        "Loading source lexicon from: %s", opts.source_lexicon_filepath
    )
    source_lexicon = load_words(opts.source_lexicon_filepath)
    logger.info(
        "Loading target lexicon from: %s", opts.target_lexicon_filepath
    )
    target_lexicon = load_words(opts.target_lexicon_filepath)

    logger.info("Looking for semordnilaps...")
    semordnilaps = find_semordnilaps(
        source_lexicon, target_lexicon, threshold=opts.freq_treshold
    )

    logger.info("Sorting semordnilaps...")
    semordnilaps = dict(
        sorted(semordnilaps.items(), key=lambda item: normalize_word(item[0]))
    )
    logger.info("Saving semordnilaps at: %s", opts.out_filepath)
    save_semordnilaps(
        semordnilaps=semordnilaps,
        output_file=opts.out_filepath,
    )


if __name__ == "__main__":
    main()
