# ADR 0007: Tagged v2 and reduced core scope

Status: accepted

## Decision

New tagged artifacts use provider-neutral UD JSONL v2 in gzip shards. The
default profile stores UPOS and FEATS; lemma/XPOS require `full`. Shards are
independently durable and the final directory is atomically promoted. V1
readers and active v1 partial resume remain supported.

Stanza uses one model pipeline per process. Documents above a configurable
character bound are split deterministically, restored to global offsets and
recorded; unsplittable/errors are quarantined or fail according to policy.
Parallel model workers remain deferred until benchmark evidence justifies the
extra memory; heartbeats make long calls observable.

The supported source tree is corpus acquisition, tagging, n-grams, shared
utilities and optional modern DuckDB search/scoring. Desktop UI, review,
phrases, FreeLing, embeddings, candidate/dictionary extraction and legacy
search were removed with their commands, tests and dependencies.

The supported pipeline now branches after corpus acquisition: direct raw
n-gram extraction is the low-storage default when lexical counts suffice;
tagged v2 is the optional enrichment branch for contextual UPOS evidence.
Both branches converge on the same idempotent DuckDB generation storage.

## Consequences

- Large tagged outputs have smaller failure domains and bounded document size.
- ES/GL model compatibility has an explicit real-model smoke command.
- The default install exposes `sp_corpus`, `sp_tag`, `sp_ngrams` and optional
  `sp_search_ngrams`; the old `sp_corpus_wikisource` entry point remains only
  as a compatibility alias.
- Historical user data and active partial files are never deleted by source
  cleanup.
