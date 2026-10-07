import csv
from collections import Counter
from dataclasses import replace

import duckdb
import pytest

from semordnilap.ngrams.infrastructure import DuckDbNgramCountRepository
from semordnilap.scoring import score_semordnilap_pair
from semordnilap.search.application import FindSemordnilapsCommand, run_search
from semordnilap.search.domain import SearchPolicy, SemordnilapPair
from semordnilap.search.infrastructure import DuckDbSemordnilapSearchRepository


def add_counts(db_path, *, lang, corpus, counts):
    repository = DuckDbNgramCountRepository(db_path)
    repository.add_counts(
        Counter(counts),
        lang=lang,
        corpus=corpus,
        fold_nasal_letters=False,
    )
    repository.close()


def test_search_ngrams_finds_reversed_norm_key_pairs(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    add_counts(
        db_path,
        lang="es",
        corpus="wiki",
        counts={("roda",): 5, ("casa",): 10},
    )
    add_counts(
        db_path,
        lang="pt",
        corpus="wiki",
        counts={("a", "dor"): 7, ("mesa",): 8},
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
            )
        )
    )
    repository.close()

    assert len(pairs) == 1
    assert pairs[0].source_text == "roda"
    assert pairs[0].source_norm_key == "roda"
    assert pairs[0].target_text == "a dor"
    assert pairs[0].target_norm_key == "ador"
    assert pairs[0].source_has_punctuation is False
    assert pairs[0].target_has_punctuation is False


def test_search_ngrams_exposes_punctuation_for_each_side(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    add_counts(db_path, lang="es", corpus="wiki", counts={("roda,",): 5})
    add_counts(db_path, lang="pt", corpus="wiki", counts={("a", "dor"): 7})

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
            )
        )
    )
    repository.close()

    assert len(pairs) == 1
    assert pairs[0].source_text == "roda,"
    assert pairs[0].source_has_punctuation is True
    assert pairs[0].target_has_punctuation is False


def test_search_ngrams_supports_legacy_tables_without_punctuation_column(
    tmp_path,
):
    db_path = tmp_path / "legacy.duckdb"
    connection = duckdb.connect(str(db_path))
    for table in ("ngram_counts", "ngram_totals"):
        connection.execute(
            f"""
            CREATE TABLE {table} (
                lang TEXT,
                corpus TEXT,
                text TEXT,
                n INTEGER,
                count BIGINT,
                norm_key TEXT
            )
            """
        )
    connection.execute(
        """
        CREATE TABLE ngram_compactions (
            lang TEXT,
            corpus TEXT,
            n INTEGER,
            compacted_at TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        INSERT INTO ngram_counts VALUES
            ('es', 'wiki', 'roda', 1, 5, 'roda'),
            ('pt', 'wiki', 'a dor', 2, 7, 'ador')
        """
    )
    connection.close()

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
            )
        )
    )
    repository.close()

    assert len(pairs) == 1
    assert pairs[0].source_has_punctuation is False
    assert pairs[0].target_has_punctuation is False


def test_search_ngrams_aggregates_partial_counts(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    add_counts(db_path, lang="es", corpus="wiki", counts={("roda",): 2})
    add_counts(db_path, lang="es", corpus="wiki", counts={("roda",): 3})
    add_counts(db_path, lang="pt", corpus="wiki", counts={("a", "dor"): 4})

    repository = DuckDbSemordnilapSearchRepository(db_path)
    pairs = list(
        repository.iter_pairs(
            SearchPolicy(
                source_lang="es",
                target_lang="pt",
                source_corpus="wiki",
                target_corpus="wiki",
                min_source_count=5,
                min_target_count=4,
            )
        )
    )
    repository.close()

    assert len(pairs) == 1
    assert pairs[0].source_count == 5
    assert pairs[0].target_count == 4


def test_search_ngrams_exports_tsv(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    out_path = tmp_path / "pairs.tsv"
    add_counts(db_path, lang="es", corpus="wiki", counts={("roda",): 5})
    add_counts(db_path, lang="pt", corpus="wiki", counts={("a", "dor"): 4})

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
        ),
    )
    repository = DuckDbSemordnilapSearchRepository(db_path)

    exported = run_search(command, repository)

    with out_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    assert exported == 1
    assert rows[0]["pair_id"].startswith("semordnilap-pair-v1:")
    assert rows[0]["lexical_pair_id"].startswith(
        "semordnilap-lexical-pair-v1:"
    )
    assert rows[0]["source_dataset_id"] == ""
    assert rows[0]["target_dataset_id"] == ""
    assert rows[0]["source_text"] == "roda"
    assert rows[0]["target_text"] == "a dor"
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


def test_search_ngrams_can_use_compacted_counts_and_filters(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    add_counts(
        db_path,
        lang="es",
        corpus="wiki",
        counts={("roda",): 5, ("la", "casa"): 10},
    )
    add_counts(
        db_path,
        lang="pt",
        corpus="wiki",
        counts={("a", "dor"): 7, ("mesa",): 8},
    )

    counts_repository = DuckDbNgramCountRepository(db_path)
    counts_repository.compact_counts(lang="es", corpus="wiki", n=1)
    counts_repository.compact_counts(lang="pt", corpus="wiki", n=2)
    counts_repository.close()

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
                counts_source="compact",
            )
        )
    )
    repository.close()

    assert len(pairs) == 1
    assert pairs[0].source_text == "roda"
    assert pairs[0].target_text == "a dor"


def test_search_ngrams_reports_missing_compaction(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    add_counts(db_path, lang="es", corpus="wiki", counts={("roda",): 5})
    add_counts(db_path, lang="pt", corpus="wiki", counts={("a", "dor"): 7})

    counts_repository = DuckDbNgramCountRepository(db_path)
    counts_repository.compact_counts(lang="es", corpus="wiki", n=1)
    counts_repository.close()

    repository = DuckDbSemordnilapSearchRepository(db_path)
    with pytest.raises(RuntimeError, match="No compacted target counts"):
        list(
            repository.iter_pairs(
                SearchPolicy(
                    source_lang="es",
                    target_lang="pt",
                    source_corpus="wiki",
                    target_corpus="wiki",
                    counts_source="compact",
                )
            )
        )
    repository.close()
