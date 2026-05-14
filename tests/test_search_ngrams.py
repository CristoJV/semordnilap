import csv
import pytest
from collections import Counter

from semordnilap.ngrams.infrastructure import DuckDbNgramCountRepository
from semordnilap.search.application import FindSemordnilapsCommand, run_search
from semordnilap.search.domain import SearchPolicy
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
    assert rows[0]["source_text"] == "roda"
    assert rows[0]["target_text"] == "a dor"
    assert float(rows[0]["pair_score"]) > 0


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
