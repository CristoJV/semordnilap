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
CURRENT_SCHEMA_VERSION = 4
V2_FINAL_TABLE = "ngram_final_v2"
FINALIZATION_PARTS_TABLE = "ngram_finalization_parts"
DEFAULT_FINALIZATION_BUCKETS = 8
REMOVED_LEGACY_TABLES = (
    "ngram_counts",
    "ngram_totals",
    "ngram_compactions",
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
        if read_only and (
            self._schema_version < 3 or not self._has_generation_schema
        ):
            self._con.close()
            raise RuntimeError(
                "This database does not contain a supported generation-based "
                "n-gram schema"
            )
        if not read_only:
            if existed and self._schema_version < CURRENT_SCHEMA_VERSION:
                if self._schema_version != 3 or not self._has_generation_schema:
                    self._con.close()
                    raise RuntimeError(
                        "This database predates the supported generation-based "
                        "schema v3 and cannot be migrated in place; use a new "
                        "database and re-extract the corpus"
                    )
                if not allow_migrate:
                    self._con.close()
                    raise RuntimeError(
                        "DuckDB schema version 3 requires explicit migration: "
                        f"sp_ngrams db migrate --db-path {db_path}"
                    )
            if allow_migrate:
                try:
                    self._migrate_to_current()
                except Exception:
                    self._con.close()
                    raise
            else:
                self._create_schema_v4()
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

    def _create_schema_v4(self) -> None:
        self._con.execute("BEGIN TRANSACTION")
        try:
            self._ensure_generation_tables()
            self._record_schema_version(CURRENT_SCHEMA_VERSION)
            self._con.execute("COMMIT")
        except Exception:
            self._con.execute("ROLLBACK")
            raise

    def _migrate_to_current(self) -> None:
        if self._schema_version == CURRENT_SCHEMA_VERSION:
            return
        if self._schema_version != 3 or not self._has_generation_schema:
            raise RuntimeError(
                "Only generation-based schema v3 can be migrated to v4; "
                f"found schema v{self._schema_version}"
            )
        self._con.execute("BEGIN TRANSACTION")
        try:
            self._ensure_generation_tables()
            for table in REMOVED_LEGACY_TABLES:
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
                FINALIZATION_PARTS_TABLE,
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
        preserve_nasal_letters: bool,
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
                preserve_nasal_letters=preserve_nasal_letters,
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
            SELECT status, active_generation,
                   CAST(json_extract_string(policy_json, '$.max_n') AS INTEGER)
            FROM extraction_datasets WHERE dataset_id = ?
            """,
            [dataset_id],
        ).fetchone()
        if not dataset:
            raise ValueError(f"Unknown extraction dataset: {dataset_id}")
        if dataset[0] == "complete":
            if not retain_staging:
                self._cleanup_finalized_staging(dataset_id)
            return self._count_v2_final_rows(dataset_id)
        generation = int(dataset[1] or 0) + 1
        max_n = int(dataset[2] or 1)
        bucket_count = self._finalization_bucket_count(
            dataset_id=dataset_id,
            generation=generation,
        )
        completed = {
            (row[0], row[1])
            for row in self._con.execute(
                f"""
                SELECT n, bucket
                FROM {FINALIZATION_PARTS_TABLE}
                WHERE dataset_id = ? AND generation = ?
                  AND bucket_count = ?
                """,
                [dataset_id, generation, bucket_count],
            ).fetchall()
        }
        total_parts = max_n * bucket_count
        logger.info(
            "Finalizing dataset %s progressively: generation=%d n=1..%d "
            "buckets=%d completed_parts=%d/%d",
            dataset_id,
            generation,
            max_n,
            bucket_count,
            len(completed),
            total_parts,
        )

        current_threads, preserve_order = self._con.execute(
            """
            SELECT current_setting('threads'),
                   current_setting('preserve_insertion_order')
            """
        ).fetchone()
        finalization_threads = min(int(current_threads), 2)
        try:
            self._con.execute(f"SET threads = {finalization_threads}")
            self._con.execute("SET preserve_insertion_order = false")
            step = 0
            for n in range(1, max_n + 1):
                for bucket in range(bucket_count):
                    step += 1
                    if (n, bucket) in completed:
                        logger.info(
                            "Finalization part %d/%d already committed: "
                            "n=%d bucket=%d/%d",
                            step,
                            total_parts,
                            n,
                            bucket + 1,
                            bucket_count,
                        )
                        continue
                    self._finalize_extraction_part(
                        dataset_id=dataset_id,
                        generation=generation,
                        n=n,
                        bucket=bucket,
                        bucket_count=bucket_count,
                        step=step,
                        total_parts=total_parts,
                    )
            self._fault("finalize.after_final_counts")
            self._fault("finalize.after_validation")
        finally:
            self._con.execute(f"SET threads = {int(current_threads)}")
            self._con.execute(
                "SET preserve_insertion_order = "
                + ("true" if preserve_order else "false")
            )

        self._con.execute("BEGIN TRANSACTION")
        try:
            completed_parts = self._con.execute(
                f"""
                SELECT COUNT(*)
                FROM {FINALIZATION_PARTS_TABLE}
                WHERE dataset_id = ? AND generation = ?
                  AND bucket_count = ?
                """,
                [dataset_id, generation, bucket_count],
            ).fetchone()[0]
            if completed_parts != total_parts:
                raise RuntimeError(
                    f"Finalization is incomplete for {dataset_id}: "
                    f"{completed_parts}/{total_parts} parts"
                )
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
            self._fault("finalize.before_transaction_commit")
            self._con.execute("COMMIT")
        except Exception:
            self._con.execute("ROLLBACK")
            raise
        if not retain_staging:
            self._cleanup_finalized_staging(dataset_id)
        return self._count_v2_final_rows(dataset_id)

    def _cleanup_finalized_staging(self, dataset_id: str) -> None:
        self._con.execute("BEGIN TRANSACTION")
        try:
            self._con.execute(
                "DELETE FROM ngram_stage_v2 WHERE dataset_id = ?",
                [dataset_id],
            )
            self._con.execute(
                f"""
                DELETE FROM {FINALIZATION_PARTS_TABLE}
                WHERE dataset_id = ?
                """,
                [dataset_id],
            )
            self._con.execute("COMMIT")
        except Exception:
            self._con.execute("ROLLBACK")
            raise

    def _finalization_bucket_count(
        self, *, dataset_id: str, generation: int
    ) -> int:
        row = self._con.execute(
            f"""
            SELECT MIN(bucket_count), MAX(bucket_count)
            FROM {FINALIZATION_PARTS_TABLE}
            WHERE dataset_id = ? AND generation = ?
            """,
            [dataset_id, generation],
        ).fetchone()
        if row and row[0] is not None:
            if row[0] != row[1]:
                raise RuntimeError(
                    f"Inconsistent finalization partitions for {dataset_id}"
                )
            return int(row[0])
        return DEFAULT_FINALIZATION_BUCKETS

    def _finalize_extraction_part(
        self,
        *,
        dataset_id: str,
        generation: int,
        n: int,
        bucket: int,
        bucket_count: int,
        step: int,
        total_parts: int,
    ) -> None:
        logger.info(
            "Finalization part %d/%d started: n=%d bucket=%d/%d",
            step,
            total_parts,
            n,
            bucket + 1,
            bucket_count,
        )
        started_at = perf_counter()
        self._con.execute("BEGIN TRANSACTION")
        try:
            self._con.execute(
                f"""
                DELETE FROM {V2_FINAL_TABLE}
                WHERE dataset_id = ? AND generation = ? AND n = ?
                  AND hash(surface_key) % ? = ?
                """,
                [dataset_id, generation, n, bucket_count, bucket],
            )
            rows = self._con.execute(
                f"""
                INSERT INTO {V2_FINAL_TABLE}
                SELECT dataset_id, ?, surface_key,
                       arg_min(surface_display, chunk_id), n, SUM(count),
                       any_value(norm_key), bool_or(has_punctuation)
                FROM ngram_stage_v2
                WHERE dataset_id = ? AND n = ?
                  AND hash(surface_key) % ? = ?
                GROUP BY dataset_id, surface_key, n
                """,
                [generation, dataset_id, n, bucket_count, bucket],
            ).fetchone()[0]
            self._fault("finalize.after_part_counts")
            self._con.execute(
                f"""
                INSERT INTO {FINALIZATION_PARTS_TABLE}
                VALUES (?, ?, ?, ?, ?, current_timestamp)
                """,
                [dataset_id, generation, n, bucket, bucket_count],
            )
            self._con.execute("COMMIT")
        except Exception:
            self._con.execute("ROLLBACK")
            raise
        logger.info(
            "Finalization part %d/%d committed: n=%d bucket=%d/%d "
            "rows=%d elapsed=%.2fs",
            step,
            total_parts,
            n,
            bucket + 1,
            bucket_count,
            rows,
            perf_counter() - started_at,
        )

    def resume_finalization(
        self, *, lang: str, corpus: str, dataset_id: str | None = None
    ) -> int:
        rows = self._con.execute(
            """
            SELECT d.dataset_id, r.run_id
            FROM extraction_datasets d
            JOIN extraction_runs r USING (dataset_id)
            WHERE d.lang = ? AND d.corpus = ?
              AND (? IS NULL OR d.dataset_id = ?)
            ORDER BY d.created_at
            """,
            [lang, corpus, dataset_id, dataset_id],
        ).fetchall()
        if not rows:
            raise ValueError(
                f"No extraction dataset found for {lang}/{corpus}"
            )
        if len(rows) > 1:
            raise ValueError(
                f"Multiple policy identities exist for {lang}/{corpus}; "
                "select --dataset-id explicitly"
            )
        return self.finalize_extraction(
            dataset_id=rows[0][0],
            run_id=rows[0][1],
        )

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
        self._con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {FINALIZATION_PARTS_TABLE} (
                dataset_id TEXT NOT NULL,
                generation INTEGER NOT NULL,
                n INTEGER NOT NULL,
                bucket INTEGER NOT NULL,
                bucket_count INTEGER NOT NULL,
                completed_at TIMESTAMP NOT NULL,
                PRIMARY KEY(dataset_id, generation, n, bucket)
            )
            """
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

    def _resolve_dataset(
        self, *, lang: str, corpus: str, dataset_id: str | None = None
    ):
        if not self._has_generation_schema:
            raise RuntimeError(
                "This database does not contain the generation-based n-gram "
                "schema"
            )
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

    def _iter_final_counts(
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
        dataset_id: str | None = None,
    ):
        dataset = self._resolve_dataset(
            lang=lang, corpus=corpus, dataset_id=dataset_id
        )
        if dataset is None:
            raise ValueError(f"No extraction dataset exists for {lang}/{corpus}")
        dataset_id, status, generation = dataset
        if status != "complete" or generation is None:
            raise RuntimeError(f"Extraction dataset is not complete: {dataset_id}")
        yield from self._iter_final_counts(
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

    def stats(
        self,
        *,
        lang: str | None = None,
        corpus: str | None = None,
        include_top_rows: bool = False,
    ):
        filter_params = [lang, lang, corpus, corpus]
        datasets = self._con.execute(
            """
            SELECT dataset_id, artifact_id, policy_hash, lang, corpus,
                   input_format, sample, status, active_generation,
                   created_at, completed_at
            FROM extraction_datasets
            WHERE (? IS NULL OR lang = ?) AND (? IS NULL OR corpus = ?)
            ORDER BY lang, corpus, created_at
            """,
            filter_params,
        ).fetchall()
        generation_collections = self._con.execute(
            """
            SELECT lang, corpus, COUNT(*) AS datasets,
                   count_if(status = 'complete') AS complete_datasets,
                   count_if(status = 'in_progress') AS active_datasets,
                   MAX(created_at) AS latest_created_at
            FROM extraction_datasets
            WHERE (? IS NULL OR lang = ?) AND (? IS NULL OR corpus = ?)
            GROUP BY lang, corpus
            ORDER BY lang, corpus
            """,
            filter_params,
        ).fetchall()
        generation_by_n = self._con.execute(
            f"""
            SELECT d.dataset_id, d.lang, d.corpus, f.n,
                   COUNT(*) AS rows, SUM(f.count) AS occurrences
            FROM extraction_datasets d
            JOIN {V2_FINAL_TABLE} f
              ON f.dataset_id = d.dataset_id
             AND f.generation = d.active_generation
            WHERE (? IS NULL OR d.lang = ?) AND (? IS NULL OR d.corpus = ?)
            GROUP BY d.dataset_id, d.lang, d.corpus, f.n
            ORDER BY d.lang, d.corpus, d.dataset_id, f.n
            """,
            filter_params,
        ).fetchall()
        extraction_runs = self._con.execute(
            """
            SELECT d.dataset_id, d.lang, d.corpus, r.status,
                   r.completed_documents, r.generated_occurrences,
                   r.committed_chunks, r.updated_at
            FROM extraction_datasets d
            JOIN extraction_runs r USING (dataset_id)
            WHERE (? IS NULL OR d.lang = ?) AND (? IS NULL OR d.corpus = ?)
            ORDER BY d.created_at
            """,
            filter_params,
        ).fetchall()
        finalization_parts = self._con.execute(
            f"""
            SELECT p.dataset_id, p.generation, p.n,
                   COUNT(*) AS completed_buckets,
                   MAX(p.bucket_count) AS bucket_count,
                   MAX(p.completed_at) AS updated_at
            FROM {FINALIZATION_PARTS_TABLE} p
            JOIN extraction_datasets d USING (dataset_id)
            WHERE (? IS NULL OR d.lang = ?) AND (? IS NULL OR d.corpus = ?)
            GROUP BY p.dataset_id, p.generation, p.n
            ORDER BY p.dataset_id, p.generation, p.n
            """,
            filter_params,
        ).fetchall()

        top_rows = []
        if include_top_rows:
            top_rows = self._con.execute(
                f"""
                SELECT d.lang, d.corpus, f.surface_display, f.n, f.count,
                       f.norm_key, d.dataset_id
                FROM extraction_datasets d
                JOIN {V2_FINAL_TABLE} f
                  ON f.dataset_id = d.dataset_id
                 AND f.generation = d.active_generation
                WHERE (? IS NULL OR d.lang = ?)
                  AND (? IS NULL OR d.corpus = ?)
                ORDER BY f.count DESC, f.surface_key
                LIMIT 20
                """,
                filter_params,
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
            "generation_collections": generation_collections,
            "datasets": datasets,
            "generation_by_n": generation_by_n,
            "extraction_runs": extraction_runs,
            "finalization_parts": finalization_parts,
            "table_inventory": table_inventory,
            "top_rows": top_rows,
        }

    def delete_counts(self, *, lang: str, corpus: str) -> dict[str, int]:
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
        deleted = {"datasets": len(dataset_ids)}
        for table in (
            "ngram_stage_v2",
            V2_FINAL_TABLE,
            FINALIZATION_PARTS_TABLE,
            "extraction_chunks",
            "extraction_runs",
        ):
            deleted[table] = sum(
                self._con.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE dataset_id = ?",
                    [dataset_id],
                ).fetchone()[0]
                for dataset_id in dataset_ids
            )
        logger.info(
            "Deleting %d generation-based n-gram dataset(s) for %s/%s",
            len(dataset_ids),
            lang,
            corpus,
        )
        self._con.execute("BEGIN TRANSACTION")
        try:
            for dataset_id in dataset_ids:
                for table in (
                    "ngram_stage_v2",
                    V2_FINAL_TABLE,
                    FINALIZATION_PARTS_TABLE,
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
