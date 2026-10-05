# ADR 0005: Artifact identity and lifecycle

Status: accepted

## Decision

Every newly produced corpus and tagged artifact has a versioned manifest with
`writing` or `complete` state, SHA-256 content/shard checksums, immutable
`artifact_id`, semantic configuration, counts and provenance. Consumers reject
incomplete annotated artifacts by default. An explicitly unsafe recovery flag
is required to consume an unmanifested tagged stream.

Large source corpora are gzip JSONL directories with independently committed
shards. A sibling `.part` directory and its writing manifest are resumable;
only a complete artifact is atomically promoted. Writers hold a non-blocking
POSIX advisory lock containing PID, host and start time.

Normalization policy `unicode-nfc-casefold-v2` preserves `ñ`; only the
explicit `fold_nasal_letters` policy maps it to `n`. Other accents, including
Portuguese nasal vowels, fold for the compact semordnilap key as before.

## Consequences

- Dataset revision, rejected rows, shard order and checksums are reproducible.
- Empty source records are rejected once and no longer skew tagging progress.
- Interrupted downloads restart after the last committed shard.
- Concurrent writers fail before mutating an artifact.
- Existing single-file source corpora and tagged JSONL v1 remain readable and
  receive computed identities when no historical manifest exists.
