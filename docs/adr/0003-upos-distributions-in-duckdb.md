# ADR 0003: Separate UPOS distribution relations

Status: accepted

## Decision

Textual n-gram totals remain in `ngram_counts` and `ngram_totals`. Observed
UPOS patterns are stored in parallel `ngram_upos_counts` and
`ngram_upos_totals` relations keyed by the same textual identity plus pattern
and cross-sentence status.

An ordinary token contributes one UPOS slot. A UD multi-word surface token
joins the UPOS values of its underlying words with `+`, so the number of
space-separated pattern slots continues to equal `n`.

## Consequences

- Grammatical interpretations do not create duplicate textual n-grams.
- Pattern counts remain queryable and compactable in SQL.
- TSV export can expose a compact JSON distribution while DuckDB retains a
  normalized representation.

