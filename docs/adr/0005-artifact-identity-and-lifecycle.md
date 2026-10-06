# ADR 0005: Artifact identity and lifecycle

Status: accepted

## Decision

Every newly produced corpus and tagged artifact has a versioned manifest with
`writing` or `complete` state, SHA-256 content/shard checksums, immutable
`artifact_id`, semantic configuration, counts and provenance. Tagging readers
validate annotated artifacts within that independent subsystem. `sp_ngrams`
rejects annotated input entirely.

Large source corpora are gzip JSONL directories with independently committed
shards. A sibling `.part` directory and its writing manifest are resumable;
only a complete artifact is atomically promoted. Writers hold a non-blocking
POSIX advisory lock containing PID, host and start time.

A source-collection manifest is the authoritative membership list for direct
n-gram extraction. Corpus adapters resolve only complete child artifacts whose
IDs occur in that list; stale directories, unlisted artifacts and `.part`
directories below the collection root are never scanned implicitly.

Normalization policy `unicode-nfc-casefold-v2` preserves `ñ`; only the
explicit `fold_nasal_letters` policy maps it to `n`. Other accents, including
Portuguese nasal vowels, fold for the compact semordnilap key as before.

## Consequences

- Dataset revision, rejected rows, shard order and checksums are reproducible.
- Empty source records are rejected once and no longer skew tagging progress.
- Interrupted downloads restart after the last committed shard.
- Direct collection extraction cannot accidentally consume an interrupted or
  superseded child merely because it is present on disk.
- Concurrent writers fail before mutating an artifact.
- Existing single-file source corpora remain readable by the raw n-gram
  adapter. Tagged JSONL v1 remains readable only by the tagging subsystem.
