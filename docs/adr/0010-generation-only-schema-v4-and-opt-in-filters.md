# ADR 0010: Generation-only schema v4 and opt-in extraction filters

Status: accepted

## Context

The n-gram subsystem retained two storage protocols: legacy partial/total
tables and resumable generations. That duplicated read, search, statistics,
deletion and CLI behavior. The legacy compaction performed a blocking rebuild
without document checkpoints or atomic generation activation.

Extraction also discarded all-stopword windows by default and exposed filter
options with inconsistent names. Changing those decisions later required a
complete audit and re-extraction because data rejected before staging cannot be
restored by search-time filters.

## Decision

DuckDB schema version 4 supports only resumable generations. Counting writes
transactional chunks to `ngram_stage_v2`; finalization aggregates independently
by `n` and hash bucket, checkpoints every part and atomically activates
`ngram_final_v2`. Export and search read only the active generation.

The public CLI removes compact operations, raw/compact source selectors and
compatibility aliases. Schema v3 can be migrated explicitly and transactionally
to v4. Migration preserves all generation metadata, chunks, staging, final rows
and finalization checkpoints, then drops `ngram_counts`, `ngram_totals` and
`ngram_compactions`. Schemas v0–v2 are not interpreted by the new code.

Extraction defaults favor retention:

| Option | Default | Meaning |
|---|---:|---|
| `--filter-min-token-len` | `2` | Reject shorter tokens except language whitelist entries. |
| `--filter-max-token-len` | `30` | Reject longer tokens. |
| `--filter-min-norm-len` | `2` | Reject shorter normalized keys. |
| `--filter-all-stopword-ngrams` | off | All-stopword windows are retained unless enabled. |
| `--filter-punctuation-boundaries` | off | Punctuation is retained and may be crossed unless enabled. |
| `--preserve-nasal-letters` | off | `ñ` folds to `n` by default; this option preserves it. |

Every option that discards candidate windows uses the `--filter-` prefix.
`--preserve-nasal-letters` changes normalization rather than filtering rows.
All policy values remain part of `policy_hash`, so changing one creates a
distinct immutable dataset.

## Consequences

- There is one persistence and recovery protocol throughout extraction,
  export, statistics, deletion and search.
- A flush changes only the physical segmentation of staging; it never changes
  logical counts. Finalization recombines every partial count with `SUM`.
- All-stopword n-grams and punctuation-crossing surfaces remain available for
  later search-time decisions by default.
- Opt-in extraction filters permanently omit matching windows and therefore
  require a new dataset identity.
- Existing v3 generation work, including an interrupted finalization, is
  recoverable after migration without rereading the corpus.
- Old databases without the v3 generation contract must be re-extracted or
  converted outside this application.

This ADR supersedes the schema and migration portions of ADR 0009, the schema
version paragraph of ADR 0006, and the old punctuation flag name in ADR 0002.
