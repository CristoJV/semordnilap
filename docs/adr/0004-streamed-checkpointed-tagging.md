# ADR 0004: Streamed and checkpointed tagging

Status: accepted

## Decision

Tagging is an optional enrichment stage for consumers that need contextual
UPOS/FEATS. It is not a prerequisite for lexical n-gram extraction; source
adapters can stream downloaded corpus shards directly into the n-gram engine.

Legacy v1 writes one annotated document per JSONL line to a persistent `.part` file. Flush
and `fsync` it every configurable number of completed documents (10 by
default), recording compatible run metadata in `.part.meta.json`. Promote the
partial file atomically only after the whole corpus succeeds.

The checkpoint format is versioned independently. Version 2 stores two durable
positions after every checkpointed document batch:

- the byte offset in the annotated `.part` JSONL;
- the source file, source-line number, and source byte offset.

It also records the input reader options and a SHA-256 snapshot of every
source file. `--resume` checks that snapshot and the run metadata, truncates
any uncheckpointed output suffix, seeks directly to both offsets, and restarts
at the first unfinished document. No completed prefix is deserialized again.

Existing checkpoints without offsets remain supported. Their `.part` is
deserialized and compared with the source exactly once while a byte progress
bar is displayed. This indexing writes resumable `recovering` checkpoints, so
an interruption of the migration itself continues from its last indexed
record. At completion the metadata is promoted to checkpoint v2; `--force` is
not required. Stanza model construction is deferred until the first new
document, after recovery has finished.

## Consequences

- Application memory is bounded to the current source and annotated document.
- A hard stop may require reprocessing at most the uncheckpointed documents
  but never duplicates a completed JSONL record.
- Smaller checkpoint intervals improve durability while increasing disk-sync
  overhead.
- A legacy multi-gigabyte partial incurs one linear indexing pass. Later
  resumes are O(1) apart from source inventory/counting.
- Source and Stanza model files have cryptographic identities in new
  checkpoints and final manifests. Legacy checkpoints remain readable.
- Workloads that need only lexical frequencies can omit this entire storage
  lifecycle without weakening raw extraction resumability in DuckDB.

New jobs default to v2 gzip shards. Each completed shard records ordered
document ordinals, source cursor and checksum before advancing the checkpoint.
Resume starts after the last finalized shard. Long documents are split at
deterministic safe boundaries with global offsets; indivisible or failed
documents are quarantined by default. A daemon heartbeat reports progress
while Stanza processes one fragment.
