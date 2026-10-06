import gzip
import io
import json

import pytest

from semordnilap.corpus import corpusnos as corpusnos_module
from semordnilap.corpus.cli import build_argparser
from semordnilap.corpus.corpusnos import (
    ALL_CONFIGS,
    DEFAULT_SUBSETS,
    selected_configs,
)
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


def test_corpus_cli_requires_and_dispatches_subcommands():
    parser = build_argparser()

    wikisource = parser.parse_args(["wikisource", "--langs", "gl"])
    corpusnos = parser.parse_args(["corpusnos"])

    assert wikisource.corpus == "wikisource"
    assert wikisource.langs == ["gl"]
    assert corpusnos.corpus == "corpusnos"
    assert corpusnos.subsets == list(DEFAULT_SUBSETS)


def test_corpusnos_defaults_to_low_noise_configs():
    args = build_argparser().parse_args(["corpusnos"])

    assert selected_configs(args) == [
        "dta_books",
        "dta_research_articles",
        "dta_press_and_blogs",
        "public_data_press_and_blogs",
        "dta_encyclopedic",
        "public_data_encyclopedic",
    ]
    assert "public_data_web_crawls" not in selected_configs(args)
    assert "public_data_translation_corpora" not in selected_configs(args)


def test_corpusnos_can_select_logical_subsets_or_exact_configs():
    parser = build_argparser()
    subsets = parser.parse_args(
        ["corpusnos", "--subsets", "governmental", "web_contents"]
    )
    exact = parser.parse_args(
        ["corpusnos", "--configs", "public_data_web_crawls"]
    )
    all_subsets = parser.parse_args(["corpusnos", "--subsets", "all"])

    assert selected_configs(subsets) == [
        "dta_governmental",
        "dta_web_contents",
    ]
    assert selected_configs(exact) == ["public_data_web_crawls"]
    assert selected_configs(all_subsets) == list(ALL_CONFIGS)


def test_corpus_export_preserves_optional_corpusnos_metadata(tmp_path):
    artifact = tmp_path / "corpusnos"
    corpusnos_rows = [
        {
            "id": 7,
            "text": "texto galego",
            "num_words": 2,
            "num_tokens": 3,
            "pyplexity_score": 1.25,
            "lang": "gl",
        }
    ]

    export_rows(
        corpusnos_rows,
        artifact,
        identity={**IDENTITY, "config": "dta_books", "lang": "gl"},
        shard_docs=1,
        compression="none",
        resume=False,
    )

    record = json.loads(
        (artifact / "part-00000.jsonl").read_text(encoding="utf-8")
    )
    assert record == {
        "id": 7,
        "url": None,
        "title": None,
        "text": "texto galego",
        "num_words": 2,
        "num_tokens": 3,
        "pyplexity_score": 1.25,
        "lang": "gl",
    }


def test_corpusnos_run_exports_selected_config_and_collection(
    tmp_path, monkeypatch
):
    rows = [{"id": 1, "text": "un documento", "lang": "gl"}]
    monkeypatch.setattr(
        corpusnos_module, "load_hf_dataset", lambda *args, **kwargs: rows
    )
    args = build_argparser().parse_args(
        [
            "corpusnos",
            "--configs",
            "dta_books",
            "--out-dir",
            str(tmp_path),
        ]
    )

    assert corpusnos_module.run(args) == 0

    artifact = tmp_path / "corpusnos_dta_books"
    assert list(iter_texts(artifact, "jsonl")) == ["un documento"]
    collection = read_complete_manifest(tmp_path, verify_checksums=False)
    assert collection["configs"] == ["dta_books"]
    assert collection["artifacts"][0]["config"] == "dta_books"


def test_corpusnos_loader_accepts_different_jsonl_schemas(monkeypatch):
    files = {
        "datasets/proxectonos/corpusnos@main/"
        "data_transfer_agreement/research_articles/a.jsonl": (
            '{"id": 1, "text": "PDF", "tokens": 1, "abstract_gl": "resumo"}\n'
        ),
        "datasets/proxectonos/corpusnos@main/"
        "data_transfer_agreement/research_articles/b.jsonl": (
            '{"doc_id": "doi:2", "text": "XML", "language": "gl", '
            '"authors": [{"name": "A"}]}\n'
        ),
    }

    class FakeApi:
        def list_repo_files(self, *args, **kwargs):
            return [
                "unrelated.jsonl",
                "data_transfer_agreement/research_articles/b.jsonl",
                "data_transfer_agreement/research_articles/a.jsonl",
            ]

    class FakeFilesystem:
        def open(self, path, *args, **kwargs):
            return io.StringIO(files[path])

    monkeypatch.setattr(corpusnos_module, "HfApi", FakeApi)
    monkeypatch.setattr(corpusnos_module, "HfFileSystem", FakeFilesystem)

    loaded = corpusnos_module.load_hf_dataset(
        "proxectonos/corpusnos",
        "dta_research_articles",
        None,
        revision="main",
        streaming=True,
    )

    assert list(corpusnos_module._rows(loaded)) == [
        {
            "id": 1,
            "url": None,
            "title": None,
            "text": "PDF",
            "num_words": None,
            "pyplexity_score": None,
            "lang": None,
            "num_tokens": 1,
        },
        {
            "id": "doi:2",
            "url": None,
            "title": None,
            "text": "XML",
            "num_words": None,
            "pyplexity_score": None,
            "lang": "gl",
            "num_tokens": None,
        },
    ]
