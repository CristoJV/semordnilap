from dataclasses import replace

import pytest

from semordnilap.ngrams.application import count_corpus, export_tsv
from semordnilap.ngrams.cli.extract import build_argparser, command_from_args
from semordnilap.ngrams.infrastructure import DuckDbNgramCountRepository
from semordnilap.ngrams.domain import NgramExtractionPolicy
from semordnilap.search.domain import SearchPolicy
from semordnilap.search.infrastructure import DuckDbSemordnilapSearchRepository


def command_for(path, *, corpus="test", max_n=2, flush=100):
    args = build_argparser().parse_args(
        [
            "extract",
            "--input",
            str(path),
            "--format",
            "txt",
            "--lang",
            "es",
            "--corpus",
            corpus,
            "--max-n",
            str(max_n),
            "--flush-unique-ngrams",
            str(flush),
        ]
    )
    return command_from_args(args)


def test_replaying_a_complete_extraction_is_a_noop(tmp_path):
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("La casa\nEl camino\n", encoding="utf-8")
    repository = DuckDbNgramCountRepository(tmp_path / "ngrams.duckdb")
    command = command_for(corpus)

    count_corpus(command, repository)
    before = repository._con.execute(
        "SELECT COUNT(*), SUM(count) FROM ngram_final_v2"
    ).fetchone()
    count_corpus(command, repository)
    after = repository._con.execute(
        "SELECT COUNT(*), SUM(count) FROM ngram_final_v2"
    ).fetchone()

    assert after == before
    assert (
        repository._con.execute(
            "SELECT COUNT(*) FROM extraction_chunks"
        ).fetchone()[0]
        == 2
    )
    repository.close()


def test_chunk_transaction_rolls_back_and_resume_skips_committed_docs(
    tmp_path,
):
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("La casa\nEl camino\n", encoding="utf-8")
    db_path = tmp_path / "ngrams.duckdb"
    repository = DuckDbNgramCountRepository(db_path)
    commits = 0

    def fail_second_commit(point):
        nonlocal commits
        if point == "commit.before_transaction_commit":
            commits += 1
            if commits == 2:
                raise RuntimeError("injected crash")

    repository._fault_injector = fail_second_commit
    with pytest.raises(RuntimeError, match="injected crash"):
        count_corpus(command_for(corpus), repository)
    assert (
        repository._con.execute(
            "SELECT COUNT(*) FROM extraction_chunks"
        ).fetchone()[0]
        == 1
    )
    repository.close()

    repository = DuckDbNgramCountRepository(db_path)
    count_corpus(command_for(corpus), repository)
    rows = list(repository.iter_counts(lang="es", corpus="test", min_count=1))
    assert {row.text for row in rows} >= {"La casa", "El camino"}
    assert (
        repository._con.execute(
            "SELECT COUNT(*) FROM extraction_chunks"
        ).fetchone()[0]
        == 2
    )
    repository.close()


def test_finalization_is_atomic_and_resumable(tmp_path):
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("La casa azul\n", encoding="utf-8")
    db_path = tmp_path / "ngrams.duckdb"
    repository = DuckDbNgramCountRepository(db_path)

    def fail_finalization(point):
        if point == "finalize.before_transaction_commit":
            raise RuntimeError("finalize crash")

    repository._fault_injector = fail_finalization
    with pytest.raises(RuntimeError, match="finalize crash"):
        count_corpus(command_for(corpus), repository)
    assert (
        repository._con.execute(
            "SELECT COUNT(*) FROM ngram_final_v2"
        ).fetchone()[0]
        == 0
    )
    repository.close()

    repository = DuckDbNgramCountRepository(db_path)
    count_corpus(command_for(corpus), repository)
    assert (
        repository._con.execute(
            "SELECT status FROM extraction_datasets"
        ).fetchone()[0]
        == "complete"
    )
    assert (
        repository._con.execute(
            "SELECT COUNT(*) FROM ngram_stage_v2"
        ).fetchone()[0]
        == 0
    )
    repository.close()


def test_pathological_document_flushes_deterministic_bounded_segments(
    tmp_path,
):
    corpus = tmp_path / "corpus.txt"
    corpus.write_text(
        "casa verde camino largo perro negro ventana grande\n",
        encoding="utf-8",
    )
    repository = DuckDbNgramCountRepository(tmp_path / "ngrams.duckdb")

    count_corpus(command_for(corpus, flush=2), repository)

    assert (
        repository._con.execute(
            "SELECT COUNT(*) FROM extraction_chunks"
        ).fetchone()[0]
        > 1
    )
    assert (
        repository._con.execute(
            "SELECT COUNT(*) FROM ngram_stage_v2"
        ).fetchone()[0]
        == 0
    )
    repository.close()


