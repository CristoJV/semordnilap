"""Download cleaned Wikisource corpora for n-gram extraction."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable


DEFAULT_DATE = "20231201"
DEFAULT_LANGS = ("es", "pt")
DEFAULT_DATASET = "wikimedia/wikisource"
DEFAULT_OUT_DIR = Path("data/raw/wikisource")


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download cleaned Wikisource corpora from Hugging Face."
    )
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET,
        help=f"Hugging Face dataset name. Default: {DEFAULT_DATASET}",
    )
    parser.add_argument(
        "--date",
        default=DEFAULT_DATE,
        help=f"Wikisource dump date/config prefix. Default: {DEFAULT_DATE}",
    )
    parser.add_argument(
        "--langs",
        nargs="+",
        default=list(DEFAULT_LANGS),
        help="Language codes to download. Default: es pt",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Output directory. Default: {DEFAULT_OUT_DIR}",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Optional Hugging Face datasets cache directory.",
    )
    parser.add_argument(
        "--write-text",
        action="store_true",
        help="Also export one plain-text file per language.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output files.",
    )
    return parser


def load_hf_dataset(dataset_name: str, config: str, cache_dir: Path | None):
    try:
        from datasets import load_dataset
    except ImportError:
        print(
            "Missing dependency: datasets. Install it with `uv add datasets`.",
            file=sys.stderr,
        )
        raise

    return load_dataset(
        dataset_name,
        config,
        split="train",
        cache_dir=str(cache_dir) if cache_dir else None,
    )


def ensure_can_write(path: Path, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(
            f"{path} already exists. Use --force to overwrite it."
        )


def write_jsonl(rows: Iterable[dict], output_path: Path) -> int:
    count = 0
    with output_path.open("w", encoding="utf-8") as f:
        for row in rows:
            record = {
                "id": row.get("id"),
                "url": row.get("url"),
                "title": row.get("title"),
                "text": row.get("text"),
            }
            f.write(json.dumps(record, ensure_ascii=False))
            f.write("\n")
            count += 1
    return count


def write_text(rows: Iterable[dict], output_path: Path) -> int:
    count = 0
    with output_path.open("w", encoding="utf-8") as f:
        for row in rows:
            title = (row.get("title") or "").strip()
            text = (row.get("text") or "").strip()
            if not text:
                continue
            if title:
                f.write(f"\n\n# {title}\n\n")
            f.write(text)
            f.write("\n")
            count += 1
    return count


def export_language(args: argparse.Namespace, lang: str) -> None:
    config = f"{args.date}.{lang}"
    jsonl_path = args.out_dir / f"wikisource_{lang}_{args.date}.jsonl"
    text_path = args.out_dir / f"wikisource_{lang}_{args.date}.txt"

    ensure_can_write(jsonl_path, args.force)
    if args.write_text:
        ensure_can_write(text_path, args.force)

    print(f"Loading {args.dataset}:{config}")
    dataset = load_hf_dataset(args.dataset, config, args.cache_dir)

    exported = write_jsonl(dataset, jsonl_path)
    print(f"Wrote {exported} documents to {jsonl_path}")

    if args.write_text:
        exported_texts = write_text(dataset, text_path)
        print(f"Wrote {exported_texts} texts to {text_path}")


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    for lang in args.langs:
        export_language(args, lang)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

