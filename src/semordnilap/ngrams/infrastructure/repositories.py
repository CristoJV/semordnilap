"""Infrastructure adapters for n-gram storage."""

from __future__ import annotations

import logging
import csv
import json
import tempfile
from collections import Counter
from pathlib import Path
from time import perf_counter

from semordnilap.ngrams.domain import (
    ExtractedNgram,
    NgramCount,
    NgramKey,
    build_ngram_count,
)

logger = logging.getLogger(__name__)
INSERT_BATCH_SIZE = 50_000
CURRENT_SCHEMA_VERSION = 3
RAW_COUNTS_TABLE = "ngram_counts"
TOTAL_COUNTS_TABLE = "ngram_totals"
V2_FINAL_TABLE = "ngram_final_v2"
REMOVED_UPOS_TABLES = (
    "ngram_upos_counts",
    "ngram_upos_totals",
    "ngram_upos_stage_v2",
    "ngram_upos_final_v2",
)


class DuckDbNgramCountRepository:
    generation_storage = True

    def __init__(
        self,
        db_path: Path,
        *,
        read_only: bool = False,
        allow_migrate: bool = False,
    ) -> None:
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError(
                "DuckDB backend requires `duckdb`. Install it with "
                "`uv add duckdb`, then rerun the command."
            ) from exc

        existed = db_path.exists()
        if not read_only:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Opening DuckDB database at %s", db_path)
        self._tmp_dir = db_path.parent
        self._db_path = db_path
        self._fault_injector = None
        self._con = duckdb.connect(str(db_path), read_only=read_only)
        self._schema_version = self._read_schema_version()
        if self._schema_version > CURRENT_SCHEMA_VERSION:
            self._con.close()
            raise RuntimeError(
                f"DuckDB schema version {self._schema_version} is newer than "
                f"the supported version {CURRENT_SCHEMA_VERSION}"
            )
        self._has_generation_schema = self._table_exists("extraction_datasets")
        if not read_only:
            if (
                existed
                and self._schema_version < CURRENT_SCHEMA_VERSION
                and not allow_migrate
            ):
                self._con.close()
                raise RuntimeError(
                    f"DuckDB schema version {self._schema_version} requires "
                    "explicit migration: "
                    f"sp_ngrams db migrate --db-path {db_path}"
                )
            if allow_migrate:
                self._migrate_to_current()
            else:
                self._create_schema_v3()
            self._has_generation_schema = True
            self._schema_version = CURRENT_SCHEMA_VERSION

    def _table_exists(self, table: str) -> bool:
        return bool(
            self._con.execute(
                """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_name = ?
                """,
                [table],
            ).fetchone()[0]
        )

    def _read_schema_version(self) -> int:
        if not self._table_exists("semordnilap_schema"):
            return 0
        row = self._con.execute(
            "SELECT MAX(version) FROM semordnilap_schema"
        ).fetchone()
        return int(row[0] or 0)

    @property
    def schema_version(self) -> int:
        return self._schema_version

    @classmethod
    def migrate(cls, db_path: Path) -> None:
        repository = cls(db_path, allow_migrate=True)
        repository.close()

    def _fault(self, point: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(point)

    def _create_schema_v3(self) -> None:
        self._con.execute("BEGIN TRANSACTION")
        try:
            self._ensure_text_tables()
            self._ensure_generation_tables()
            self._record_schema_version(CURRENT_SCHEMA_VERSION)
            self._con.execute("COMMIT")
        except Exception:
            self._con.execute("ROLLBACK")
            raise

    def _migrate_to_current(self) -> None:
        if self._schema_version == CURRENT_SCHEMA_VERSION:
            return
        self._con.execute("BEGIN TRANSACTION")
        try:
            self._ensure_text_tables()
            self._ensure_generation_tables()
            for table in REMOVED_UPOS_TABLES:
                self._con.execute(f"DROP TABLE IF EXISTS {table}")
            self._record_schema_version(CURRENT_SCHEMA_VERSION)
            self._con.execute("COMMIT")
        except Exception:
            self._con.execute("ROLLBACK")
            raise

    def _record_schema_version(self, version: int) -> None:
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS semordnilap_schema (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL
            )
            """
        )
        self._con.execute(
            """
            INSERT INTO semordnilap_schema
            SELECT ?, current_timestamp
            WHERE NOT EXISTS (
                SELECT 1 FROM semordnilap_schema WHERE version = ?
            )
            """,
            [version, version],
        )

    def _ensure_text_tables(self) -> None:
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS ngram_counts (
                lang TEXT NOT NULL,
                corpus TEXT NOT NULL,
                text TEXT NOT NULL,
                n INTEGER NOT NULL,
                count BIGINT NOT NULL,
                norm_key TEXT NOT NULL,
                has_punctuation BOOLEAN NOT NULL DEFAULT false
            )
            """
        )
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS ngram_totals (
                lang TEXT NOT NULL,
                corpus TEXT NOT NULL,
                text TEXT NOT NULL,
                n INTEGER NOT NULL,
                count BIGINT NOT NULL,
                norm_key TEXT NOT NULL,
                has_punctuation BOOLEAN NOT NULL DEFAULT false
            )
            """
        )
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS ngram_compactions (
                lang TEXT NOT NULL,
                corpus TEXT NOT NULL,
                n INTEGER NOT NULL,
                compacted_at TIMESTAMP NOT NULL
            )
            """
        )
        # DuckDB rewrites an existing column to its default when ADD COLUMN IF
        # NOT EXISTS is repeated, so inspect the schema before migrating.
        for table in (RAW_COUNTS_TABLE, TOTAL_COUNTS_TABLE):
            columns = {
                row[1]
                for row in self._con.execute(
                    f"PRAGMA table_info('{table}')"
                ).fetchall()
            }
            if "has_punctuation" not in columns:
                self._con.execute(
                    f"""
                    ALTER TABLE {table}
                    ADD COLUMN has_punctuation BOOLEAN DEFAULT false
                    """
                )

    def prepare_extraction(
        self,
        *,
        dataset_id: str,
        run_id: str,
        artifact_id: str,
        policy_hash: str,
        lang: str,
        corpus: str,
        input_format: str,
        policy: dict,
        sample: bool,
        restart: bool,
    ) -> dict:
        if restart:
            self._delete_v2_dataset(dataset_id)
        row = self._con.execute(
            """
            SELECT status, active_generation
            FROM extraction_datasets
            WHERE dataset_id = ?
            """,
            [dataset_id],
        ).fetchone()
        if row and row[0] == "complete":
            return {
                "status": "complete",
                "completed_documents": self._run_completed_documents(run_id),
            }
        if not row:
            self._con.execute("BEGIN TRANSACTION")
            try:
                self._con.execute(
                    """
                    INSERT INTO extraction_datasets VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, 'in_progress', NULL,
                        current_timestamp, NULL
                    )
                    """,
                    [
                        dataset_id,
                        artifact_id,
                        policy_hash,
                        lang,
                        corpus,
                        input_format,
                        json.dumps(policy, sort_keys=True),
                        sample,
                    ],
                )
                self._con.execute(
                    """
                    INSERT INTO extraction_runs VALUES (
                        ?, ?, 'in_progress', 0, 0, 0, current_timestamp
                    )
                    """,
                    [run_id, dataset_id],
                )
                self._con.execute("COMMIT")
            except Exception:
                self._con.execute("ROLLBACK")
                raise
        return {
            "status": "in_progress",
            "completed_documents": self._run_completed_documents(run_id),
        }

    def _run_completed_documents(self, run_id: str) -> int:
        row = self._con.execute(
            """
            SELECT completed_documents FROM extraction_runs WHERE run_id = ?
            """,
            [run_id],
        ).fetchone()
        return int(row[0]) if row else 0

    def _delete_v2_dataset(self, dataset_id: str) -> None:
        self._con.execute("BEGIN TRANSACTION")
        try:
            for table in (
                "ngram_stage_v2",
                V2_FINAL_TABLE,
                "extraction_chunks",
            ):
                self._con.execute(
                    f"DELETE FROM {table} WHERE dataset_id = ?", [dataset_id]
                )
            self._con.execute(
                """
                DELETE FROM extraction_runs WHERE dataset_id = ?
                """,
                [dataset_id],
            )
            self._con.execute(
                """
                DELETE FROM extraction_datasets WHERE dataset_id = ?
                """,
                [dataset_id],
            )
            self._con.execute("COMMIT")
        except Exception:
            self._con.execute("ROLLBACK")
            raise

    def commit_extraction_chunk(
        self,
        *,
        dataset_id: str,
        run_id: str,
        chunk_id: str,
        digest: str,
        document_ordinal: int,
        segment: int,
        final_segment: bool,
        counts: Counter[NgramKey],
        lang: str,
        corpus: str,
        fold_nasal_letters: bool,
    ) -> bool:
        existing = self._con.execute(
            """
            SELECT digest FROM extraction_chunks
            WHERE dataset_id = ? AND chunk_id = ?
            """,
            [dataset_id, chunk_id],
        ).fetchone()
        if existing:
            if existing[0] != digest:
                raise ValueError(
                    f"Committed chunk {chunk_id} has a different digest"
                )
            return False

        base_counts: Counter[ExtractedNgram] = Counter()
        for key, count in counts.items():
            if isinstance(key, ExtractedNgram):
                base_counts[key] += count
            else:
                base_counts[
                    ExtractedNgram(tuple(key), " ".join(key), " ".join(key))
                ] += count

        base_rows = []
        for key, count in base_counts.items():
            row = build_ngram_count(
                key,
                count=count,
                lang=lang,
                corpus=corpus,
                fold_nasal_letters=fold_nasal_letters,
            )
            base_rows.append(
                (
                    dataset_id,
                    chunk_id,
                    key.surface_key,
                    key.surface_display or key.surface_key,
                    row.n,
                    row.count,
                    row.norm_key,
                    row.has_punctuation,
                )
            )

        occurrences = sum(base_counts.values())
        self._con.execute("BEGIN TRANSACTION")
        try:
            if base_rows:
                self._copy_rows(
                    "ngram_stage_v2",
                    (
                        "dataset_id",
                        "chunk_id",
                        "surface_key",
                        "surface_display",
                        "n",
                        "count",
                        "norm_key",
                        "has_punctuation",
                    ),
                    base_rows,
                )
            self._fault("commit.after_base_counts")
            self._con.execute(
                """
                INSERT INTO extraction_chunks VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp
                )
                """,
                [
                    dataset_id,
                    chunk_id,
                    digest,
                    document_ordinal,
                    segment,
                    final_segment,
                    occurrences,
                    len(base_rows),
                ],
            )
            self._fault("commit.after_chunk_ledger")
            self._con.execute(
                """
                UPDATE extraction_runs
                SET completed_documents = CASE
                        WHEN ? THEN greatest(completed_documents, ?)
                        ELSE completed_documents END,
                    generated_occurrences = generated_occurrences + ?,
                    committed_chunks = committed_chunks + 1,
                    updated_at = current_timestamp
                WHERE run_id = ?
                """,
                [final_segment, document_ordinal, occurrences, run_id],
            )
            self._fault("commit.before_transaction_commit")
            self._con.execute("COMMIT")
        except Exception:
            self._con.execute("ROLLBACK")
            raise
        return True

    def finalize_extraction(
        self, *, dataset_id: str, run_id: str, retain_staging: bool = False
    ) -> int:
        dataset = self._con.execute(
            """
            SELECT status, active_generation
            FROM extraction_datasets WHERE dataset_id = ?
            """,
            [dataset_id],
        ).fetchone()
        if not dataset:
            raise ValueError(f"Unknown extraction dataset: {dataset_id}")
        if dataset[0] == "complete":
            return self._count_v2_final_rows(dataset_id)
        generation = int(dataset[1] or 0) + 1
        self._con.execute("BEGIN TRANSACTION")
        try:
            self._con.execute(
                f"DELETE FROM {V2_FINAL_TABLE} WHERE dataset_id = ?",
                [dataset_id],
            )
            self._con.execute(
                f"""
                INSERT INTO {V2_FINAL_TABLE}
                SELECT dataset_id, ?, surface_key,
                       arg_min(surface_display, chunk_id), n, SUM(count),
                       any_value(norm_key), bool_or(has_punctuation)
                FROM ngram_stage_v2
                WHERE dataset_id = ?
                GROUP BY dataset_id, surface_key, n
                """,
                [generation, dataset_id],
            )
            self._fault("finalize.after_final_counts")
            self._fault("finalize.after_validation")
            self._con.execute(
                """
                UPDATE extraction_datasets
                SET status = 'complete', active_generation = ?,
                    completed_at = current_timestamp
                WHERE dataset_id = ?
                """,
                [generation, dataset_id],
            )
            self._con.execute(
                """
                UPDATE extraction_runs
                SET status = 'complete', updated_at = current_timestamp
                WHERE run_id = ?
                """,
                [run_id],
            )
            if not retain_staging:
                self._con.execute(
                    "DELETE FROM ngram_stage_v2 WHERE dataset_id = ?",
                    [dataset_id],
                )
            self._fault("finalize.before_transaction_commit")
            self._con.execute("COMMIT")
        except Exception:
            self._con.execute("ROLLBACK")
            raise
        return self._count_v2_final_rows(dataset_id)

    def _count_v2_final_rows(self, dataset_id: str) -> int:
        return int(
            self._con.execute(
                f"SELECT COUNT(*) FROM {V2_FINAL_TABLE} WHERE dataset_id = ?",
                [dataset_id],
            ).fetchone()[0]
        )

    def _ensure_generation_tables(self) -> None:
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS extraction_datasets (
                dataset_id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL,
                policy_hash TEXT NOT NULL,
                lang TEXT NOT NULL,
                corpus TEXT NOT NULL,
                input_format TEXT NOT NULL,
                policy_json TEXT NOT NULL,
                sample BOOLEAN NOT NULL,
                status TEXT NOT NULL,
                active_generation INTEGER,
                created_at TIMESTAMP NOT NULL,
                completed_at TIMESTAMP
            )
            """
        )
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS extraction_runs (
                run_id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL,
                status TEXT NOT NULL,
                completed_documents BIGINT NOT NULL DEFAULT 0,
                generated_occurrences BIGINT NOT NULL DEFAULT 0,
                committed_chunks BIGINT NOT NULL DEFAULT 0,
                updated_at TIMESTAMP NOT NULL
            )
            """
        )
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS extraction_chunks (
                dataset_id TEXT NOT NULL,
                chunk_id TEXT NOT NULL,
                digest TEXT NOT NULL,
                document_ordinal BIGINT NOT NULL,
                segment INTEGER NOT NULL,
                final_segment BOOLEAN NOT NULL,
                occurrences BIGINT NOT NULL,
                unique_ngrams BIGINT NOT NULL,
                committed_at TIMESTAMP NOT NULL,
                PRIMARY KEY(dataset_id, chunk_id)
            )
            """
        )
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS ngram_stage_v2 (
                dataset_id TEXT NOT NULL,
                chunk_id TEXT NOT NULL,
                surface_key TEXT NOT NULL,
                surface_display TEXT NOT NULL,
                n INTEGER NOT NULL,
                count BIGINT NOT NULL,
                norm_key TEXT NOT NULL,
                has_punctuation BOOLEAN NOT NULL
            )
            """
        )
        self._con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {V2_FINAL_TABLE} (
                dataset_id TEXT NOT NULL,
                generation INTEGER NOT NULL,
                surface_key TEXT NOT NULL,
                surface_display TEXT NOT NULL,
                n INTEGER NOT NULL,
                count BIGINT NOT NULL,
                norm_key TEXT NOT NULL,
                has_punctuation BOOLEAN NOT NULL
            )
            """
        )

    def add_counts(
        self,
        counts: Counter[NgramKey],
        *,
        lang: str,
        corpus: str,
        fold_nasal_letters: bool,
    ) -> None:
        if not counts:
            return

        started_at = perf_counter()
        total = len(counts)
        logger.info(
            "Appending %d unique n-gram counts for lang=%s corpus=%s",
            total,
            lang,
            corpus,
        )

        batch = []
        persisted = 0
        for ngram, count in counts.items():
            row = build_ngram_count(
                ngram,
                count=count,
                lang=lang,
                corpus=corpus,
                fold_nasal_letters=fold_nasal_letters,
            )
            batch.append(
                (
                    row.lang,
                    row.corpus,
                    row.text,
                    row.n,
                    row.count,
                    row.norm_key,
                    row.has_punctuation,
                )
            )
            if len(batch) >= INSERT_BATCH_SIZE:
                self._insert_batch(batch)
                persisted += len(batch)
                logger.info("Appended %d/%d n-gram counts", persisted, total)
                batch.clear()

        if batch:
            self._insert_batch(batch)
            persisted += len(batch)
            logger.info("Appended %d/%d n-gram counts", persisted, total)

        self._invalidate_compactions(
            lang=lang,
            corpus=corpus,
            n_values={
                len(ngram.tokens)
                if isinstance(ngram, ExtractedNgram)
                else len(ngram)
                for ngram in counts
            },
        )
        logger.info(
            "Appended %d n-gram counts in %.2fs",
            total,
            perf_counter() - started_at,
        )

    def _insert_batch(self, rows: list[tuple]) -> None:
        self._copy_rows(
            "ngram_counts",
            (
                "lang",
                "corpus",
                "text",
                "n",
                "count",
                "norm_key",
                "has_punctuation",
            ),
            rows,
        )

    def _copy_rows(
        self,
        table: str,
        columns: tuple[str, ...],
        rows: list[tuple],
    ) -> None:
        """Bulk-load rows through a temporary TSV inside the caller's txn."""
        if not rows:
            return
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            suffix=".tsv",
            dir=self._tmp_dir,
            delete=False,
        ) as f:
            tmp_path = Path(f.name)
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            writer.writerows(rows)

        escaped_path = str(tmp_path).replace("'", "''")
        column_list = ", ".join(columns)
        try:
            self._con.execute(
                f"""
                COPY {table}({column_list})
                FROM '{escaped_path}'
                (FORMAT CSV, DELIMITER '\t', HEADER false)
                """
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    def _invalidate_compactions(
        self, *, lang: str, corpus: str, n_values: set[int]
    ) -> None:
        if not n_values:
            return
        placeholders = ", ".join("?" for _ in n_values)
        params = [lang, corpus, *sorted(n_values)]
        self._con.execute(
            f"""
            DELETE FROM ngram_totals
            WHERE lang = ? AND corpus = ? AND n IN ({placeholders})
            """,
            params,
        )
        self._con.execute(
            f"""
            DELETE FROM ngram_compactions
            WHERE lang = ? AND corpus = ? AND n IN ({placeholders})
            """,
            params,
        )
        logger.info(
            "Invalidated compacted totals for lang=%s corpus=%s n=%s",
            lang,
            corpus,
            ",".join(str(n) for n in sorted(n_values)),
        )

    def _resolve_v2_dataset(
        self, *, lang: str, corpus: str, dataset_id: str | None = None
    ):
        if not self._has_generation_schema:
            if dataset_id:
                raise ValueError(
                    "dataset_id requires a generation-based database schema"
                )
            return None
        if dataset_id:
            row = self._con.execute(
                """
                SELECT dataset_id, status, active_generation
                FROM extraction_datasets
                WHERE dataset_id = ? AND lang = ? AND corpus = ?
                """,
                [dataset_id, lang, corpus],
            ).fetchone()
            if not row:
                raise ValueError(
                    f"Dataset {dataset_id!r} does not match {lang}/{corpus}"
                )
            return row
        rows = self._con.execute(
            """
            SELECT dataset_id, status, active_generation
            FROM extraction_datasets
            WHERE lang = ? AND corpus = ?
            ORDER BY created_at DESC
            """,
            [lang, corpus],
        ).fetchall()
        if len(rows) > 1:
            raise ValueError(
                f"Multiple policy identities exist for {lang}/{corpus}; "
                "select a dataset_id explicitly"
            )
        return rows[0] if rows else None

    def _iter_v2_counts(
        self,
        *,
        dataset_id: str,
        generation: int,
        lang: str,
        corpus: str,
        min_count: int,
        max_results: int,
        export_n: int,
        min_norm_len: int,
        max_norm_len: int,
    ):
        where = ["dataset_id = ?", "generation = ?", "count >= ?"]
        params: list = [dataset_id, generation, min_count]
        if export_n:
            where.append("n = ?")
            params.append(export_n)
        if min_norm_len:
            where.append("length(norm_key) >= ?")
            params.append(min_norm_len)
        if max_norm_len:
            where.append("length(norm_key) <= ?")
            params.append(max_norm_len)
        limit = f"LIMIT {max_results}" if max_results else ""
        result = self._con.execute(
            f"""
            SELECT surface_display, n, count, norm_key, has_punctuation
            FROM {V2_FINAL_TABLE}
            WHERE {" AND ".join(where)}
            ORDER BY count DESC, surface_key ASC
            {limit}
            """,
            params,
        )
        while row := result.fetchone():
            yield NgramCount(
                lang=lang,
                corpus=corpus,
                text=row[0],
                n=row[1],
                count=row[2],
                norm_key=row[3],
                has_punctuation=row[4],
            )

    def iter_counts(
        self,
        *,
        lang: str,
        corpus: str,
        min_count: int,
        max_results: int = 0,
        export_n: int = 0,
        min_norm_len: int = 0,
        max_norm_len: int = 0,
        source: str = "auto",
        dataset_id: str | None = None,
    ):
        v2_dataset = self._resolve_v2_dataset(
            lang=lang, corpus=corpus, dataset_id=dataset_id
        )
        if v2_dataset:
            dataset_id, status, generation = v2_dataset
            if status != "complete" or generation is None:
                raise RuntimeError(
                    f"Extraction dataset is not complete: {dataset_id}"
                )
            if source == "raw":
                raise RuntimeError(
                    "Raw staging was retired after generation finalization"
                )
            yield from self._iter_v2_counts(
                dataset_id=dataset_id,
                generation=generation,
                lang=lang,
                corpus=corpus,
                min_count=min_count,
                max_results=max_results,
                export_n=export_n,
                min_norm_len=min_norm_len,
                max_norm_len=max_norm_len,
            )
            return

        table = self._select_counts_table(
            lang=lang,
            corpus=corpus,
            export_n=export_n,
            source=source,
        )
        logger.info(
            "Exporting n-grams from %s for lang=%s corpus=%s min_count=%d "
            "max_results=%d export_n=%d min_norm_len=%d max_norm_len=%d",
            table,
            lang,
            corpus,
            min_count,
            max_results,
            export_n,
            min_norm_len,
            max_norm_len,
        )
        where_clause, params = self._count_filters(
            lang=lang,
            corpus=corpus,
            n=export_n,
            min_norm_len=min_norm_len,
            max_norm_len=max_norm_len,
        )
        limit_clause = ""
        if max_results:
            limit_clause = f"LIMIT {max_results}"

        if table == TOTAL_COUNTS_TABLE:
            base_sql = f"""
                SELECT lang, corpus, text, n, count AS total_count, norm_key,
                       has_punctuation
                FROM {TOTAL_COUNTS_TABLE}
                WHERE {where_clause} AND count >= ?
                ORDER BY total_count DESC, text ASC
                {limit_clause}
            """
        else:
            base_sql = f"""
                SELECT lang, corpus, text, n, SUM(count) AS total_count,
                       norm_key, has_punctuation
                FROM {RAW_COUNTS_TABLE}
                WHERE {where_clause}
                GROUP BY lang, corpus, text, n, norm_key, has_punctuation
                HAVING SUM(count) >= ?
                ORDER BY total_count DESC, text ASC
                {limit_clause}
            """
        result = self._con.execute(base_sql, [*params, min_count])
        while row := result.fetchone():
            yield self._row_to_count(row)

    def _count_filters(
        self,
        *,
        lang: str,
        corpus: str,
        n: int = 0,
        min_norm_len: int = 0,
        max_norm_len: int = 0,
    ) -> tuple[str, list]:
        where = ["lang = ?", "corpus = ?"]
        params = [lang, corpus]
        if n:
            where.append("n = ?")
            params.append(n)
        if min_norm_len:
            where.append("length(norm_key) >= ?")
            params.append(min_norm_len)
        if max_norm_len:
            where.append("length(norm_key) <= ?")
            params.append(max_norm_len)
        return " AND ".join(where), params

    def _row_to_count(self, row) -> NgramCount:
        return NgramCount(
            lang=row[0],
            corpus=row[1],
            text=row[2],
            n=row[3],
            count=row[4],
            norm_key=row[5],
            has_punctuation=row[6],
        )

    def _select_counts_table(
        self, *, lang: str, corpus: str, export_n: int, source: str
    ) -> str:
        if source not in {"auto", "raw", "compact"}:
            raise ValueError("source must be one of: auto, raw, compact")
        if source == "raw":
            return RAW_COUNTS_TABLE
        if source == "compact":
            if not self._has_usable_compaction(
                lang=lang, corpus=corpus, n=export_n
            ):
                raise RuntimeError(
                    f"No complete compacted counts for {lang}/{corpus}"
                )
            return TOTAL_COUNTS_TABLE
        if self._has_usable_compaction(lang=lang, corpus=corpus, n=export_n):
            return TOTAL_COUNTS_TABLE
        return RAW_COUNTS_TABLE

    def _has_usable_compaction(
        self, *, lang: str, corpus: str, n: int
    ) -> bool:
        if n:
            return self._has_compaction(lang=lang, corpus=corpus, n=n)

        raw_n = set(
            self._distinct_n_values(
                table=RAW_COUNTS_TABLE,
                lang=lang,
                corpus=corpus,
            )
        )
        compact_n = set(self._compacted_n_values(lang=lang, corpus=corpus))
        return bool(compact_n) and raw_n.issubset(compact_n)

    def _has_compaction(self, *, lang: str, corpus: str, n: int) -> bool:
        row = self._con.execute(
            """
            SELECT COUNT(*)
            FROM ngram_compactions
            WHERE lang = ? AND corpus = ? AND n = ?
            """,
            [lang, corpus, n],
        ).fetchone()
        return bool(row and row[0])

    def _distinct_n_values(
        self, *, table: str, lang: str, corpus: str
    ) -> list[int]:
        rows = self._con.execute(
            f"""
            SELECT DISTINCT n
            FROM {table}
            WHERE lang = ? AND corpus = ?
            ORDER BY n
            """,
            [lang, corpus],
        ).fetchall()
        return [row[0] for row in rows]

    def _compacted_n_values(self, *, lang: str, corpus: str) -> list[int]:
        rows = self._con.execute(
            """
            SELECT n
            FROM ngram_compactions
            WHERE lang = ? AND corpus = ?
            ORDER BY n
            """,
            [lang, corpus],
        ).fetchall()
        return [row[0] for row in rows]

    def compact_counts(self, *, lang: str, corpus: str, n: int) -> int:
        logger.info(
            "Compacting raw n-gram rows into totals for lang=%s corpus=%s n=%d",
            lang,
            corpus,
            n,
        )
        started_at = perf_counter()
        self._con.execute("BEGIN TRANSACTION")
        try:
            self._con.execute(
                """
                DELETE FROM ngram_totals
                WHERE lang = ? AND corpus = ? AND n = ?
                """,
                [lang, corpus, n],
            )
            self._con.execute(
                """
                INSERT INTO ngram_totals(
                    lang, corpus, text, n, count, norm_key, has_punctuation
                )
                SELECT lang, corpus, text, n, SUM(count) AS total_count,
                       norm_key, has_punctuation
                FROM ngram_counts
                WHERE lang = ? AND corpus = ? AND n = ?
                GROUP BY lang, corpus, text, n, norm_key, has_punctuation
                """,
                [lang, corpus, n],
            )
            self._con.execute(
                """
                DELETE FROM ngram_compactions
                WHERE lang = ? AND corpus = ? AND n = ?
                """,
                [lang, corpus, n],
            )
            self._con.execute(
                """
                INSERT INTO ngram_compactions(lang, corpus, n, compacted_at)
                VALUES (?, ?, ?, current_timestamp)
                """,
                [lang, corpus, n],
            )
            self._con.execute("COMMIT")
        except Exception:
            self._con.execute("ROLLBACK")
            raise
        compacted = self._con.execute(
            """
            SELECT COUNT(*)
            FROM ngram_totals
            WHERE lang = ? AND corpus = ? AND n = ?
            """,
            [lang, corpus, n],
        ).fetchone()[0]
        logger.info(
            "Compacted %d total n-gram rows in %.2fs",
            compacted,
            perf_counter() - started_at,
        )
        return compacted

    def count_entries(self, *, lang: str, corpus: str) -> int:
        return self._con.execute(
            """
            SELECT COUNT(*)
            FROM ngram_counts
            WHERE lang = ? AND corpus = ?
            """,
            [lang, corpus],
        ).fetchone()[0]

    def stats(
        self,
        *,
        lang: str | None = None,
        corpus: str | None = None,
        include_top_rows: bool = False,
    ):
        where = []
        params = []
        if lang:
            where.append("lang = ?")
            params.append(lang)
        if corpus:
            where.append("corpus = ?")
            params.append(corpus)

        where_clause = ""
        if where:
            where_clause = "WHERE " + " AND ".join(where)

        by_lang_corpus = self._con.execute(
            f"""
            SELECT
                lang,
                corpus,
                COUNT(*) AS partial_rows,
                SUM(count) AS total_occurrences,
                approx_count_distinct(text) AS approx_unique_texts
            FROM ngram_counts
            {where_clause}
            GROUP BY lang, corpus
            ORDER BY partial_rows DESC
            """,
            params,
        ).fetchall()

        legacy_collections = self._con.execute(
            """
            WITH locations AS (
                SELECT DISTINCT lang, corpus, 'raw' AS location
                FROM ngram_counts
                UNION ALL
                SELECT DISTINCT lang, corpus, 'compact' AS location
                FROM ngram_totals
                UNION ALL
                SELECT DISTINCT lang, corpus, 'compaction' AS location
                FROM ngram_compactions
            ), collection_flags AS (
                SELECT lang, corpus,
                       bool_or(location = 'raw') AS has_raw,
                       bool_or(location = 'compact') AS has_compact
                FROM locations
                GROUP BY lang, corpus
            ), compacted_n AS (
                SELECT lang, corpus,
                       list(n ORDER BY n) AS n_values,
                       MAX(compacted_at) AS last_compacted_at
                FROM ngram_compactions
                GROUP BY lang, corpus
            )
            SELECT f.lang, f.corpus, f.has_raw, f.has_compact,
                   COALESCE(c.n_values, []), c.last_compacted_at
            FROM collection_flags f
            LEFT JOIN compacted_n c USING (lang, corpus)
            ORDER BY f.lang, f.corpus
            """
        ).fetchall()

        v2_datasets = []
        v2_table_counts = []
        generation_collections = []
        all_v2_datasets = []
        generation_by_n = []
        if self._has_generation_schema:
            v2_datasets = self._con.execute(
                """
                SELECT dataset_id, artifact_id, policy_hash, lang, corpus,
                       sample, status, active_generation
                FROM extraction_datasets
                WHERE (? IS NULL OR lang = ?) AND (? IS NULL OR corpus = ?)
                ORDER BY created_at
                """,
                [lang, lang, corpus, corpus],
            ).fetchall()
            v2_table_counts = self._con.execute(
                """
                SELECT 'ngram_stage_v2', COUNT(*) FROM ngram_stage_v2
                UNION ALL
                SELECT 'ngram_final_v2', COUNT(*) FROM ngram_final_v2
                UNION ALL
                SELECT 'extraction_chunks', COUNT(*) FROM extraction_chunks
                """
            ).fetchall()
            generation_collections = self._con.execute(
                """
                SELECT lang, corpus, COUNT(*) AS datasets,
                       count_if(status = 'complete') AS complete_datasets,
                       count_if(status = 'in_progress') AS active_datasets,
                       MAX(created_at) AS latest_created_at
                FROM extraction_datasets
                GROUP BY lang, corpus
                ORDER BY lang, corpus
                """
            ).fetchall()
            all_v2_datasets = self._con.execute(
                """
                SELECT dataset_id, artifact_id, policy_hash, lang, corpus,
                       input_format, sample, status, active_generation,
                       created_at, completed_at
                FROM extraction_datasets
                ORDER BY lang, corpus, created_at
                """
            ).fetchall()
            generation_by_n = self._con.execute(
                f"""
                SELECT d.dataset_id, d.lang, d.corpus, f.n,
                       COUNT(*) AS rows, SUM(f.count) AS occurrences
                FROM extraction_datasets d
                JOIN {V2_FINAL_TABLE} f
                  ON f.dataset_id = d.dataset_id
                 AND f.generation = d.active_generation
                WHERE (? IS NULL OR d.lang = ?)
                  AND (? IS NULL OR d.corpus = ?)
                GROUP BY d.dataset_id, d.lang, d.corpus, f.n
                ORDER BY d.lang, d.corpus, d.dataset_id, f.n
                """,
                [lang, lang, corpus, corpus],
            ).fetchall()

        by_n = self._con.execute(
            f"""
            SELECT
                lang,
                corpus,
                n,
                COUNT(*) AS partial_rows,
                SUM(count) AS total_occurrences,
                approx_count_distinct(text) AS approx_unique_texts
            FROM ngram_counts
            {where_clause}
            GROUP BY lang, corpus, n
            ORDER BY partial_rows DESC
            """,
            params,
        ).fetchall()

        top_partial_rows = []
        if include_top_rows:
            top_partial_rows = self._con.execute(
                f"""
                SELECT lang, corpus, text, n, count, norm_key
                FROM ngram_counts
                {where_clause}
                ORDER BY count DESC
                LIMIT 20
                """,
                params,
            ).fetchall()

        totals_by_n = self._con.execute(
            f"""
            SELECT
                lang,
                corpus,
                n,
                COUNT(*) AS total_rows,
                SUM(count) AS total_occurrences
            FROM ngram_totals
            {where_clause}
            GROUP BY lang, corpus, n
            ORDER BY total_rows DESC
            """,
            params,
        ).fetchall()

        table_counts = self._con.execute(
            """
            SELECT 'ngram_counts' AS table_name, COUNT(*) AS rows
            FROM ngram_counts
            UNION ALL
            SELECT 'ngram_totals' AS table_name, COUNT(*) AS rows
            FROM ngram_totals
            UNION ALL
            SELECT 'ngram_compactions' AS table_name, COUNT(*) AS rows
            FROM ngram_compactions
            ORDER BY table_name
            """,
        ).fetchall()

        filtered_table_counts = self._con.execute(
            f"""
            SELECT 'ngram_counts' AS table_name, COUNT(*) AS rows
            FROM ngram_counts
            {where_clause}
            UNION ALL
            SELECT 'ngram_totals' AS table_name, COUNT(*) AS rows
            FROM ngram_totals
            {where_clause}
            UNION ALL
            SELECT 'ngram_compactions' AS table_name, COUNT(*) AS rows
            FROM ngram_compactions
            {where_clause}
            ORDER BY table_name
            """,
            [*params, *params, *params],
        ).fetchall()

        compacted = self._con.execute(
            f"""
            SELECT lang, corpus, n, compacted_at
            FROM ngram_compactions
            {where_clause}
            ORDER BY compacted_at DESC
            """,
            params,
        ).fetchall()

        table_inventory = []
        physical_tables = self._con.execute(
            """
            SELECT table_name, COUNT(column_name) AS columns
            FROM information_schema.columns
            WHERE table_schema = 'main'
            GROUP BY table_name
            ORDER BY table_name
            """
        ).fetchall()
        for table_name, columns in physical_tables:
            identifier = table_name.replace('"', '""')
            rows = self._con.execute(
                f'SELECT COUNT(*) FROM "{identifier}"'
            ).fetchone()[0]
            table_inventory.append((table_name, columns, rows))

        return {
            "schema_version": self._schema_version,
            "legacy_collections": legacy_collections,
            "generation_collections": generation_collections,
            "all_v2_datasets": all_v2_datasets,
            "generation_by_n": generation_by_n,
            "table_inventory": table_inventory,
            "by_lang_corpus": by_lang_corpus,
            "by_n": by_n,
            "totals_by_n": totals_by_n,
            "table_counts": table_counts,
            "filtered_table_counts": filtered_table_counts,
            "top_partial_rows": top_partial_rows,
            "compacted": compacted,
            "v2_datasets": v2_datasets,
            "v2_table_counts": v2_table_counts,
        }

    def _count_table_rows(self, table: str, *, lang: str, corpus: str) -> int:
        return self._con.execute(
            f"""
            SELECT COUNT(*)
            FROM {table}
            WHERE lang = ? AND corpus = ?
            """,
            [lang, corpus],
        ).fetchone()[0]

    def delete_counts(self, *, lang: str, corpus: str) -> dict[str, int]:
        deleted = {
            RAW_COUNTS_TABLE: self._count_table_rows(
                RAW_COUNTS_TABLE, lang=lang, corpus=corpus
            ),
            TOTAL_COUNTS_TABLE: self._count_table_rows(
                TOTAL_COUNTS_TABLE, lang=lang, corpus=corpus
            ),
            "ngram_compactions": self._count_table_rows(
                "ngram_compactions", lang=lang, corpus=corpus
            ),
        }
        dataset_ids = [
            row[0]
            for row in self._con.execute(
                """
                SELECT dataset_id FROM extraction_datasets
                WHERE lang = ? AND corpus = ?
                """,
                [lang, corpus],
            ).fetchall()
        ]
        deleted["v2_datasets"] = len(dataset_ids)
        logger.info(
            "Deleting n-gram rows for lang=%s corpus=%s: raw=%d totals=%d "
            "compactions=%d",
            lang,
            corpus,
            deleted[RAW_COUNTS_TABLE],
            deleted[TOTAL_COUNTS_TABLE],
            deleted["ngram_compactions"],
        )
        self._con.execute("BEGIN TRANSACTION")
        try:
            for table in (
                RAW_COUNTS_TABLE,
                TOTAL_COUNTS_TABLE,
                "ngram_compactions",
            ):
                self._con.execute(
                    f"DELETE FROM {table} WHERE lang = ? AND corpus = ?",
                    [lang, corpus],
                )
            for dataset_id in dataset_ids:
                for table in (
                    "ngram_stage_v2",
                    V2_FINAL_TABLE,
                    "extraction_chunks",
                ):
                    self._con.execute(
                        f"DELETE FROM {table} WHERE dataset_id = ?",
                        [dataset_id],
                    )
                self._con.execute(
                    "DELETE FROM extraction_runs WHERE dataset_id = ?",
                    [dataset_id],
                )
            self._con.execute(
                """
                DELETE FROM extraction_datasets
                WHERE lang = ? AND corpus = ?
                """,
                [lang, corpus],
            )
            self._con.execute("COMMIT")
        except Exception:
            self._con.execute("ROLLBACK")
            raise
        return deleted

    def reset_counts(self, *, lang: str, corpus: str) -> dict[str, int]:
        return self.delete_counts(lang=lang, corpus=corpus)

    def close(self) -> None:
        logger.info("Closing DuckDB database")
        self._con.close()
