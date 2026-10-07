"""DuckDB-backed semordnilap search over extracted corpus n-grams."""

from __future__ import annotations

import logging
from pathlib import Path

from semordnilap.ngrams.domain.filters import is_all_stopwords
from semordnilap.ngrams.domain.tokenize import tokenize_sentence
from semordnilap.search.domain import SearchPolicy, SemordnilapPair

logger = logging.getLogger(__name__)
FINAL_COUNTS_TABLE = "ngram_final_v2"


def _surface_is_all_stopwords(text: str, lang: str) -> bool:
    return is_all_stopwords(tuple(tokenize_sentence(text)), lang)


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
        self._stopword_function_registered = False

    def _ensure_stopword_function(self) -> None:
        if self._stopword_function_registered:
            return
        self._con.create_function(
            "semordnilap_is_all_stopwords",
            _surface_is_all_stopwords,
            ["VARCHAR", "VARCHAR"],
            "BOOLEAN",
        )
        self._stopword_function_registered = True

    def iter_pairs(self, policy: SearchPolicy):
        logger.info(
            "Searching finalized semordnilaps: %s/%s -> %s/%s",
            policy.source_lang,
            policy.source_corpus,
            policy.target_lang,
            policy.target_corpus,
        )

        extra_where = self._pair_filter_sql(policy, prefix="AND ")
        limit_clause = (
            f"LIMIT {policy.filter_max_results}"
            if policy.filter_max_results is not None
            else ""
        )
        (
            source_dataset,
            target_dataset,
            src_sql,
            src_params,
            tgt_sql,
            tgt_params,
        ) = self._search_inputs(policy)

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

    def describe_selection(self, policy: SearchPolicy) -> dict:
        source = self._resolve_dataset(
            lang=policy.source_lang,
            corpus=policy.source_corpus,
            dataset_id=policy.source_dataset_id,
        )
        target = self._resolve_dataset(
            lang=policy.target_lang,
            corpus=policy.target_corpus,
            dataset_id=policy.target_dataset_id,
        )
        self._validate_complete_dataset(source)
        self._validate_complete_dataset(target)
        return {
            "source": {
                "lang": policy.source_lang,
                "corpus": policy.source_corpus,
                "dataset_id": source[0],
                "generation": source[2],
            },
            "target": {
                "lang": policy.target_lang,
                "corpus": policy.target_corpus,
                "dataset_id": target[0],
                "generation": target[2],
            },
        }

    def estimate_pairs(self, policy: SearchPolicy) -> dict:
        (
            source_dataset,
            target_dataset,
            src_sql,
            src_params,
            tgt_sql,
            tgt_params,
        ) = self._search_inputs(policy)
        source_candidates = self._con.execute(
            f"SELECT COUNT(*) FROM ({src_sql}) AS candidates",
            src_params,
        ).fetchone()[0]
        target_candidates = self._con.execute(
            f"SELECT COUNT(*) FROM ({tgt_sql}) AS candidates",
            tgt_params,
        ).fetchone()[0]
        where_clause = self._pair_filter_sql(policy, prefix="WHERE ")
        combinations = self._con.execute(
            f"""
            WITH src AS ({src_sql}),
            tgt AS ({tgt_sql})
            SELECT src.n, tgt.n, COUNT(*) AS pairs
            FROM src
            JOIN tgt ON reverse(src.norm_key) = tgt.norm_key
            {where_clause}
            GROUP BY src.n, tgt.n
            ORDER BY src.n, tgt.n
            """,
            [*src_params, *tgt_params],
        ).fetchall()
        matching_pairs = sum(row[2] for row in combinations)
        limited_pairs = (
            min(matching_pairs, policy.filter_max_results)
            if policy.filter_max_results is not None
            else matching_pairs
        )
        return {
            "source_dataset_id": source_dataset[0],
            "source_generation": source_dataset[2],
            "target_dataset_id": target_dataset[0],
            "target_generation": target_dataset[2],
            "source_candidates": source_candidates,
            "target_candidates": target_candidates,
            "matching_pairs": matching_pairs,
            "output_pairs": limited_pairs,
            "combinations": combinations,
        }

    def _search_inputs(self, policy: SearchPolicy):
        if policy.filter_exclude_all_stopword_ngrams:
            self._ensure_stopword_function()
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
            min_count=policy.filter_min_source_count,
            n=policy.filter_source_n,
            min_norm_len=policy.filter_min_norm_len,
            max_norm_len=policy.filter_max_norm_len,
            exclude_punctuation=policy.filter_exclude_punctuation,
            exclude_all_stopwords=policy.filter_exclude_all_stopword_ngrams,
        )
        tgt_sql, tgt_params = self._candidate_sql(
            dataset=target_dataset,
            lang=policy.target_lang,
            corpus=policy.target_corpus,
            min_count=policy.filter_min_target_count,
            n=policy.filter_target_n,
            min_norm_len=policy.filter_min_norm_len,
            max_norm_len=policy.filter_max_norm_len,
            exclude_punctuation=policy.filter_exclude_punctuation,
            exclude_all_stopwords=policy.filter_exclude_all_stopword_ngrams,
        )
        return (
            source_dataset,
            target_dataset,
            src_sql,
            src_params,
            tgt_sql,
            tgt_params,
        )

    def _pair_filter_sql(self, policy: SearchPolicy, *, prefix: str) -> str:
        filters = []
        if policy.filter_exclude_palindromes:
            filters.append("src.norm_key <> tgt.norm_key")
        if policy.filter_exclude_identical_text:
            filters.append(
                "NOT (src.lang = tgt.lang "
                "AND src.corpus = tgt.corpus "
                "AND src.text = tgt.text)"
            )
        return f"{prefix}{' AND '.join(filters)}" if filters else ""

    def _validate_complete_dataset(self, dataset) -> None:
        dataset_id, status, generation = dataset
        if status != "complete" or generation is None:
            raise RuntimeError(f"N-gram dataset is incomplete: {dataset_id}")

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
        n: int | None,
        min_norm_len: int | None,
        max_norm_len: int | None,
        exclude_punctuation: bool,
        exclude_all_stopwords: bool,
    ) -> tuple[str, list]:
        self._validate_complete_dataset(dataset)
        dataset_id, _status, generation = dataset
        where = ["dataset_id = ?", "generation = ?", "count >= ?"]
        params = [lang, corpus, dataset_id, generation, min_count]
        if n is not None:
            where.append("n = ?")
            params.append(n)
        if min_norm_len is not None:
            where.append("length(norm_key) >= ?")
            params.append(min_norm_len)
        if max_norm_len is not None:
            where.append("length(norm_key) <= ?")
            params.append(max_norm_len)
        if exclude_punctuation:
            where.append("NOT has_punctuation")
        if exclude_all_stopwords:
            where.append(
                "NOT semordnilap_is_all_stopwords(surface_display, ?)"
            )
            params.append(lang)
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
