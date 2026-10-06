# ADR 0006: Idempotent n-gram generations

Status: accepted

## Decision

An extracted dataset is identified by the source artifact ID and a hash of
every semantic extraction option. The language and corpus names are aliases,
not identities. Each deterministic document segment is committed once under
a unique chunk ID and digest.

For manifest-aware source extraction, the policy hash also records the
selected corpus adapter. A collection uses its own artifact ID while the
adapter supplies the exact ordered child shards. Existing generic `raw`
extraction keeps its historical policy identity.

Text counts, the chunk ledger and the run checkpoint are written in one
DuckDB transaction. Replaying a matching committed chunk is a no-op; reusing
its ID with different content fails. Final totals are built as a new validated
generation and become active in the same transaction. Successful finalization
removes staging unless retention is explicitly requested.

New databases use schema version 3 and store only textual counts plus
`has_punctuation`. Existing databases require the explicit
`sp_ngrams db migrate` operation; v0/v1 gain `has_punctuation=false`, while v2
keeps textual rows and drops all UPOS tables. Read-only inspection never
migrates, and versions newer than the supported one are rejected. When an
alias resolves to multiple immutable datasets, readers require `dataset_id`.
TSV exports use a partial file, checksum manifest and atomic promotion.

## Consequences

- Retrying extraction cannot duplicate counts.
- Policy changes and limited samples cannot mix with a complete dataset.
- Memory is bounded by the streaming token window and configured maximum
  pending unique n-grams, including within one large document.
- Final storage does not permanently duplicate staging and aggregate rows.
- Human aliases remain convenient, but ambiguity is visible rather than
  silently selecting or combining incompatible data.