def test_policy_change_creates_distinct_identity_and_ambiguous_alias_fails(
    tmp_path,
):
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("La casa azul\n", encoding="utf-8")
    repository = DuckDbNgramCountRepository(tmp_path / "ngrams.duckdb")
    count_corpus(command_for(corpus, max_n=1), repository)
    count_corpus(command_for(corpus, max_n=2), repository)

    assert (
        repository._con.execute(
            "SELECT COUNT(*) FROM extraction_datasets"
        ).fetchone()[0]
        == 2
    )
    with pytest.raises(ValueError, match="Multiple policy identities"):
        list(repository.iter_counts(lang="es", corpus="test", min_count=1))

    dataset_id = repository._con.execute(
        """
        SELECT dataset_id FROM extraction_datasets
        WHERE json_extract_string(policy_json, '$.max_n') = '1'
        """
    ).fetchone()[0]
    selected = list(
        repository.iter_counts(
            lang="es",
            corpus="test",
            min_count=1,
            dataset_id=dataset_id,
        )
    )
    assert selected
    assert {row.n for row in selected} == {1}
    repository.close()


def test_atomic_export_preserves_previous_final_on_failure(tmp_path):
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("La casa\n", encoding="utf-8")
    db_path = tmp_path / "ngrams.duckdb"
    repository = DuckDbNgramCountRepository(db_path)
    command = command_for(corpus)
    count_corpus(command, repository)
    output = tmp_path / "counts.tsv"
    output.write_text("previous\n", encoding="utf-8")

    original = repository.iter_counts

    def broken_rows(**kwargs):
        yield next(iter(original(**kwargs)))
        raise RuntimeError("export crash")

    repository.iter_counts = broken_rows
    with pytest.raises(RuntimeError, match="export crash"):
        export_tsv(
            replace(command, output_path=output, min_count=1), repository
        )

    assert output.read_text(encoding="utf-8") == "previous\n"
    repository.close()


def test_modern_search_reads_finalized_v2_generations(tmp_path):
    source = tmp_path / "source.txt"
    target = tmp_path / "target.txt"
    source.write_text("roda\n", encoding="utf-8")
    target.write_text("a dor\n", encoding="utf-8")
    db_path = tmp_path / "ngrams.duckdb"
    repository = DuckDbNgramCountRepository(db_path)
    count_corpus(command_for(source, corpus="wiki"), repository)
    target_command = replace(
        command_for(target, corpus="wiki"),
        policy=NgramExtractionPolicy(lang="pt", max_n=2),
    )
    count_corpus(target_command, repository)
    repository.close()

    search = DuckDbSemordnilapSearchRepository(db_path)
    pairs = list(
        search.iter_pairs(
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
    search.close()

    assert [(pair.source_text, pair.target_text) for pair in pairs] == [
        ("roda", "a dor")
    ]


def test_modern_search_can_select_one_of_multiple_policy_identities(tmp_path):
    source = tmp_path / "source.txt"
    target = tmp_path / "target.txt"
    source.write_text("roda\n", encoding="utf-8")
    target.write_text("a dor\n", encoding="utf-8")
    db_path = tmp_path / "ngrams.duckdb"
    repository = DuckDbNgramCountRepository(db_path)
    count_corpus(command_for(source, corpus="wiki", max_n=1), repository)
    count_corpus(command_for(source, corpus="wiki", max_n=2), repository)
    source_dataset_id = repository._con.execute(
        """
        SELECT dataset_id FROM extraction_datasets
        WHERE lang = 'es'
          AND json_extract_string(policy_json, '$.max_n') = '1'
        """
    ).fetchone()[0]
    count_corpus(
        replace(
            command_for(target, corpus="wiki"),
            policy=NgramExtractionPolicy(lang="pt", max_n=2),
        ),
        repository,
    )
    repository.close()

    search = DuckDbSemordnilapSearchRepository(db_path)
    with pytest.raises(ValueError, match="Multiple policy identities"):
        list(
            search.iter_pairs(
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
    pairs = list(
        search.iter_pairs(
            SearchPolicy(
                source_lang="es",
                target_lang="pt",
                source_corpus="wiki",
                target_corpus="wiki",
                min_source_count=1,
                min_target_count=1,
                source_dataset_id=source_dataset_id,
            )
        )
    )
    search.close()
    assert [(pair.source_text, pair.target_text) for pair in pairs] == [
        ("roda", "a dor")
    ]


def test_legacy_database_requires_explicit_migration_and_stats_open_is_read_only(
    tmp_path,
):
    import duckdb

    db_path = tmp_path / "legacy.duckdb"
    connection = duckdb.connect(str(db_path))
    connection.execute(
        """
        CREATE TABLE ngram_counts (
            lang TEXT, corpus TEXT, text TEXT, n INTEGER, count BIGINT,
            norm_key TEXT
        )
        """
    )
    connection.close()

    read_only = DuckDbNgramCountRepository(db_path, read_only=True)
    assert read_only._table_exists("semordnilap_schema") is False
    read_only.close()
    with pytest.raises(RuntimeError, match="explicit migration"):
        DuckDbNgramCountRepository(db_path)

    DuckDbNgramCountRepository.migrate(db_path)
    migrated = DuckDbNgramCountRepository(db_path, read_only=True)
    assert migrated._table_exists("semordnilap_schema") is True
    migrated.close()


def test_migration_command_is_explicitly_available():
    args = build_argparser().parse_args(
        ["db", "migrate", "--db-path", "legacy.duckdb"]
    )
    assert (args.command, args.db_command) == ("db", "migrate")
