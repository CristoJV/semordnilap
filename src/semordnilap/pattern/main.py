import argparse
import json
import logging
from collections import defaultdict
from itertools import product
from pathlib import Path

from tqdm import tqdm

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


def load_lexicon(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_tag_index(lexicon):
    tag_index = defaultdict(set)

    for form, analyses in tqdm(
        lexicon.items(),
        total=len(lexicon),
        desc="Building tag index from lexicon",
    ):
        for entry in analyses:
            tag = entry.get("tag")
            if not tag:
                continue

            tag_index[tag].add(form)
    return tag_index


def generate_candidates(tag_index, pattern):
    buckets = []
    for tag in pattern:
        words = tag_index.get(tag, set())

        if not words:
            logger.warning("No forms for TAG=%s", tag)
            return []
        buckets.append(sorted(words))

    raw_candidates = list(product(*buckets))
    return [" ".join(candidate) for candidate in raw_candidates]


def build_parser():
    parser = argparse.ArgumentParser("Pattern generator (tag-based)")
    parser.add_argument("-l", "--lexicon", help="Lexicon JSON filepath")
    parser.add_argument("-o", "--out", help="Output filepath")
    parser.add_argument("-p", "--pattern", nargs="+", help="Tag pattern")
    return parser


def export_candidates(out_filepath: str, candidates: list[str]):
    with open(out_filepath, "w", encoding="utf-8") as f:
        for candidate in candidates:
            f.write(f"{candidate}\n")


def main():
    args = build_parser().parse_args()
    lexicon = load_lexicon(args.lexicon)
    tag_index = build_tag_index(lexicon)

    candidates = generate_candidates(tag_index, args.pattern)
    candidates_filepath = Path(args.out)
    candidates_filepath.parent.mkdir(parents=True, exist_ok=True)
    export_candidates(candidates_filepath, candidates)
    logger.info(
        "Generated %d candidates. Saved them in %s",
        len(candidates),
        candidates_filepath,
    )


if __name__ == "__main__":
    main()
