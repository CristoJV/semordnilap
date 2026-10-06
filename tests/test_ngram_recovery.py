from dataclasses import replace

import duckdb
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
    connection.execute(
        "INSERT INTO ngram_counts VALUES ('gl', 'legacy', 'a casa', 2, 7, 'acasa')"
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
    assert migrated.schema_version == 3
    assert migrated._con.execute(
        "SELECT text, count, has_punctuation FROM ngram_counts"
    ).fetchall() == [("a casa", 7, False)]
    assert all(
        not migrated._table_exists(table)
        for table in (
            "ngram_upos_counts",
            "ngram_upos_totals",
            "ngram_upos_stage_v2",
            "ngram_upos_final_v2",
        )
    )
    migrated.close()

    DuckDbNgramCountRepository.migrate(db_path)
    migrated_again = DuckDbNgramCountRepository(db_path, read_only=True)
    assert migrated_again._con.execute(
        "SELECT text, count, has_punctuation FROM ngram_counts"
    ).fetchall() == [("a casa", 7, False)]
    migrated_again.close()


def test_v2_migration_preserves_textual_generations_and_drops_upos(tmp_path):
    db_path = tmp_path / "v2.duckdb"
    connection = duckdb.connect(str(db_path))
    connection.execute(
        """
        CREATE TABLE semordnilap_schema (
            version INTEGER PRIMARY KEY, applied_at TIMESTAMP NOT NULL
        );
        INSERT INTO semordnilap_schema VALUES (2, current_timestamp);
        CREATE TABLE ngram_final_v2 (
            dataset_id TEXT, generation INTEGER, surface_key TEXT,
            surface_display TEXT, n INTEGER, count BIGINT, norm_key TEXT,
            has_punctuation BOOLEAN
        );
        INSERT INTO ngram_final_v2 VALUES
            ('dataset', 1, 'casa, azul', 'casa, azul', 2, 11,
             'casaazul', true);
        CREATE TABLE ngram_upos_counts (value INTEGER);
        CREATE TABLE ngram_upos_totals (value INTEGER);
        CREATE TABLE ngram_upos_stage_v2 (value INTEGER);
        CREATE TABLE ngram_upos_final_v2 (value INTEGER);
        INSERT INTO ngram_upos_counts VALUES (1);
        """
    )
    connection.close()

    with pytest.raises(RuntimeError, match="explicit migration"):
        DuckDbNgramCountRepository(db_path)

    DuckDbNgramCountRepository.migrate(db_path)
    migrated = DuckDbNgramCountRepository(db_path, read_only=True)

    assert migrated.schema_version == 3
    assert migrated._con.execute(
        """
        SELECT dataset_id, surface_display, count, has_punctuation
        FROM ngram_final_v2
        """
    ).fetchall() == [("dataset", "casa, azul", 11, True)]
    assert all(
        not migrated._table_exists(table)
        for table in (
            "ngram_upos_counts",
            "ngram_upos_totals",
            "ngram_upos_stage_v2",
            "ngram_upos_final_v2",
        )
    )
    migrated.close()


def test_v2_migration_rolls_back_all_changes_on_failure(tmp_path, monkeypatch):
    db_path = tmp_path / "v2-failure.duckdb"
    connection = duckdb.connect(str(db_path))
    connection.execute(
        """
        CREATE TABLE semordnilap_schema (
            version INTEGER PRIMARY KEY, applied_at TIMESTAMP NOT NULL
        );
        INSERT INTO semordnilap_schema VALUES (2, current_timestamp);
        CREATE TABLE ngram_counts (
            lang TEXT, corpus TEXT, text TEXT, n INTEGER, count BIGINT,
            norm_key TEXT
        );
        INSERT INTO ngram_counts VALUES
            ('gl', 'legacy', 'a casa', 2, 5, 'acasa');
        CREATE TABLE ngram_upos_counts (value INTEGER);
        INSERT INTO ngram_upos_counts VALUES (1)
        """
    )
    connection.close()

    def fail_version_record(_self, _version):
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(
        DuckDbNgramCountRepository,
        "_record_schema_version",
        fail_version_record,
    )
    with pytest.raises(RuntimeError, match="injected migration failure"):
        DuckDbNgramCountRepository.migrate(db_path)

    connection = duckdb.connect(str(db_path), read_only=True)
    assert (
        connection.execute(
            "SELECT MAX(version) FROM semordnilap_schema"
        ).fetchone()[0]
        == 2
    )
    assert connection.execute(
        "SELECT text, count FROM ngram_counts"
    ).fetchall() == [("a casa", 5)]
    assert (
        connection.execute(
            """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_name = 'ngram_upos_counts'
        """
        ).fetchone()[0]
        == 1
    )
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info('ngram_counts')"
        ).fetchall()
    }
    assert "has_punctuation" not in columns
    connection.close()


def test_future_database_schema_is_rejected(tmp_path):
    db_path = tmp_path / "future.duckdb"
    connection = duckdb.connect(str(db_path))
    connection.execute(
        """
        CREATE TABLE semordnilap_schema (
            version INTEGER PRIMARY KEY, applied_at TIMESTAMP NOT NULL
        );
        INSERT INTO semordnilap_schema VALUES (99, current_timestamp)
        """
    )
    connection.close()

    with pytest.raises(RuntimeError, match="newer than the supported version"):
        DuckDbNgramCountRepository(db_path, read_only=True)


def test_migration_command_is_explicitly_available():
    args = build_argparser().parse_args(
        ["db", "migrate", "--db-path", "legacy.duckdb"]
    )
    assert (args.command, args.db_command) == ("db", "migrate")
