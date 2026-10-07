import json

import pytest

from semordnilap.corpus.wikisource import export_rows
from semordnilap.ngrams.application import count_corpus
from semordnilap.ngrams.cli.extract import build_argparser, command_from_args
from semordnilap.ngrams.infrastructure import DuckDbNgramCountRepository
from semordnilap.utils.artifacts import stable_id, write_json_atomic


def source_artifact(root, name, *, config, lang, texts, date=None):
    path = root / name
    identity = {
        "dataset": (
            "wikimedia/wikisource"
            if date is not None
            else "proxectonos/corpusnos"
        ),
        "config": config,
        "revision": "fixture-revision",
        "lang": lang,
        "compression": "none",
        "shard_docs": 1000,
    }
    if date is not None:
        identity["date"] = date
    manifest = export_rows(
        ({"id": index, "text": text} for index, text in enumerate(texts)),
        path,
        identity=identity,
        shard_docs=1000,
        compression="none",
        resume=False,
    )
    return path, manifest


def source_collection(root, artifacts, *, configs=None):
    value = {
        "schema": "semordnilap.source-collection",
        "schema_version": 1,
        "status": "complete",
        "created_at": "2026-10-05T00:00:00+00:00",
        "artifacts": [
            {
                "artifact_id": manifest["artifact_id"],
                "lang": manifest["lang"],
                **(
                    {"config": manifest["config"]}
                    if configs is not None
                    else {}
                ),
            }
            for manifest in artifacts
        ],
    }
    if configs is not None:
        value["configs"] = configs
        value["dataset"] = "proxectonos/corpusnos"
        value["revision"] = "fixture-revision"
    value["artifact_id"] = stable_id("source-collection", value)
    value["sha256"] = value["artifact_id"].split(":", 1)[1]
    write_json_atomic(root / "manifest.json", value)


def parse_extract(*arguments):
    args = build_argparser().parse_args(["extract", *arguments])
    return command_from_args(args)


def test_wikisource_adapter_selects_requested_collection_language(tmp_path):
    _es_path, es = source_artifact(
        tmp_path,
        "wikisource_es_20231201",
        config="20231201.es",
        lang="es",
        texts=["La casa"],
        date="20231201",
    )
    gl_path, gl = source_artifact(
        tmp_path,
        "wikisource_gl_20231201",
        config="20231201.gl",
        lang="gl",
        texts=["A casa"],
        date="20231201",
    )
    source_collection(tmp_path, [es, gl])

    command = parse_extract(
        "--adapter",
        "wikisource",
        "--input",
        str(tmp_path),
        "--lang",
        "GL",
    )

    assert command.source_adapter == "wikisource"
    assert command.input_path == gl_path
    assert command.input_format == "jsonl"
    assert command.input_files == (gl_path / "part-00000.jsonl",)
    assert command.policy.lang == "gl"
    assert command.corpus == "wikisource_20231201"


def test_corpusnos_adapter_rejects_non_galician_language(tmp_path):
    artifact, _manifest = source_artifact(
        tmp_path,
        "corpusnos_dta_books",
        config="dta_books",
        lang="gl",
        texts=["A casa"],
    )

    with pytest.raises(ValueError, match="only supports --lang gl"):
        parse_extract(
            "--adapter",
            "corpusnos",
            "--input",
            str(artifact),
            "--lang",
            "es",
        )


def test_corpusnos_collection_extracts_only_manifest_artifacts(tmp_path):
    selected_path, selected = source_artifact(
        tmp_path,
        "corpusnos_dta_books",
        config="dta_books",
        lang="gl",
        texts=["Casa galega"],
    )
    source_artifact(
        tmp_path,
        "corpusnos_dta_governmental",
        config="dta_governmental",
        lang="gl",
        texts=["Documento alleo"],
    )
    partial = tmp_path / "corpusnos_dta_research_articles.part"
    partial.mkdir()
    (partial / "part-00000.jsonl").write_text(
        json.dumps({"text": "Ruído parcial"}) + "\n", encoding="utf-8"
    )
    source_collection(tmp_path, [selected], configs=["dta_books"])

    command = parse_extract(
        "--input",
        str(tmp_path),
        "--lang",
        "gl",
        "--max-n",
        "1",
    )

    assert command.source_adapter == "corpusnos"
    assert command.input_path == tmp_path
    assert command.input_files == (selected_path / "part-00000.jsonl",)
    assert command.corpus == "corpusnos"

    repository = DuckDbNgramCountRepository(tmp_path / "ngrams.duckdb")
    count_corpus(command, repository)
    rows = list(
        repository.iter_counts(
            lang="gl", corpus="corpusnos", min_count=1
        )
    )
    policy = repository._con.execute(
        "SELECT policy_json FROM extraction_datasets"
    ).fetchone()[0]
    repository.close()

    assert {row.text for row in rows} == {"Casa", "galega"}
    assert json.loads(policy)["source_adapter"] == "corpusnos"


def test_explicit_corpus_alias_overrides_adapter_default(tmp_path):
    artifact, _manifest = source_artifact(
        tmp_path,
        "corpusnos_dta_books",
        config="dta_books",
        lang="gl",
        texts=["A casa"],
    )

    command = parse_extract(
        "--adapter",
        "corpusnos",
        "--input",
        str(artifact),
        "--lang",
        "gl",
        "--corpus",
        "nos_books",
    )

    assert command.corpus == "nos_books"


def test_existing_generic_raw_cli_remains_compatible(tmp_path):
    source = tmp_path / "plain.txt"
    source.write_text("La casa\n", encoding="utf-8")

    command = parse_extract(
        "--input",
        str(source),
        "--format",
        "txt",
        "--lang",
        "es",
    )

    assert command.source_adapter == "raw"
    assert command.input_files == ()
    assert command.input_format == "txt"
    assert command.corpus == "default"
