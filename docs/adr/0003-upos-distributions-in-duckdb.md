# ADR 0003: Separate UPOS distribution relations

Status: superseded by [ADR 0009](0009-text-only-ngram-schema-v3.md)

This record describes the former schema v2 design. Schema v3 removes every
UPOS relation and export field.

## Decision

Textual n-gram totals remain in `ngram_counts` and `ngram_totals`. Observed
UPOS patterns are stored in parallel `ngram_upos_counts` and
`ngram_upos_totals` relations keyed by the same textual identity plus pattern
and cross-sentence status.

An ordinary token contributes one UPOS slot. A UD multi-word surface token
joins the UPOS values of its underlying words with `+`, so the number of
space-separated pattern slots continues to equal `n`.

Direct raw extraction writes the same textual totals but no rows to the UPOS
relations. An empty exported `upos_counts` and zero `cross_sentence_count`
therefore mean "not observed from tagged input", not a claim about grammar.

## Consequences

- Grammatical interpretations do not create duplicate textual n-grams.
- Pattern counts remain queryable and compactable in SQL.
- TSV export can expose a compact JSON distribution while DuckDB retains a
  normalized representation.
