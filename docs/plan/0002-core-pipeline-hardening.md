# Core pipeline hardening implementation plan

Status: complete  
RFC: [0001-core-pipeline-hardening](../rfc/0001-core-pipeline-hardening.md)

## Objective

Turn `corpus -> contextual UPOS tagging -> n-grams` into a reproducible,
restartable and bounded pipeline. Preserve read compatibility with tagged
JSONL v1 and legacy DuckDB data while making new artifacts self-identifying
and safe to retry. Retain modern DuckDB search as an optional read-only
consumer and remove every other legacy application path.

## Decisions that close the RFC questions

- Keep `sp_search_ngrams` as the only optional downstream command.
- Tagged v2 defaults to UPOS plus UD features; lemma and XPOS belong to an
  explicit `full` profile.
- Use gzip-compressed JSONL shards. It is streamable, inspectable and requires
  no additional runtime dependency; Parquet remains unnecessary until a
  measured query workload justifies it.
- Text identity is NFC + Unicode case-folding + collapsed whitespace.
  `surface_display` retains the first normalized-whitespace source spelling.
- Persist all accepted frequencies. Filtering by minimum frequency is an
  export concern, not a lossy extraction step.
- Delete committed staging after validated finalization by default. An
  explicit retention option may keep it for diagnosis.
- Benchmarks record throughput, peak RSS and disk amplification on the machine
  that runs them; they are reports, not hardware-specific pass/fail gates.

## Phase 1 — Contracts, correctness and artifact lifecycle

Status: complete

- [x] Add shared canonical JSON hashing, file/artifact digests, complete
      manifests, atomic promotion and advisory locks.
- [x] Make Wikisource export streaming, filtered, progress-visible, sharded,
      compressed, revision-pinned and restart-safe, with per-language and
      collection manifests.
- [x] Fix versioned normalization (`ñ` preserved unless explicitly folded),
      Unicode tokenization, canonical surfaces and raw/tagged adapter parity.
- [x] Detect annotated input from schema/manifest under `--format auto` and
      reject incomplete tagged artifacts unless explicitly allowed.
- [x] Centralize extraction-policy validation and make punctuation crossing
      the invariant/default.
- [x] Strengthen annotation IDs, ordering, non-overlap and source-span
      validation; record exact Stanza model digests.
- [x] Add atomic tagging finalization, completion recovery and
      concurrent-writer protection.
- [x] Record these contracts in ADRs and pass focused plus complete tests
      before phase 2.

Verification: 55 focused tests and 100 complete tests pass. Ruff passes for
the supported core; the five remaining full-tree findings are confined to the
legacy GUI scheduled for removal in phase 3. Atomic TSV export is grouped with
the storage transaction work in phase 2.

## Phase 2 — Idempotent extraction and bounded storage

Status: complete

- [x] Introduce explicit DuckDB schema migrations plus immutable dataset and
      policy identities, run state and unique committed chunk IDs.
- [x] Commit a chunk's text counts, UPOS counts, metrics and checkpoint in one
      transaction; replaying it must be a no-op.
- [x] Separate `resume`, `restart` and a new source identity. Samples must have
      distinct identities and cannot be mistaken for full artifacts.
- [x] Stream raw and annotated windows into a bounded accumulator, including
      deterministic sub-document chunks for pathological documents.
- [x] Build validated final generations and retire staging after successful
      promotion so raw and compact representations are not permanently
      duplicated.
- [x] Make compact reads fail when incomplete; make stats read-only; make
      reset/delete transactional and TSV export atomic.
- [x] Add persistence-boundary fault injection, replay, source-change,
      concurrent-writer, migration and memory-bound tests; verify the complete
      suite before phase 3.

Verification: 52 focused n-gram/search tests and 110 complete tests pass.
Ruff passes over the supported core. Chunk persistence uses bulk COPY inside
the transaction; selector tests cover ambiguous aliases in export and search.

## Phase 3 — Scalable tagged v2, cleanup and final documentation

Status: complete

- [x] Write compact gzip tagged shards with independent checksums, ordered
      document ordinals, global offsets and manifests; keep v1 readers and
      resume active v1 partials without rewriting them.
- [x] Add deterministic long-document splitting/quarantine, a bounded
      single-pipeline workload, ordered output and heartbeat/throughput metrics.
- [x] Add ES/GL real-model smoke targets and repeatable benchmark commands for
      small, 10k, 1M-window and oversized-document fixtures.
- [x] Remove `app`, `review`, `phrases`, FreeLing and confirmed-unused legacy
      extraction/candidate/embed/language/loading/search-engine paths, their
      tests, scripts, commands and dependencies. Do not delete user data.
- [x] Reduce the installed command surface to `sp_corpus_wikisource`, `sp_tag`,
      `sp_ngrams` and optional `sp_search_ngrams`; regenerate the lockfile.
- [x] Update all ADRs, guides, technical architecture, README and RFC status;
      run clean-install/import/CLI/full-test/Ruff checks and record results.

Verification: 79 tests pass after removal of 33 legacy-only tests; Ruff passes
over the complete repository; all four installed CLI help targets and core
imports pass. Real local Stanza models pass for ES (7 tokens, model digest
`3bc25b...55dcecd`) and GL (7 tokens, `7744a0...e1c9de87`). The recorded
benchmark produced 112k windows/s at 10k, 109k windows/s at 1M, and 115k
windows/s on the oversized fixture. The encoding fixture measured v2 compact
gzip at 2.42x source UTF-8 versus 47.46x for uncompressed v1 JSON. Peak RSS is
reported by the script. Parallel Stanza workers remain deliberately deferred:
the RFC required
measurement before multiplying model memory, and a bounded one-pipeline design
plus long-document splitting satisfies the memory contract.

## Global acceptance gate

Every RFC acceptance criterion must map to an automated test, a reproducible
smoke/benchmark command, or a documented operational invariant. A phase is not
complete until its checklist, ADRs and verification record are updated.

Acceptance gate: complete.
