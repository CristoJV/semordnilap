import argparse
import json
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from semordnilap.extract_engine.core import iter_pages
from semordnilap.extract_engine.languages import LANGUAGE_ENGINES

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


def export_words_json(path: str, words: Iterable[str]) -> int:
    ordered = {k: sorted(words[k]) for k in sorted(words)}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            ordered,
            f,
            ensure_ascii=False,
            indent=2,
        )
    return len(ordered)


def run_extraction(opts: ExtractOptions):

    engine = LANGUAGE_ENGINES[opts.language](opts.dump_filepath)

    lexicon = defaultdict(set)

    for ns, title, text in iter_pages(
        opts.dump_filepath, max_pages=opts.max_pages
    ):
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
    parser = argparse.ArgumentParser(
        "Extract spanish lexicon from aw Wiktionary dump."
    )
    parser.add_argument("-d", "--dump", help="Dump filepath", required=True)
    parser.add_argument("-o", "--out", help="Output filepath", required=True)
    parser.add_argument("--max-pages", help="Page limit", default=0)
    parser.add_argument("-l", "--language", help="Language code", default="es")

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = build_argparser().parse_args(argv)

    opts = ExtractOptions(
        dump_filepath=args.dump,
        out_filepath=args.out,
        max_pages=args.max_pages,
        language=args.language,
    )

    lexicon = run_extraction(opts)
    n = export_words_json(opts.out_filepath, lexicon)
    logger.info("Created %s with %d words", opts.out_filepath, n)
    return 0


if __name__ == "__main__":
    main()
