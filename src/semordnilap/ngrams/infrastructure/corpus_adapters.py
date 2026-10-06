"""Resolve downloaded corpus artifacts into raw n-gram inputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from semordnilap.utils.artifacts import manifest_path, read_complete_manifest
from semordnilap.utils.io import detect_corpus_format

SOURCE_ADAPTERS = ("auto", "raw", "wikisource", "corpusnos")
SOURCE_CORPUS_SCHEMA = "semordnilap.source-corpus"
SOURCE_COLLECTION_SCHEMA = "semordnilap.source-collection"


@dataclass(frozen=True)
class ResolvedCorpusInput:
    path: Path
    files: tuple[Path, ...]
    input_format: str
    text_field: str
    corpus: str
    adapter: str


def _read_manifest(path: Path) -> dict | None:
    candidate = manifest_path(path)
    if not candidate.is_file():
        return None
    return read_complete_manifest(path, verify_checksums=False)


def _infer_adapter(path: Path, manifest: dict | None) -> str:
    if not manifest:
        return "raw"
    schema = manifest.get("schema")
    dataset = str(manifest.get("dataset") or "").lower()
    config = str(manifest.get("config") or "")
    if schema == SOURCE_CORPUS_SCHEMA:
        if dataset == "wikimedia/wikisource" or (
            manifest.get("date") and "." in config
        ):
            return "wikisource"
        if dataset == "proxectonos/corpusnos" or config.startswith(
            ("dta_", "public_data_")
        ):
            return "corpusnos"
    if schema == SOURCE_COLLECTION_SCHEMA:
        if (
            dataset == "proxectonos/corpusnos"
            or manifest.get("configs") is not None
        ):
            return "corpusnos"
        children = _collection_children(path, manifest)
        child_datasets = {
            str(child_manifest.get("dataset") or "").lower()
            for _child, child_manifest in children
        }
        if child_datasets == {"wikimedia/wikisource"}:
            return "wikisource"
    return "raw"


def _collection_children(
    path: Path, manifest: dict
) -> list[tuple[Path, dict]]:
    if not path.is_dir():
        raise ValueError(f"Corpus collection must be a directory: {path}")
    artifact_entries = manifest.get("artifacts") or []
    expected_ids = [entry.get("artifact_id") for entry in artifact_entries]
    if not expected_ids or any(not value for value in expected_ids):
        raise ValueError(f"Corpus collection has invalid artifacts: {path}")
    if len(set(expected_ids)) != len(expected_ids):
        raise ValueError(f"Corpus collection repeats an artifact: {path}")

    discovered: dict[str, tuple[Path, dict]] = {}
    for child in sorted(path.iterdir()):
        if not child.is_dir() or child.name.endswith(".part"):
            continue
        child_manifest_path = manifest_path(child)
        if not child_manifest_path.is_file():
            continue
        try:
            child_manifest = json.loads(
                child_manifest_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            continue
        artifact_id = child_manifest.get("artifact_id")
        if (
            child_manifest.get("status") == "complete"
            and artifact_id in expected_ids
        ):
            if artifact_id in discovered:
                raise ValueError(
                    f"Corpus collection has duplicate child artifact "
                    f"{artifact_id}: {path}"
                )
            discovered[artifact_id] = (child, child_manifest)

    missing = [value for value in expected_ids if value not in discovered]
    if missing:
        raise ValueError(
            f"Corpus collection is missing {len(missing)} complete artifact(s): "
            f"{path}"
        )
    return [discovered[value] for value in expected_ids]


def _artifact_files(path: Path, manifest: dict) -> tuple[Path, ...]:
    if manifest.get("schema") != SOURCE_CORPUS_SCHEMA:
        raise ValueError(f"Not a source corpus artifact: {path}")
    files = []
    seen = set()
    for shard in manifest.get("shards") or []:
        relative = Path(str(shard.get("path") or ""))
        if (
            not relative.name
            or relative.is_absolute()
            or ".." in relative.parts
        ):
            raise ValueError(
                f"Invalid corpus shard path in {path}: {relative}"
            )
        candidate = path / relative
        if not candidate.is_file():
            raise ValueError(f"Corpus shard is missing: {candidate}")
        if candidate in seen:
            raise ValueError(f"Corpus shard is repeated: {candidate}")
        seen.add(candidate)
        files.append(candidate)
    if not files:
        raise ValueError(f"Corpus artifact has no shards: {path}")
    return tuple(files)


def _resolve_wikisource(
    path: Path, manifest: dict, *, lang: str, corpus: str | None
) -> ResolvedCorpusInput:
    schema = manifest.get("schema")
    if schema == SOURCE_COLLECTION_SCHEMA:
        matches = [
            (child, child_manifest)
            for child, child_manifest in _collection_children(path, manifest)
            if str(child_manifest.get("lang") or "").lower() == lang
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Wikisource collection must contain exactly one complete "
                f"artifact for language {lang!r}: {path}"
            )
        path, manifest = matches[0]
    elif schema != SOURCE_CORPUS_SCHEMA:
        raise ValueError(f"Not a Wikisource source artifact: {path}")

    artifact_lang = str(manifest.get("lang") or "").lower()
    if artifact_lang != lang:
        raise ValueError(
            f"Wikisource artifact language {artifact_lang!r} does not match "
            f"--lang {lang!r}"
        )
    date = str(manifest.get("date") or "").strip()
    if not date:
        config = str(manifest.get("config") or "")
        date = config.split(".", 1)[0]
    alias = corpus or (f"wikisource_{date}" if date else "wikisource")
    return ResolvedCorpusInput(
        path=path,
        files=_artifact_files(path, manifest),
        input_format="jsonl",
        text_field="text",
        corpus=alias,
        adapter="wikisource",
    )


def _resolve_corpusnos(
    path: Path, manifest: dict, *, lang: str, corpus: str | None
) -> ResolvedCorpusInput:
    if lang != "gl":
        raise ValueError("CorpusNOS only supports --lang gl")
    schema = manifest.get("schema")
    if schema == SOURCE_COLLECTION_SCHEMA:
        children = _collection_children(path, manifest)
        files = []
        for child, child_manifest in children:
            if str(child_manifest.get("lang") or "").lower() != "gl":
                raise ValueError(
                    f"CorpusNOS child artifact is not Galician: {child}"
                )
            files.extend(_artifact_files(child, child_manifest))
        alias = corpus or "corpusnos"
    elif schema == SOURCE_CORPUS_SCHEMA:
        artifact_lang = str(manifest.get("lang") or "").lower()
        if artifact_lang != "gl":
            raise ValueError(f"CorpusNOS artifact is not Galician: {path}")
        config = str(manifest.get("config") or "").strip()
        if not config:
            raise ValueError(f"CorpusNOS artifact has no config: {path}")
        files = list(_artifact_files(path, manifest))
        alias = corpus or f"corpusnos_{config}"
    else:
        raise ValueError(f"Not a CorpusNOS source artifact: {path}")
    return ResolvedCorpusInput(
        path=path,
        files=tuple(files),
        input_format="jsonl",
        text_field="text",
        corpus=alias,
        adapter="corpusnos",
    )


def resolve_corpus_input(
    path: Path,
    *,
    adapter: str,
    lang: str,
    corpus: str | None,
    requested_format: str,
    text_field: str,
) -> ResolvedCorpusInput:
    manifest = _read_manifest(path)
    selected = adapter
    if selected == "auto":
        selected = (
            "raw"
            if requested_format not in {"auto", "jsonl"}
            else _infer_adapter(path, manifest)
        )
    if selected == "raw":
        return ResolvedCorpusInput(
            path=path,
            files=(),
            input_format=detect_corpus_format(path, requested_format),
            text_field=text_field,
            corpus=corpus or "default",
            adapter="raw",
        )
    if requested_format not in {"auto", "jsonl"}:
        raise ValueError(
            f"The {selected} adapter requires --format auto or jsonl"
        )
    if text_field != "text":
        raise ValueError(f"The {selected} adapter requires --text-field text")
    if manifest is None:
        raise ValueError(f"Corpus artifact manifest is missing: {path}")
    if selected == "wikisource":
        return _resolve_wikisource(path, manifest, lang=lang, corpus=corpus)
    if selected == "corpusnos":
        return _resolve_corpusnos(path, manifest, lang=lang, corpus=corpus)
    raise ValueError(f"Unsupported corpus adapter: {selected}")
