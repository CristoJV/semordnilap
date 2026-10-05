import gzip

import pytest

from semordnilap.corpus.wikisource import export_rows
from semordnilap.utils.artifacts import read_complete_manifest
from semordnilap.utils.io import iter_texts


IDENTITY = {
    "dataset": "fixture",
    "config": "test.es",
    "revision": "abc123",
    "lang": "es",
    "date": "20261004",
    "compression": "gzip",
    "shard_docs": 1,
}


def rows():
    return [
        {"id": "1", "text": "uno", "title": "Uno"},
        {"id": "empty", "text": "   "},
        {"id": "2", "text": "dos", "title": "Dos"},
        {"id": "3", "text": "tres", "title": "Tres"},
    ]


def test_corpus_export_filters_shards_compresses_and_manifests(tmp_path):
    artifact = tmp_path / "corpus"

    manifest = export_rows(
        rows(),
        artifact,
        identity=IDENTITY,
        shard_docs=1,
        compression="gzip",
        resume=False,
    )

    assert manifest["status"] == "complete"
    assert manifest["documents"] == 3
    assert manifest["rejected_documents"] == 1
    assert len(manifest["shards"]) == 3
    assert list(iter_texts(artifact, "jsonl")) == ["uno", "dos", "tres"]
    assert (
        read_complete_manifest(artifact)["artifact_id"]
        == manifest["artifact_id"]
    )
    with gzip.open(
        artifact / "part-00000.jsonl.gz", "rt", encoding="utf-8"
    ) as stream:
        assert '"text": "uno"' in stream.read()


def test_corpus_export_resumes_only_after_committed_shards(tmp_path):
    artifact = tmp_path / "corpus"

    def interrupted():
        yield from rows()[:2]
        raise RuntimeError("network stopped")

    with pytest.raises(RuntimeError, match="network stopped"):
        export_rows(
            interrupted(),
            artifact,
            identity=IDENTITY,
            shard_docs=1,
            compression="gzip",
            resume=False,
        )

    manifest = export_rows(
        rows(),
        artifact,
        identity=IDENTITY,
        shard_docs=1,
        compression="gzip",
        resume=True,
    )

    assert manifest["documents"] == 3
    assert list(iter_texts(artifact, "jsonl")) == ["uno", "dos", "tres"]
