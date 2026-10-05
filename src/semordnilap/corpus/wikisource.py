"""Stream reproducible Wikisource artifacts from Hugging Face."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Iterable

from tqdm import tqdm

from semordnilap.utils.artifacts import (
    ArtifactLock,
    sha256_file,
    stable_id,
    utc_now,
    write_json_atomic,
)

DEFAULT_DATE = "20231201"
DEFAULT_LANGS = ("es", "gl")
DEFAULT_DATASET = "wikimedia/wikisource"
DEFAULT_OUT_DIR = Path("data/corpus/wikisource")
CORPUS_SCHEMA = "semordnilap.source-corpus"
CORPUS_SCHEMA_VERSION = 1


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--date", default=DEFAULT_DATE)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--langs", nargs="+", default=list(DEFAULT_LANGS))
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
        description="Download versioned Wikisource corpus artifacts."
    )
    configure_parser(parser)
    return parser


def load_hf_dataset(
    dataset_name: str,
    config: str,
    cache_dir: Path | None,
    *,
    revision: str,
    streaming: bool,
):
    try:
        from datasets import load_dataset
    except ImportError:
        print("Missing dependency: datasets.", file=sys.stderr)
        raise
    return load_dataset(
        dataset_name,
        config,
        split="train",
        cache_dir=str(cache_dir) if cache_dir else None,
        revision=revision,
        streaming=streaming,
    )


def _record(row: dict) -> dict | None:
    text = row.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    record = {
        "id": row.get("id"),
        "url": row.get("url"),
        "title": row.get("title"),
        "text": text,
    }
    for field in ("num_words", "num_tokens", "pyplexity_score", "lang"):
        if row.get(field) is not None:
            record[field] = row[field]
    return record


def _open_shard(path: Path, compression: str):
    if compression == "gzip":
        return gzip.open(path, "wt", encoding="utf-8", newline="")
    return path.open("w", encoding="utf-8", newline="")


def _shard_name(index: int, compression: str) -> str:
    suffix = ".jsonl.gz" if compression == "gzip" else ".jsonl"
    return f"part-{index:05d}{suffix}"


def _write_work_manifest(
    path: Path,
    *,
    identity: dict,
    shards: list[dict],
    documents: int,
    rejected: int,
) -> None:
    write_json_atomic(
        path,
        {
            **identity,
            "schema": CORPUS_SCHEMA,
            "schema_version": CORPUS_SCHEMA_VERSION,
            "status": "writing",
            "updated_at": utc_now(),
            "documents": documents,
            "rejected_documents": rejected,
            "shards": shards,
        },
    )


def export_rows(
    rows: Iterable[dict],
    artifact_path: Path,
    *,
    identity: dict,
    shard_docs: int,
    compression: str,
    resume: bool,
) -> dict:
    partial = artifact_path.with_name(artifact_path.name + ".part")
    checkpoint = partial / "manifest.json"
    shards: list[dict] = []
    documents = rejected = consumed = 0
    if resume and checkpoint.exists():
        previous = json.loads(checkpoint.read_text(encoding="utf-8"))
        for key, value in identity.items():
            if previous.get(key) != value:
                raise ValueError(f"Corpus resume mismatch for {key}")
        shards = list(previous.get("shards") or [])
        documents = int(previous.get("documents", 0))
        rejected = int(previous.get("rejected_documents", 0))
        consumed = documents + rejected
    else:
        partial.mkdir(parents=True, exist_ok=False)
        _write_work_manifest(
            checkpoint,
            identity=identity,
            shards=shards,
            documents=0,
            rejected=0,
        )

    iterator = iter(rows)
    for _ in range(consumed):
        try:
            next(iterator)
        except StopIteration as exc:
            raise ValueError(
                "Dataset is shorter than its resume checkpoint"
            ) from exc

    progress = tqdm(iterator, desc=f"Exporting {identity['lang']}", unit="doc")
    progress_iterator = iter(progress)
    shard_index = len(shards)
    while True:
        shard_path = partial / _shard_name(shard_index, compression)
        accepted = 0
        exhausted = False
        with _open_shard(shard_path, compression) as stream:
            while accepted < shard_docs:
                try:
                    row = next(progress_iterator)
                except StopIteration:
                    exhausted = True
                    break
                record = _record(row)
                if record is None:
                    rejected += 1
                    continue
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                accepted += 1
                documents += 1
        if accepted:
            shard = {
                "path": shard_path.name,
                "documents": accepted,
                "bytes": shard_path.stat().st_size,
                "sha256": sha256_file(shard_path),
            }
            shards.append(shard)
            _write_work_manifest(
                checkpoint,
                identity=identity,
                shards=shards,
                documents=documents,
                rejected=rejected,
            )
            shard_index += 1
        else:
            shard_path.unlink(missing_ok=True)
        if exhausted:
            break

    content = {
        **identity,
        "schema": CORPUS_SCHEMA,
        "schema_version": CORPUS_SCHEMA_VERSION,
        "documents": documents,
        "rejected_documents": rejected,
        "shards": shards,
    }
    progress.close()
    content_digest = stable_id("source", content)
    final_manifest = {
        **content,
        "status": "complete",
        "created_at": utc_now(),
        "sha256": content_digest.split(":", 1)[1],
        "artifact_id": content_digest,
    }
    write_json_atomic(checkpoint, final_manifest)
    os.replace(partial, artifact_path)
    return final_manifest


def export_language(args: argparse.Namespace, lang: str) -> dict:
    config = f"{args.date}.{lang}"
    artifact_path = args.out_dir / f"wikisource_{lang}_{args.date}"
    partial = artifact_path.with_name(artifact_path.name + ".part")
    with ArtifactLock(artifact_path):
        if args.force:
            if artifact_path.exists():
                shutil.rmtree(artifact_path)
            if partial.exists():
                shutil.rmtree(partial)
        elif artifact_path.exists():
            raise FileExistsError(
                f"Corpus artifact already exists: {artifact_path}"
            )
        elif partial.exists() and not args.resume:
            raise FileExistsError(
                f"Incomplete corpus exists at {partial}; use --resume or --force"
            )
        elif args.resume and not partial.exists():
            raise FileNotFoundError(f"No partial corpus to resume: {partial}")

        dataset = load_hf_dataset(
            args.dataset,
            config,
            args.cache_dir,
            revision=args.revision,
            streaming=args.streaming,
        )
        return export_rows(
            dataset,
            artifact_path,
            identity={
                "dataset": args.dataset,
                "config": config,
                "revision": args.revision,
                "lang": lang,
                "date": args.date,
                "compression": args.compression,
                "shard_docs": args.shard_docs,
            },
            shard_docs=args.shard_docs,
            compression=args.compression,
            resume=args.resume,
        )


def run(args: argparse.Namespace) -> int:
    if args.shard_docs < 1:
        raise ValueError("--shard-docs must be at least 1")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    manifests = [export_language(args, lang.lower()) for lang in args.langs]
    collection = {
        "schema": "semordnilap.source-collection",
        "schema_version": 1,
        "status": "complete",
        "created_at": utc_now(),
        "artifacts": [
            {
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
