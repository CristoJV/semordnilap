"""Application services for reviewing semordnilap pairs."""

from __future__ import annotations

from semordnilap.review.domain import ReviewFilters, ReviewRow


TABLE_HEADERS = [
    "source_text",
    "target_text",
    "pair_score",
    "source_count",
    "target_count",
    "source_n",
    "target_n",
    "source_norm_key",
    "target_norm_key",
]


def filter_rows(
    rows: list[ReviewRow], filters: ReviewFilters
) -> list[ReviewRow]:
    matched = [row for row in rows if filters.matches(row)]
    matched.sort(
        key=lambda row: (
            -row.pair_score,
            -row.source_count,
            -row.target_count,
            row.source_text,
            row.target_text,
        )
    )
    return matched[: filters.limit]


def rows_to_table(rows: list[ReviewRow]) -> list[list]:
    return [
        [
            row.source_text,
            row.target_text,
            row.pair_score,
            row.source_count,
            row.target_count,
            row.source_n,
            row.target_n,
            row.source_norm_key,
            row.target_norm_key,
        ]
        for row in rows
    ]


def build_detail_markdown(row: ReviewRow | None) -> str:
    if row is None:
        return "Select a row to inspect it."

    status = "match" if row.key_matches else "mismatch"
    return "\n".join(
        [
            f"## {row.source_text} ⇄ {row.target_text}",
            "",
            f"**Score:** `{row.pair_score}`",
            "",
            "| Field | Source | Target |",
            "|---|---:|---:|",
            f"| Language | `{row.source_lang}` | `{row.target_lang}` |",
            f"| Corpus | `{row.source_corpus}` | `{row.target_corpus}` |",
            f"| Tokens | `{row.source_n}` | `{row.target_n}` |",
            f"| Count | `{row.source_count}` | `{row.target_count}` |",
            f"| Norm key | `{row.source_norm_key}` | `{row.target_norm_key}` |",
            "",
            f"`reverse({row.source_norm_key}) = {row.reversed_source_key}`",
            "",
            f"Key check: **{status}**",
        ]
    )

