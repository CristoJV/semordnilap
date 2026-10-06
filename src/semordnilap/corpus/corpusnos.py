"""Stream selected Galician CorpusNOS subsets from Hugging Face."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Iterable

from huggingface_hub import HfApi, HfFileSystem, hf_hub_download

from semordnilap.corpus.wikisource import export_rows
from semordnilap.utils.artifacts import (
    ArtifactLock,
    read_complete_manifest,
    stable_id,
    utc_now,
    write_json_atomic,
)

DEFAULT_DATASET = "proxectonos/corpusnos"
DEFAULT_OUT_DIR = Path("data/corpus/corpusnos")
DEFAULT_SUBSETS = (
    "books",
    "research_articles",
    "press_blogs",
    "encyclopedic",
)

SUBSET_CONFIGS = {
    "books": ("dta_books",),
    "research_articles": ("dta_research_articles",),
    "press_blogs": (
        "dta_press_and_blogs",
        "public_data_press_and_blogs",
    ),
    "encyclopedic": (
        "dta_encyclopedic",
        "public_data_encyclopedic",
    ),
    "governmental": ("dta_governmental",),
    "web_contents": ("dta_web_contents",),
    "web_crawls": ("public_data_web_crawls",),
    "translation_corpora": ("public_data_translation_corpora",),
}
ALL_CONFIGS = tuple(
    config for configs in SUBSET_CONFIGS.values() for config in configs
)
CONFIG_PREFIXES = {
    "dta_books": "data_transfer_agreement/books/",
    "dta_research_articles": "data_transfer_agreement/research_articles/",
    "dta_press_and_blogs": "data_transfer_agreement/press_and_blogs/",
    "dta_encyclopedic": "data_transfer_agreement/encyclopedic/",
    "dta_governmental": "data_transfer_agreement/governmental/",
    "dta_web_contents": "data_transfer_agreement/web_contents/",
    "public_data_press_and_blogs": "public_data/press_and_blogs/",
    "public_data_encyclopedic": "public_data/encyclopedic/",
    "public_data_web_crawls": "public_data/web_crawls/",
    "public_data_translation_corpora": "public_data/translation_corpora/",
}


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--revision", default="main")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--subsets",
        nargs="+",
        choices=(*SUBSET_CONFIGS, "all"),
        default=list(DEFAULT_SUBSETS),
        help=(
            "logical subsets to download (default: books, "
            "research_articles, press_blogs, encyclopedic)"
        ),
    )
    selection.add_argument(
        "--configs",
        nargs="+",
        choices=ALL_CONFIGS,
        help="exact Hugging Face configurations to download",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--shard-docs", type=int, default=1000)
    parser.add_argument(
        "--compression", choices=["gzip", "none"], default="gzip"
    )
    parser.add_argument(
        "--streaming", action=argparse.BooleanOptionalAction, default=True
    )
    recovery = parser.add_mutually_exclusive_group()
    recovery.add_argument("--resume", action="store_true")
    recovery.add_argument("--force", action="store_true")


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download selected CorpusNOS Galician corpus artifacts."
    )
    configure_parser(parser)
    return parser


def selected_configs(args: argparse.Namespace) -> list[str]:
    if args.configs:
        requested = args.configs
    elif "all" in args.subsets:
        requested = list(ALL_CONFIGS)
    else:
        requested = [
            config
            for subset in args.subsets
            for config in SUBSET_CONFIGS[subset]
        ]
    return list(dict.fromkeys(requested))


def load_hf_dataset(
    dataset_name: str,
    config: str,
    cache_dir: Path | None,
    *,
    revision: str,
    streaming: bool,
):
    prefix = CONFIG_PREFIXES[config]
    files = sorted(
        path
        for path in HfApi().list_repo_files(
            dataset_name, repo_type="dataset", revision=revision
        )
        if path.startswith(prefix) and path.endswith(".jsonl")
    )
    if not files:
        raise FileNotFoundError(
            f"No JSONL files found for CorpusNOS config {config!r} "
            f"at revision {revision!r}"
        )

    def rows():
        filesystem = HfFileSystem() if streaming else None
        for filename in files:
            if streaming:
                path = f"datasets/{dataset_name}@{revision}/{filename}"
                assert filesystem is not None
                stream_context = filesystem.open(path, "r", encoding="utf-8")
            else:
                path = hf_hub_download(
                    dataset_name,
                    filename,
                    repo_type="dataset",
                    revision=revision,
                    cache_dir=str(cache_dir) if cache_dir else None,
                )
                stream_context = Path(path).open("r", encoding="utf-8")
            with stream_context as stream:
                for lineno, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(
                            f"Invalid JSONL at {filename}:{lineno}"
                        ) from exc
                    if not isinstance(row, dict):
                        raise ValueError(
                            f"JSONL record must be an object at "
                            f"{filename}:{lineno}"
                        )
                    yield row

    return rows()


def _rows(rows: Iterable[dict]) -> Iterable[dict]:
    for row in rows:
        # export_rows deliberately stores a compact, consumer-neutral record.
        # Keep useful CorpusNOS metrics without coupling later stages to them.
        yield {
            "id": row.get("id", row.get("doc_id")),
            "url": row.get("url", row.get("source_url")),
            "title": row.get("title"),
            "text": row.get("text"),
            "num_words": row.get("num_words"),
            "pyplexity_score": row.get("pyplexity_score"),
            "lang": row.get("lang", row.get("language")),
            "num_tokens": row.get("num_tokens", row.get("tokens")),
        }


def export_config(args: argparse.Namespace, config: str) -> dict:
    artifact_path = args.out_dir / f"corpusnos_{config}"
    partial = artifact_path.with_name(artifact_path.name + ".part")
    with ArtifactLock(artifact_path):
        if args.force:
            if artifact_path.exists():
                shutil.rmtree(artifact_path)
            if partial.exists():
                shutil.rmtree(partial)
        elif artifact_path.exists():
            if args.resume:
                return read_complete_manifest(
                    artifact_path, verify_checksums=False
                )
            raise FileExistsError(
                f"Corpus artifact already exists: {artifact_path}"
            )
        elif partial.exists() and not args.resume:
            raise FileExistsError(
                f"Incomplete corpus exists at {partial}; "
                "use --resume or --force"
            )

        resume = args.resume and partial.exists()
        dataset = load_hf_dataset(
            args.dataset,
            config,
            args.cache_dir,
            revision=args.revision,
            streaming=args.streaming,
        )
        return export_rows(
            _rows(dataset),
            artifact_path,
            identity={
                "dataset": args.dataset,
                "config": config,
                "revision": args.revision,
                "lang": "gl",
                "compression": args.compression,
                "shard_docs": args.shard_docs,
            },
            shard_docs=args.shard_docs,
            compression=args.compression,
            resume=resume,
        )


def run(args: argparse.Namespace) -> int:
    if args.shard_docs < 1:
        raise ValueError("--shard-docs must be at least 1")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    configs = selected_configs(args)
    manifests = [export_config(args, config) for config in configs]
    collection = {
        "schema": "semordnilap.source-collection",
        "schema_version": 1,
        "status": "complete",
        "created_at": utc_now(),
        "dataset": args.dataset,
        "revision": args.revision,
        "configs": configs,
        "artifacts": [
            {
                "config": manifest["config"],
                "lang": manifest["lang"],
                "artifact_id": manifest["artifact_id"],
            }
            for manifest in manifests
        ],
    }
    collection["artifact_id"] = stable_id("source-collection", collection)
    collection["sha256"] = collection["artifact_id"].split(":", 1)[1]
    write_json_atomic(args.out_dir / "manifest.json", collection)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(build_argparser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
