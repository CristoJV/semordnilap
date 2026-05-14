"""DuckDB-backed semordnilap search over extracted corpus n-grams."""

from __future__ import annotations

import logging
from pathlib import Path

from semordnilap.search.domain import SearchPolicy, SemordnilapPair

logger = logging.getLogger(__name__)
RAW_COUNTS_TABLE = "ngram_counts"
TOTAL_COUNTS_TABLE = "ngram_totals"


class DuckDbSemordnilapSearchRepository:
    def __init__(self, db_path: Path) -> None:
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError(
                "DuckDB search requires `duckdb`. Install it with "
                "`uv add duckdb`, then rerun the command."
            ) from exc

        logger.info("Opening DuckDB database at %s", db_path)
        self._con = duckdb.connect(str(db_path), read_only=True)

    def iter_pairs(self, policy: SearchPolicy):
        logger.info(
            "Searching semordnilaps from %s counts: %s/%s -> %s/%s",
            policy.counts_source,
            policy.source_lang,
            policy.source_corpus,
            policy.target_lang,
            policy.target_corpus,
        )

        filters = []
        if not policy.include_palindromes:
            filters.append("src.norm_key <> tgt.norm_key")
        if not policy.include_identical_text:
            filters.append(
                "NOT (src.lang = tgt.lang "
                "AND src.corpus = tgt.corpus "
                "AND src.text = tgt.text)"
            )

        extra_where = ""
        if filters:
            extra_where = "AND " + " AND ".join(filters)

        limit_clause = ""
        if policy.max_results:
            limit_clause = f"LIMIT {policy.max_results}"

        table = self._counts_table(policy)
        if table == TOTAL_COUNTS_TABLE:
            self._validate_compact_counts(
                lang=policy.source_lang,
                corpus=policy.source_corpus,
                n=policy.source_n,
                side="source",
            )
            self._validate_compact_counts(
                lang=policy.target_lang,
                corpus=policy.target_corpus,
                n=policy.target_n,
                side="target",
            )
        src_sql, src_params = self._candidate_sql(
            table=table,
            lang=policy.source_lang,
            corpus=policy.source_corpus,
            min_count=policy.min_source_count,
            n=policy.source_n,
            min_norm_len=policy.min_norm_len,
            max_norm_len=policy.max_norm_len,
        )
        tgt_sql, tgt_params = self._candidate_sql(
            table=table,
            lang=policy.target_lang,
            corpus=policy.target_corpus,
            min_count=policy.min_target_count,
            n=policy.target_n,
            min_norm_len=policy.min_norm_len,
            max_norm_len=policy.max_norm_len,
        )

        result = self._con.execute(
            f"""
            WITH src AS ({src_sql}),
            tgt AS ({tgt_sql})
            SELECT
                src.lang AS source_lang,
                src.corpus AS source_corpus,
                src.text AS source_text,
                src.n AS source_n,
                src.total_count AS source_count,
                src.norm_key AS source_norm_key,
                tgt.lang AS target_lang,
                tgt.corpus AS target_corpus,
                tgt.text AS target_text,
                tgt.n AS target_n,
                tgt.total_count AS target_count,
                tgt.norm_key AS target_norm_key
            FROM src
            JOIN tgt ON reverse(src.norm_key) = tgt.norm_key
            WHERE 1 = 1
            {extra_where}
            ORDER BY
                (src.total_count + tgt.total_count) DESC,
                src.text ASC,
                tgt.text ASC
            {limit_clause}
            """,
            [*src_params, *tgt_params],
        )

        while row := result.fetchone():
            yield SemordnilapPair(
                source_lang=row[0],
                source_corpus=row[1],
                source_text=row[2],
                source_n=row[3],
                source_count=row[4],
                source_norm_key=row[5],
                target_lang=row[6],
                target_corpus=row[7],
                target_text=row[8],
                target_n=row[9],
                target_count=row[10],
                target_norm_key=row[11],
            )

    def _counts_table(self, policy: SearchPolicy) -> str:
        if policy.counts_source == "raw":
            return RAW_COUNTS_TABLE
        if policy.counts_source == "compact":
            return TOTAL_COUNTS_TABLE
        if policy.counts_source != "auto":
            raise ValueError("counts_source must be one of: auto, raw, compact")

        source_compacted = self._has_usable_compaction(
            lang=policy.source_lang,
            corpus=policy.source_corpus,
            n=policy.source_n,
        )
        target_compacted = self._has_usable_compaction(
            lang=policy.target_lang,
            corpus=policy.target_corpus,
            n=policy.target_n,
        )
        if source_compacted and target_compacted:
            logger.info("Using compacted counts automatically")
            return TOTAL_COUNTS_TABLE

        logger.info(
            "Using raw counts automatically because compacted counts are "
            "not complete for both sides"
        )
        return RAW_COUNTS_TABLE

    def _validate_compact_counts(
        self, *, lang: str, corpus: str, n: int, side: str
    ) -> None:
        if self._has_usable_compaction(lang=lang, corpus=corpus, n=n):
            if not n:
                compacted_n = self._compacted_n_values(
                    lang=lang, corpus=corpus
                )
                if compacted_n:
                    logger.info(
                        "Using compacted %s candidates for lang=%s "
                        "corpus=%s compacted_n=%s",
                        side,
                        lang,
                        corpus,
                        ",".join(str(value) for value in compacted_n),
                    )
            return

        raw_rows = self._count_rows(
            table=RAW_COUNTS_TABLE,
            lang=lang,
            corpus=corpus,
            n=n,
        )
        n_message = f" n={n}" if n else ""
        if raw_rows:
            raise RuntimeError(
                f"No compacted {side} counts found for lang={lang!r} "
                f"corpus={corpus!r}{n_message}, but {raw_rows} raw rows "
                "exist. Run `sp_ngrams --compact-only --compact-n N` "
                "for the missing language/corpus before searching with "
                "`--counts-source compact`, or use `--counts-source raw`."
            )
        raise RuntimeError(
            f"No {side} counts found for lang={lang!r} "
            f"corpus={corpus!r}{n_message}."
        )

    def _count_rows(
        self, *, table: str, lang: str, corpus: str, n: int
    ) -> int:
        where = ["lang = ?", "corpus = ?"]
        params = [lang, corpus]
        if n:
            where.append("n = ?")
            params.append(n)
        where_clause = " AND ".join(where)
        return self._con.execute(
            f"""
            SELECT COUNT(*)
            FROM {table}
            WHERE {where_clause}
            """,
            params,
        ).fetchone()[0]

    def _has_usable_compaction(
        self, *, lang: str, corpus: str, n: int
    ) -> bool:
        if n:
            return bool(
                self._count_rows(
                    table=TOTAL_COUNTS_TABLE,
                    lang=lang,
                    corpus=corpus,
                    n=n,
                )
            )

        raw_n = set(
            self._distinct_n_values(
                table=RAW_COUNTS_TABLE,
                lang=lang,
                corpus=corpus,
            )
        )
        compact_n = set(self._compacted_n_values(lang=lang, corpus=corpus))
        return bool(compact_n) and raw_n.issubset(compact_n)

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

    def _candidate_sql(
        self,
        *,
        table: str,
        lang: str,
        corpus: str,
        min_count: int,
        n: int,
        min_norm_len: int,
        max_norm_len: int,
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

        where_clause = " AND ".join(where)
        if table == TOTAL_COUNTS_TABLE:
            return (
                f"""
                SELECT lang, corpus, text, n, count AS total_count, norm_key
                FROM {TOTAL_COUNTS_TABLE}
                WHERE {where_clause} AND count >= ?
                """,
                [*params, min_count],
            )

        return (
            f"""
            SELECT lang, corpus, text, n, SUM(count) AS total_count, norm_key
            FROM {RAW_COUNTS_TABLE}
            WHERE {where_clause}
            GROUP BY lang, corpus, text, n, norm_key
            HAVING SUM(count) >= ?
            """,
            [*params, min_count],
        )

    def close(self) -> None:
        logger.info("Closing DuckDB database")
        self._con.close()
