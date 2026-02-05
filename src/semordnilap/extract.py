import argparse
import bz2
import json
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from tqdm import tqdm

# ---------------------------------------------------------------------#
# Logging configuration
# ---------------------------------------------------------------------#

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)

DEFAULT_DESIRED_CATEGORIES = {
    "adjetivo",
    "adverbio",
    "sustantivo",
    "verbo",
    "locución",
    "interjección",
    "preposición",
    "conjunción",
    "pronombre",
    "determinante",
    "numeral",
    "onomatopeya",
    "forma",
}


def extact_pos_bases_from_spanish(wikitext: str) -> set[str]:
    """
    Extract grammatical base categories from Spanish headings.

    Examples detected:
        === Sustantivo ===
        ==== {{forma verbal}} ====
        ==== {{adjetivo demostrativo}} ====

    Ignored:
        Traducciones, Véase, Etimología, Información, etc.
    """

    # POS Part Of Speech (Categoría Gramatical)
    # Heading examples matches:
    # === Sustantivo ====
    # === {{forma verbal}} ====
    pos_header_re = re.compile(
        r"^(?P<eq>={3,5})\s*(?P<body>.*?)\s*(?P=eq)\s*$", re.M
    )
    # Extracts {{template|...}} from a heading
    header_template_re = re.compile(r"\{\{\s*([^|}\n]+)\s*(\|[^}]*)?\}\}")

    if not wikitext:
        return set()

    categories: set[str] = set()

    for m in pos_header_re.finditer(wikitext):
        body = (m.group("body") or "").strip()

        tm = header_template_re.search(body)
        if tm:
            label = tm.group(1)
        else:
            label = body

        base_category = get_base_category(label)
        if base_category:
            categories.add(base_category)
    return categories


def extract_spanish_section(
    text: str,
) -> str | None:
    """
    Extract only the Spanish section from a Wiktionary entry.

    Everything outside == {{lengua|es}} == is ignored.
    """
    es_lang_header_re = re.compile(r"^==\s*\{\{lengua\|es\}\}\s*==\s*$", re.M)
    next_lang_header_re = re.compile(r"^==[^=].*==\s*$", re.M)

    if not text:
        return None

    m = es_lang_header_re.search(text or "")
    if not m:
        return None

    start = m.end()
    rest = text[start:]
    m2 = next_lang_header_re.search(rest)

    end = start + (m2.start() if m2 else len(rest))
    return text[start:end]


def normalize_label(text: str) -> str:
    """Normalize template or heading names."""
    whitespace_re = re.compile(r"\s+")
    return whitespace_re.sub(" ", (text or "").strip().lower())


def get_base_category(label: str) -> str:
    """
    Convert extended categories to base POS

    Examples:
        "forma verbo" -> "forma"
        "sustantivo masculino" -> "sustantivo"
        "adjetivo demostrativo" -> "adjetivo"
    """
    label = normalize_label(label)
    return label.split(" ", 1)[0] if label else ""


def is_clean_word(word: str) -> bool:
    WORD_RE = re.compile(r"^[a-záéíóúüñ]+$", re.IGNORECASE)
    if not word:
        return False
    if " " in word:
        return False
    return WORD_RE.fullmatch(word) is not None


class ProgressReader:
    def __init__(self, raw, pbar):
        self.raw = raw
        self.pbar = pbar

    def read(self, size=-1):
        data = self.raw.read(size)
        if data:
            self.pbar.update(len(data))
        return data


@dataclass
class ExtractOptions:
    dump_filepath: str
    out_filepath: str
    max_pages: int


def iter_words_from_dump(
    opts: ExtractOptions, desired_categories: set[str]
) -> Iterable[str]:
    total_bytes = os.path.getsize(opts.dump_filepath)
    pbar = tqdm(
        total=total_bytes, unit="B", unit_scale=True, desc="Reading dump"
    )
    count = 0
    with open(opts.dump_filepath, "rb") as raw:
        wrapped = ProgressReader(raw, pbar)
        with bz2.open(wrapped, "rb") as f:
            for _, elem in ET.iterparse(f, events=("end",)):
                if not elem.tag.endswith("page"):
                    continue

                ns = elem.findtext(".//{*}ns")
                if ns != "0":
                    elem.clear()
                    continue

                title = elem.findtext(".//{*}title") or ""
                text = elem.findtext(".//{*}text") or ""

                spanish = extract_spanish_section(text)
                if not spanish:
                    elem.clear()
                    continue

                categories = extact_pos_bases_from_spanish(spanish)

                if not categories.intersection(desired_categories):
                    elem.clear()
                    continue

                word = title.strip().lower()
                yield word, categories

                count += 1
                elem.clear()

                if opts.max_pages and count >= opts.max_pages:
                    break
    pbar.close()


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


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        "Extract spanish lexicon from aw Wiktionary dump."
    )
    parser.add_argument("-d", "--dump", help="Dump filepath", required=True)
    parser.add_argument("-o", "--out", help="Output filepath", required=True)
    parser.add_argument("--max-pages", help="Page limit", default=0)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = build_argparser().parse_args(argv)

    opts = ExtractOptions(
        dump_filepath=args.dump,
        out_filepath=args.out,
        max_pages=args.max_pages,
    )

    desired_categories = set(DEFAULT_DESIRED_CATEGORIES)

    lexicon = defaultdict(set)
    for lemma, pos_set in iter_words_from_dump(opts, desired_categories):
        lexicon[lemma].update(pos_set)
    n = export_words_json(opts.out_filepath, lexicon)
    logger.info("Created %s with %d words", opts.out_filepath, n)
    return 0


if __name__ == "__main__":
    main()
