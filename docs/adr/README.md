# Architecture decision records

- [ADR 0001](0001-provider-neutral-upos-jsonl.md): provider-neutral UPOS JSONL.
- [ADR 0002](0002-document-windows-and-punctuation.md): document-wide windows
  with punctuation.
- [ADR 0003](0003-upos-distributions-in-duckdb.md): former normalized UPOS
  count relations (superseded).
- [ADR 0004](0004-streamed-checkpointed-tagging.md): streamed, resumable
  tagging.
- [ADR 0005](0005-artifact-identity-and-lifecycle.md): immutable manifests,
  checksums, locks and normalization identity.
- [ADR 0006](0006-idempotent-ngram-generations.md): transactional chunks,
  immutable extraction identities and validated generations.
- [ADR 0007](0007-tagged-v2-and-core-scope.md): compressed tagged shards,
  long-document policy and reduced supported scope.
- [ADR 0008](0008-direct-source-corpus-adapters.md): manifest-aware direct
  Wikisource and CorpusNOS extraction without persisted tagging.
- [ADR 0009](0009-text-only-ngram-schema-v3.md): text-only n-gram persistence,
  `has_punctuation` and explicit legacy migration (superseded).
- [ADR 0010](0010-generation-only-schema-v4-and-opt-in-filters.md):
  generation-only schema v4, v3 cleanup migration and opt-in extraction
  filters.

These records describe accepted behavior or mark the decision that superseded
it. Proposed replacements or migrations belong in
[RFCs](../rfc/README.md) until accepted.
