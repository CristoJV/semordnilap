import csv
from dataclasses import replace

import duckdb
import pytest

from semordnilap.ngrams.application import count_corpus
from semordnilap.ngrams.cli.extract import build_argparser, command_from_args
from semordnilap.ngrams.infrastructure import DuckDbNgramCountRepository
from semordnilap.scoring import score_semordnilap_pair
from semordnilap.search.application import FindSemordnilapsCommand, run_search
from semordnilap.search.domain import SearchPolicy, SemordnilapPair
from semordnilap.search.infrastructure import DuckDbSemordnilapSearchRepository


def extract(db_path, path, *, lang, corpus, text):
    path.write_text(text, encoding="utf-8")
    args = build_argparser().parse_args(
        [
            "extract",
            "--input",
            str(path),
            "--format",
            "txt",
            "--lang",
            lang,
            "--corpus",
            corpus,
        ]
    )
    repository = DuckDbNgramCountRepository(db_path)
    count_corpus(command_from_args(args), repository)
    repository.close()


def build_pair_db(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    extract(
        db_path,
        tmp_path / "source.txt",
        lang="es",
        corpus="wiki",
        text="roda roda roda roda roda\n",
    )
    extract(
        db_path,
        tmp_path / "target.txt",
        lang="pt",
        corpus="wiki",
        text="a dor. a dor. a dor. a dor\n",
    )
    return db_path


def test_search_finds_reversed_final_generation_pairs(tmp_path):
    db_path = build_pair_db(tmp_path)
    repository = DuckDbSemordnilapSearchRepository(db_path)
    pairs = list(
        repository.iter_pairs(
            SearchPolicy(
                source_lang="es",
                target_lang="pt",
                source_corpus="wiki",
                target_corpus="wiki",
                min_source_count=1,
                min_target_count=1,
                source_n=1,
                target_n=2,
                min_norm_len=4,
                max_norm_len=4,
            )
        )
    )
    repository.close()
    assert [(pair.source_text, pair.target_text) for pair in pairs] == [
        ("roda", "a dor")
    ]
    assert pairs[0].source_count == 5
    assert pairs[0].target_count == 4
    assert pairs[0].source_dataset_id
    assert pairs[0].target_dataset_id


def test_search_exposes_punctuation_for_each_side(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    extract(
        db_path,
        tmp_path / "source.txt",
        lang="es",
        corpus="wiki",
        text="ro, da\n",
    )
    extract(
        db_path,
        tmp_path / "target.txt",
        lang="pt",
        corpus="wiki",
        text="ador\n",
    )
    repository = DuckDbSemordnilapSearchRepository(db_path)
    pairs = list(
        repository.iter_pairs(
            SearchPolicy(
                source_lang="es",
                target_lang="pt",
                source_corpus="wiki",
                target_corpus="wiki",
                min_source_count=1,
                min_target_count=1,
                source_n=2,
                target_n=1,
            )
        )
    )
    repository.close()
    assert pairs[0].source_has_punctuation is True
    assert pairs[0].target_has_punctuation is False


def test_search_rejects_database_without_generation_schema(tmp_path):
    db_path = tmp_path / "legacy.duckdb"
    connection = duckdb.connect(str(db_path))
    connection.execute("CREATE TABLE ngram_counts(value INTEGER)")
    connection.close()
    with pytest.raises(RuntimeError, match="generation-based"):
        DuckDbSemordnilapSearchRepository(db_path)


def test_search_exports_tsv_with_dataset_ids(tmp_path):
    db_path = build_pair_db(tmp_path)
    out_path = tmp_path / "pairs.tsv"
    command = FindSemordnilapsCommand(
        db_path=db_path,
        output_path=out_path,
        policy=SearchPolicy(
            source_lang="es",
            target_lang="pt",
            source_corpus="wiki",
            target_corpus="wiki",
            min_source_count=1,
            min_target_count=1,
            source_n=1,
            target_n=2,
        ),
    )
    exported = run_search(
        command, DuckDbSemordnilapSearchRepository(db_path)
    )
    with out_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    assert exported == 1
    assert rows[0]["source_dataset_id"]
    assert rows[0]["target_dataset_id"]
    assert float(rows[0]["pair_score"]) == score_semordnilap_pair(5, 4)


def test_pair_ids_are_stable_across_case_counts_and_extractions():
    pair = SemordnilapPair(
        source_lang="es",
        source_corpus="wikisource_20231201",
        source_text="Roda",
        source_n=1,
        source_count=5,
        source_norm_key="roda",
        source_has_punctuation=False,
        target_lang="gl",
        target_corpus="corpusnos",
        target_text="Á dor,",
        target_n=2,
        target_count=4,
        target_norm_key="ador",
        target_has_punctuation=True,
        source_dataset_id="dataset:old-source",
        target_dataset_id="dataset:old-target",
    )
    new_extract = replace(
        pair,
        source_text="RODA",
        target_text="á DOR,",
        source_count=50,
        target_count=40,
        source_dataset_id="dataset:new-source",
        target_dataset_id="dataset:new-target",
    )
    assert new_extract.pair_id == pair.pair_id
    assert new_extract.lexical_pair_id == pair.lexical_pair_id
    assert pair.pair_id == (
        "semordnilap-pair-v1:"
        "9dfdb748d75aa7804431b64573bf0a3a504df64614a5cd2d5a6403dd1525667f"
    )
    assert pair.lexical_pair_id == (
        "semordnilap-lexical-pair-v1:"
        "a6beb15077140390779019b531b3fd7befc38717d6709e2e315983359d969c58"
    )


def test_pair_id_tracks_corpus_but_lexical_pair_id_does_not():
    pair = SemordnilapPair(
        source_lang="es",
        source_corpus="wikisource_20231201",
        source_text="roda",
        source_n=1,
        source_count=5,
        source_norm_key="roda",
        source_has_punctuation=False,
        target_lang="gl",
        target_corpus="wikisource_20231201",
        target_text="a dor",
        target_n=2,
        target_count=4,
        target_norm_key="ador",
        target_has_punctuation=False,
    )
    other_corpus = replace(pair, target_corpus="corpusnos")
    assert other_corpus.pair_id != pair.pair_id
    assert other_corpus.lexical_pair_id == pair.lexical_pair_id


def test_pair_ids_preserve_accents_and_punctuation():
    pair = SemordnilapPair(
        source_lang="es",
        source_corpus="wiki",
        source_text="roda",
        source_n=1,
        source_count=5,
        source_norm_key="roda",
        source_has_punctuation=False,
        target_lang="gl",
        target_corpus="wiki",
        target_text="á dor,",
        target_n=2,
        target_count=4,
        target_norm_key="ador",
        target_has_punctuation=True,
    )
    assert replace(pair, target_text="a dor,").pair_id != pair.pair_id
    assert replace(pair, target_text="á dor").pair_id != pair.pair_id
