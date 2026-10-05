import json

import pytest

from semordnilap.utils.artifacts import (
    ArtifactLock,
    read_complete_manifest,
    sha256_file,
    stable_id,
)


def test_artifact_lock_rejects_a_concurrent_writer(tmp_path):
    target = tmp_path / "artifact"

    with ArtifactLock(target):
        with pytest.raises(RuntimeError, match="locked by another process"):
            with ArtifactLock(target):
                pass


def test_complete_file_manifest_is_checksum_verified(tmp_path):
    artifact = tmp_path / "data.jsonl"
    artifact.write_text("{}\n", encoding="utf-8")
    digest = sha256_file(artifact)
    manifest = {
        "status": "complete",
        "sha256": digest,
        "artifact_id": stable_id("test", {"sha256": digest}),
    }
    artifact.with_suffix(".jsonl.meta.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    assert read_complete_manifest(artifact)["artifact_id"].startswith("test:")
    artifact.write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        read_complete_manifest(artifact)
