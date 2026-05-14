"""Infrastructure adapters for n-gram storage."""

from __future__ import annotations

import logging
import csv
import tempfile
from collections import Counter
from pathlib import Path
from time import perf_counter

from semordnilap.ngrams.domain import NgramCount, build_ngram_count

logger = logging.getLogger(__name__)
INSERT_BATCH_SIZE = 50_000
RAW_COUNTS_TABLE = "ngram_counts"
TOTAL_COUNTS_TABLE = "ngram_totals"


class DuckDbNgramCountRepository:
    def __init__(self, db_path: Path) -> None:
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError(
                "DuckDB backend requires `duckdb`. Install it with "
                "`uv add duckdb`, then rerun the command."
            ) from exc

        db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Opening DuckDB database at %s", db_path)
        self._tmp_dir = db_path.parent
        self._con = duckdb.connect(str(db_path))
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS ngram_counts (
                lang TEXT NOT NULL,
                corpus TEXT NOT NULL,
                text TEXT NOT NULL,
                n INTEGER NOT NULL,
                count BIGINT NOT NULL,
                norm_key TEXT NOT NULL
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
                norm_key TEXT NOT NULL
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

    def add_counts(
        self,
        counts: Counter[tuple[str, ...]],
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
        for tokens, count in counts.items():
            row = build_ngram_count(
                tokens,
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
            n_values={len(tokens) for tokens in counts},
        )
        logger.info(
            "Appended %d n-gram counts in %.2fs",
            total,
            perf_counter() - started_at,
        )

    def _insert_batch(self, rows: list[tuple]) -> None:
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
        try:
            self._con.execute(
                f"""
                COPY ngram_counts(lang, corpus, text, n, count, norm_key)
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
    ):
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
            sql = f"""
            SELECT lang, corpus, text, n, count AS total_count, norm_key
            FROM {TOTAL_COUNTS_TABLE}
            WHERE {where_clause} AND count >= ?
            ORDER BY total_count DESC, text ASC
            {limit_clause}
            """
        else:
            sql = f"""
            SELECT lang, corpus, text, n, SUM(count) AS total_count, norm_key
            FROM {RAW_COUNTS_TABLE}
            WHERE {where_clause}
            GROUP BY lang, corpus, text, n, norm_key
            HAVING SUM(count) >= ?
            ORDER BY total_count DESC, text ASC
            {limit_clause}
            """

        result = self._con.execute(sql, [*params, min_count])
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
        )

    def _select_counts_table(
        self, *, lang: str, corpus: str, export_n: int, source: str
    ) -> str:
        if source not in {"auto", "raw", "compact"}:
            raise ValueError("source must be one of: auto, raw, compact")
        if source == "raw":
            return RAW_COUNTS_TABLE
        if source == "compact":
            return TOTAL_COUNTS_TABLE
        if self._has_usable_compaction(
            lang=lang, corpus=corpus, n=export_n
        ):
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
        self._con.execute(
            """
            DELETE FROM ngram_totals
            WHERE lang = ? AND corpus = ? AND n = ?
            """,
            [lang, corpus, n],
        )
        self._con.execute(
            """
            INSERT INTO ngram_totals(lang, corpus, text, n, count, norm_key)
            SELECT lang, corpus, text, n, SUM(count) AS total_count, norm_key
            FROM ngram_counts
            WHERE lang = ? AND corpus = ? AND n = ?
            GROUP BY lang, corpus, text, n, norm_key
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

        return {
            "by_lang_corpus": by_lang_corpus,
            "by_n": by_n,
            "totals_by_n": totals_by_n,
            "table_counts": table_counts,
            "filtered_table_counts": filtered_table_counts,
            "top_partial_rows": top_partial_rows,
            "compacted": compacted,
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
        logger.info(
            "Deleting n-gram rows for lang=%s corpus=%s: raw=%d totals=%d "
            "compactions=%d",
            lang,
            corpus,
            deleted[RAW_COUNTS_TABLE],
            deleted[TOTAL_COUNTS_TABLE],
            deleted["ngram_compactions"],
        )
        self._con.execute(
            """
            DELETE FROM ngram_counts
            WHERE lang = ? AND corpus = ?
            """,
            [lang, corpus],
        )
        self._con.execute(
            """
            DELETE FROM ngram_totals
            WHERE lang = ? AND corpus = ?
            """,
            [lang, corpus],
        )
        self._con.execute(
            """
            DELETE FROM ngram_compactions
            WHERE lang = ? AND corpus = ?
            """,
            [lang, corpus],
        )
        return deleted

    def reset_counts(self, *, lang: str, corpus: str) -> dict[str, int]:
        return self.delete_counts(lang=lang, corpus=corpus)

    def close(self) -> None:
        logger.info("Closing DuckDB database")
        self._con.close()
