"""DuckDB-backed semordnilap search over extracted corpus n-grams."""

from __future__ import annotations

import logging
from pathlib import Path

from semordnilap.search.domain import SearchPolicy, SemordnilapPair

logger = logging.getLogger(__name__)
FINAL_COUNTS_TABLE = "ngram_final_v2"


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
        generation_tables = int(
            self._con.execute(
                """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_name IN ('extraction_datasets', 'ngram_final_v2')
                """
            ).fetchone()[0]
        )
        if generation_tables != 2:
            self._con.close()
            raise RuntimeError(
                "The DuckDB database does not use the supported "
                "generation-based n-gram schema; migrate or re-extract it"
            )

    def iter_pairs(self, policy: SearchPolicy):
        logger.info(
            "Searching finalized semordnilaps: %s/%s -> %s/%s",
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

        source_dataset = self._resolve_dataset(
            lang=policy.source_lang,
            corpus=policy.source_corpus,
            dataset_id=policy.source_dataset_id,
        )
        target_dataset = self._resolve_dataset(
            lang=policy.target_lang,
            corpus=policy.target_corpus,
            dataset_id=policy.target_dataset_id,
        )
        src_sql, src_params = self._candidate_sql(
            dataset=source_dataset,
            lang=policy.source_lang,
            corpus=policy.source_corpus,
            min_count=policy.min_source_count,
            n=policy.source_n,
            min_norm_len=policy.min_norm_len,
            max_norm_len=policy.max_norm_len,
        )
        tgt_sql, tgt_params = self._candidate_sql(
            dataset=target_dataset,
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
                src.has_punctuation AS source_has_punctuation,
                tgt.lang AS target_lang,
                tgt.corpus AS target_corpus,
                tgt.text AS target_text,
                tgt.n AS target_n,
                tgt.total_count AS target_count,
                tgt.norm_key AS target_norm_key,
                tgt.has_punctuation AS target_has_punctuation
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
                source_has_punctuation=row[6],
                target_lang=row[7],
                target_corpus=row[8],
                target_text=row[9],
                target_n=row[10],
                target_count=row[11],
                target_norm_key=row[12],
                target_has_punctuation=row[13],
                source_dataset_id=source_dataset[0],
                target_dataset_id=target_dataset[0],
            )

    def _resolve_dataset(
        self, *, lang: str, corpus: str, dataset_id: str | None = None
    ):
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
            """,
            [lang, corpus],
        ).fetchall()
        if len(rows) > 1:
            raise ValueError(
                f"Multiple policy identities exist for {lang}/{corpus}"
            )
        if not rows:
            raise ValueError(f"No extraction dataset exists for {lang}/{corpus}")
        return rows[0]

    def _candidate_sql(
        self,
        *,
        dataset,
        lang: str,
        corpus: str,
        min_count: int,
        n: int,
        min_norm_len: int,
        max_norm_len: int,
    ) -> tuple[str, list]:
        dataset_id, status, generation = dataset
        if status != "complete" or generation is None:
            raise RuntimeError(f"N-gram dataset is incomplete: {dataset_id}")
        where = ["dataset_id = ?", "generation = ?", "count >= ?"]
        params = [lang, corpus, dataset_id, generation, min_count]
        if n:
            where.append("n = ?")
            params.append(n)
        if min_norm_len:
            where.append("length(norm_key) >= ?")
            params.append(min_norm_len)
        if max_norm_len:
            where.append("length(norm_key) <= ?")
            params.append(max_norm_len)
        return (
            f"""
            SELECT ? AS lang, ? AS corpus, surface_display AS text, n,
                   count AS total_count, norm_key, has_punctuation
            FROM {FINAL_COUNTS_TABLE}
            WHERE {" AND ".join(where)}
            """,
            params,
        )

    def close(self) -> None:
        logger.info("Closing DuckDB database")
        self._con.close()
