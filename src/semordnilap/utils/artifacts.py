"""Reproducible artifact metadata, atomic files, and writer locks."""

from __future__ import annotations

import hashlib
import json
import os
import socket
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def stable_id(prefix: str, value: Any) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    with partial.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(partial, path)
    fsync_directory(path.parent)


def manifest_path(path: Path) -> Path:
    if path.is_dir() or not path.suffix:
        return path / "manifest.json"
    return path.with_suffix(path.suffix + ".meta.json")


def read_complete_manifest(
    path: Path, *, verify_checksums: bool = True
) -> dict[str, Any]:
    candidate = manifest_path(path)
    if not candidate.exists():
        raise ValueError(f"Artifact manifest is missing: {candidate}")
    value = json.loads(candidate.read_text(encoding="utf-8"))
    if value.get("status") != "complete":
        raise ValueError(f"Artifact is not complete: {candidate}")
    if not value.get("artifact_id") or not value.get("sha256"):
        raise ValueError(
            f"Artifact manifest has no identity/checksum: {candidate}"
        )
    if verify_checksums and path.is_file():
        actual = sha256_file(path)
        if actual != value["sha256"]:
            raise ValueError(f"Artifact checksum mismatch: {path}")
    if verify_checksums and path.is_dir():
        for shard in value.get("shards") or []:
            shard_path = path / shard["path"]
            if not shard_path.is_file() or sha256_file(
                shard_path
            ) != shard.get("sha256"):
                raise ValueError(
                    f"Artifact shard checksum mismatch: {shard_path}"
                )
    return value


def compute_artifact_id(path: Path) -> str:
    """Hash an unmanifested legacy input as an immutable ordered artifact."""
    files = (
        [path]
        if path.is_file()
        else sorted(
            candidate
            for candidate in path.rglob("*")
            if candidate.is_file()
            and candidate.name != "manifest.json"
            and not candidate.name.endswith(".lock")
        )
    )
    if not files:
        raise FileNotFoundError(f"Artifact contains no files: {path}")
    entries = [
        {
            "path": str(
                file.relative_to(path) if path.is_dir() else file.name
            ),
            "bytes": file.stat().st_size,
            "sha256": sha256_file(file),
        }
        for file in files
    ]
    return stable_id("legacy-artifact", entries)


class ArtifactLock:
    """Non-blocking advisory lock whose file records current ownership."""

    def __init__(self, target: Path) -> None:
        self.path = target.with_name(target.name + ".lock")
        self._stream = None

    def __enter__(self) -> ArtifactLock:
        if os.name != "posix":
            raise RuntimeError("Artifact locks currently require POSIX flock")
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._stream.seek(0)
            owner = self._stream.read().strip() or "unknown owner"
            self._stream.close()
            self._stream = None
            raise RuntimeError(
                f"Artifact is locked by another process ({owner}): {self.path}"
            ) from exc
        self._stream.seek(0)
        self._stream.truncate()
        self._stream.write(
            canonical_json(
                {
                    "pid": os.getpid(),
                    "host": socket.gethostname(),
                    "started_at": utc_now(),
                }
            )
        )
        self._stream.flush()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._stream is None:
            return
        import fcntl

        fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        self._stream.close()
        self._stream = None


@contextmanager
def atomic_output(path: Path, *, binary: bool = False) -> Iterator[Any]:
    """Write a sibling partial and atomically promote it on success."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    mode = "wb" if binary else "w"
    kwargs = {} if binary else {"encoding": "utf-8", "newline": ""}
    with partial.open(mode, **kwargs) as stream:
        yield stream
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(partial, path)
    fsync_directory(path.parent)
