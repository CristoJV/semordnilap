# ADR 0009: Text-only n-gram schema v3

Status: superseded by ADR 0010

## Context

Persisting UPOS distributions required a tagged corpus before extraction,
added four DuckDB relations and expanded every export. Candidate generation
only needs textual frequencies, while creating and storing annotations is the
dominant cost for large corpora.

## Decision

`sp_ngrams` consumes raw source text only. Its stored and exported n-gram
contract contains textual identity, `n`, count, normalized key and
`has_punctuation`. It contains neither UPOS distributions nor a
sentence-crossing field. Annotated `ud-jsonl` input is rejected explicitly;
the standalone tagging subsystem may continue producing that format for other
consumers.

DuckDB schema version 3 keeps the existing textual legacy and generation table
names so their rows can be preserved. Migration is explicit:

```bash
uv run sp_ngrams db migrate --db-path data/ngrams/counts.duckdb
```

- unversioned/v0/v1 stores gain `has_punctuation`, defaulting historical rows
  to `false`;
- v2 stores retain every textual count, generation and extraction ledger row;
- `ngram_upos_counts`, `ngram_upos_totals`, `ngram_upos_stage_v2` and
  `ngram_upos_final_v2` are dropped;
- rerunning migration is a no-op, and databases newer than v3 are rejected.

## Consequences

- CorpusNOS and Wikisource flow directly into bounded, resumable extraction
  without a tagged intermediate artifact.
- Migration deliberately discards only grammatical UPOS data; textual counts
  remain available.
- Historical punctuation cannot be reconstructed, so migrated legacy rows use
  the conservative value `false`; new rows compute it from their surface.
- TSV schema version 2 removes `upos_counts` and `cross_sentence_count`.
