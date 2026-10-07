import csv
import json
import logging
from dataclasses import replace

import duckdb
import pytest

from semordnilap.ngrams.application import count_corpus
from semordnilap.ngrams.cli.extract import build_argparser, command_from_args
from semordnilap.ngrams.infrastructure import DuckDbNgramCountRepository
from semordnilap.scoring import score_semordnilap_pair
from semordnilap.search.application import FindSemordnilapsCommand, run_search
from semordnilap.search.cli.find_ngrams import (
    build_argparser as build_search_argparser,
    command_from_args as search_command_from_args,
)
from semordnilap.search.domain import SearchPolicy, SemordnilapPair
from semordnilap.search.infrastructure import DuckDbSemordnilapSearchRepository
from semordnilap.utils.artifacts import manifest_path, sha256_file


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
                filter_min_source_count=1,
                filter_min_target_count=1,
                filter_source_n=1,
                filter_target_n=2,
                filter_min_norm_len=4,
                filter_max_norm_len=4,
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
                filter_min_source_count=1,
                filter_min_target_count=1,
                filter_source_n=2,
                filter_target_n=1,
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


def test_search_exports_tsv_with_dataset_ids(tmp_path, caplog):
    db_path = build_pair_db(tmp_path)
    out_path = tmp_path / "pairs.tsv"
    caplog.set_level(logging.INFO)
    command = FindSemordnilapsCommand(
        db_path=db_path,
        output_path=out_path,
        policy=SearchPolicy(
            source_lang="es",
            target_lang="pt",
            source_corpus="wiki",
            target_corpus="wiki",
            filter_min_source_count=1,
            filter_min_target_count=1,
            filter_source_n=1,
            filter_target_n=2,
        ),
        progress_every=1,
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
    metadata = json.loads(manifest_path(out_path).read_text(encoding="utf-8"))
    assert metadata["sha256"] == sha256_file(out_path)
    assert metadata["rows"] == 1
    assert metadata["selection"]["source"]["dataset_id"]
    assert metadata["combinations"] == [
        {"source_n": 1, "target_n": 2, "rows": 1}
    ]
    assert "Exported 1 semordnilap pairs" in caplog.text
    assert "Pair distribution: source_n=1 target_n=2 rows=1" in caplog.text


def test_search_cli_is_unrestricted_by_default_and_uses_filter_prefixes():
    parser = build_search_argparser()
    help_text = parser.format_help()
    args = parser.parse_args(
        [
            "--dry-run",
            "--src-lang",
            "gl",
            "--tgt-lang",
            "gl",
            "--src-corpus",
            "corpusnos",
            "--tgt-corpus",
            "corpusnos",
        ]
    )
    command = search_command_from_args(args)

    assert command.output_path is None
    assert command.policy.filter_min_source_count == 1
    assert command.policy.filter_min_target_count == 1
    assert command.policy.filter_max_results is None
    assert command.policy.filter_source_n is None
    assert command.policy.filter_target_n is None
    assert command.policy.filter_exclude_palindromes is False
    assert command.policy.filter_exclude_identical_text is False
    for option in (
        "--filter-min-src-count",
        "--filter-min-tgt-count",
        "--filter-src-n",
        "--filter-tgt-n",
        "--filter-min-norm-len",
        "--filter-max-norm-len",
        "--filter-max-results",
        "--filter-exclude-palindromes",
        "--filter-exclude-identical-text",
        "--filter-exclude-punctuation",
        "--filter-exclude-all-stopword-ngrams",
    ):
        assert option in help_text
    for obsolete in (
        "--min-src-count",
        "--src-n",
        "--max-results",
        "--include-palindromes",
        "--include-identical-text",
    ):
        assert obsolete not in help_text


def test_search_cli_requires_output_or_dry_run_and_rejects_magic_zero():
    parser = build_search_argparser()
    required = [
        "--src-lang",
        "gl",
        "--tgt-lang",
        "gl",
        "--src-corpus",
        "corpusnos",
        "--tgt-corpus",
        "corpusnos",
    ]
    with pytest.raises(ValueError, match="--out is required"):
        search_command_from_args(parser.parse_args(required))
    with pytest.raises(ValueError, match="--filter-max-results"):
        search_command_from_args(
            parser.parse_args([*required, "--dry-run", "--filter-max-results", "0"])
        )


def test_default_search_includes_palindromes_and_identical_text(tmp_path):
    db_path = tmp_path / "palindrome.duckdb"
    extract(
        db_path,
        tmp_path / "palindrome.txt",
        lang="gl",
        corpus="test",
        text="aba\n",
    )
    policy = SearchPolicy(
        source_lang="gl",
        target_lang="gl",
        source_corpus="test",
        target_corpus="test",
    )
    repository = DuckDbSemordnilapSearchRepository(db_path)
    assert [
        (pair.source_text, pair.target_text)
        for pair in repository.iter_pairs(policy)
    ] == [("aba", "aba")]
    repository.close()

    repository = DuckDbSemordnilapSearchRepository(db_path)
    assert list(
        repository.iter_pairs(replace(policy, filter_exclude_palindromes=True))
    ) == []
    repository.close()

    repository = DuckDbSemordnilapSearchRepository(db_path)
    assert list(
        repository.iter_pairs(
            replace(policy, filter_exclude_identical_text=True)
        )
    ) == []
    repository.close()


def test_search_filters_punctuation_and_all_stopword_ngrams(tmp_path):
    punctuation_db = tmp_path / "punctuation.duckdb"
    extract(
        punctuation_db,
        tmp_path / "punctuation-source.txt",
        lang="es",
        corpus="source",
        text="ro, da\n",
    )
    extract(
        punctuation_db,
        tmp_path / "punctuation-target.txt",
        lang="pt",
        corpus="target",
        text="ador\n",
    )
    punctuation_policy = SearchPolicy(
        source_lang="es",
        target_lang="pt",
        source_corpus="source",
        target_corpus="target",
        filter_source_n=2,
        filter_target_n=1,
    )
    repository = DuckDbSemordnilapSearchRepository(punctuation_db)
    assert list(repository.iter_pairs(punctuation_policy))
    repository.close()
    repository = DuckDbSemordnilapSearchRepository(punctuation_db)
    assert list(
        repository.iter_pairs(
            replace(punctuation_policy, filter_exclude_punctuation=True)
        )
    ) == []
    repository.close()

    stopword_db = tmp_path / "stopwords.duckdb"
    extract(
        stopword_db,
        tmp_path / "stopwords.txt",
        lang="gl",
        corpus="test",
        text="de a. a ed\n",
    )
    stopword_policy = SearchPolicy(
        source_lang="gl",
        target_lang="gl",
        source_corpus="test",
        target_corpus="test",
        filter_source_n=2,
        filter_target_n=2,
    )
    repository = DuckDbSemordnilapSearchRepository(stopword_db)
    assert any(
        pair.source_norm_key == "dea" and pair.target_norm_key == "aed"
        for pair in repository.iter_pairs(stopword_policy)
    )
    repository.close()
    repository = DuckDbSemordnilapSearchRepository(stopword_db)
    assert not any(
        pair.source_norm_key == "dea" or pair.target_norm_key == "dea"
        for pair in repository.iter_pairs(
            replace(
                stopword_policy,
                filter_exclude_all_stopword_ngrams=True,
            )
        )
    )
    repository.close()


def test_search_dry_run_estimates_without_writing_output(tmp_path, caplog):
    db_path = build_pair_db(tmp_path)
    caplog.set_level(logging.INFO)
    command = FindSemordnilapsCommand(
        db_path=db_path,
        output_path=None,
        dry_run=True,
        policy=SearchPolicy(
            source_lang="es",
            target_lang="pt",
            source_corpus="wiki",
            target_corpus="wiki",
            filter_source_n=1,
            filter_target_n=2,
        ),
    )
    estimated = run_search(
        command, DuckDbSemordnilapSearchRepository(db_path)
    )
    assert estimated == 1
    assert "Dry-run candidates:" in caplog.text
    assert "source_n=1 target_n=2 pairs=1" in caplog.text


def test_result_limit_is_absent_by_default_and_applied_when_requested(tmp_path):
    db_path = tmp_path / "multiple.duckdb"
    extract(
        db_path,
        tmp_path / "multiple-source.txt",
        lang="es",
        corpus="source",
        text="roda casa\n",
    )
    extract(
        db_path,
        tmp_path / "multiple-target.txt",
        lang="pt",
        corpus="target",
        text="a dor. asac\n",
    )
    policy = SearchPolicy(
        source_lang="es",
        target_lang="pt",
        source_corpus="source",
        target_corpus="target",
        filter_source_n=1,
    )
    repository = DuckDbSemordnilapSearchRepository(db_path)
    unlimited = list(repository.iter_pairs(policy))
    repository.close()
    repository = DuckDbSemordnilapSearchRepository(db_path)
    limited = list(
        repository.iter_pairs(replace(policy, filter_max_results=1))
    )
    repository.close()
    assert len(unlimited) == 2
    assert len(limited) == 1


def test_search_export_is_atomic_on_failure(tmp_path):
    db_path = build_pair_db(tmp_path)
    output = tmp_path / "pairs.tsv"
    output.write_text("previous\n", encoding="utf-8")
    repository = DuckDbSemordnilapSearchRepository(db_path)
    original = repository.iter_pairs

    def broken_pairs(policy):
        yield next(iter(original(policy)))
        raise RuntimeError("search export crash")

    repository.iter_pairs = broken_pairs
    command = FindSemordnilapsCommand(
        db_path=db_path,
        output_path=output,
        policy=SearchPolicy(
            source_lang="es",
            target_lang="pt",
            source_corpus="wiki",
            target_corpus="wiki",
            filter_source_n=1,
            filter_target_n=2,
        ),
    )
    with pytest.raises(RuntimeError, match="search export crash"):
        run_search(command, repository)
    assert output.read_text(encoding="utf-8") == "previous\n"


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
