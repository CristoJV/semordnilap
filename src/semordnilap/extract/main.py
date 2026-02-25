import argparse
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from semordnilap.extract.core import iter_pages
from semordnilap.extract.languages import LANGUAGE_ENGINES
from semordnilap.extract.utils import export_json

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


@dataclass
class ExtractOptions:
    dump_filepath: str
    out_filepath: str
    max_pages: int
    language: str


def tag_to_pos(tag: str) -> str:
    mapping = {
        "N": "NOUN",
        "A": "ADJ",
        "V": "VERB",
        "D": "DET",
        "P": "PRON",
        "S": "ADP",
        "C": "CONJ",
        "I": "INTJ",
        "F": "PUNCT",
        "Z": "NUM",
    }
    if not tag:
        return "UNK"
    return mapping.get(tag[0], "UNK")


def run_freeling_extraction(dicc_filepath: str):
    lexicon = defaultdict(list)

    with open(dicc_filepath, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            parts = line.split()
            form = parts[0]
            rest = parts[1:]

            if len(rest) % 2 != 0:
                logger.warning("Malformed line %d: %s", lineno, line)
                continue

            for i in range(0, len(rest), 2):
                lemma = rest[i]
                tag = rest[i + 1]

                entry = {
                    "source": "freeling",
                    "lemma": lemma,
                    "pos": tag_to_pos(tag),
                    "tag": tag,
                }

                lexicon[form].append(entry)
    return lexicon


def run_wiktionary_extraction(
    dump_filepath: str, max_pages: int, language: str
):

    engine = LANGUAGE_ENGINES[language](dump_filepath)

    lexicon = defaultdict(set)

    for ns, title, text in iter_pages(dump_filepath, max_pages=max_pages):
        if ns != "0":
            continue

        result, expansions = engine.process_page(title, text)

        if not result:
            continue

        lemma, pos = result
        lexicon[lemma].update(pos)

        for word, kind in expansions:
            lexicon[word].add(kind)
    return lexicon


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser("Unified lexicon extraction tool")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Wikitionary extraction
    wik_parser = subparsers.add_parser("wik")
    wik_parser.add_argument(
        "-d", "--dump", help="Dump filepath", required=True
    )
    wik_parser.add_argument(
        "-o", "--out", help="Output filepath", required=True
    )
    wik_parser.add_argument(
        "--max-pages", help="Page limit", default=0, type=int
    )
    wik_parser.add_argument(
        "-l", "--language", help="Language code", default="es"
    )

    # Freeling extraction

    fling_parser = subparsers.add_parser("fling")
    fling_parser.add_argument(
        "-d", "--dicc", help="Path to dicc.src", required=True
    )
    fling_parser.add_argument(
        "-o", "--out", help="Output JSON filepath", required=True
    )
    return parser


def main() -> int:
    args = build_argparser().parse_args()

    if args.command == "fling":
        lexicon = run_freeling_extraction(args.dicc)

    elif args.command == "wik":
        lexicon = run_wiktionary_extraction(
            args.dump, args.max_pages, args.language
        )
    else:
        raise RuntimeError(f"Unknown command {args.command}")

    json_filepath = Path(args.out)
    json_filepath.parent.mkdir(parents=True, exist_ok=True)

    n = export_json(json_filepath, lexicon)
    logger.info("Created %s with %d words", json_filepath, n)
    return 0


if __name__ == "__main__":
    main()
