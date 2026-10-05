# Contextual UPOS tagging and n-gram extraction

Status: complete

Historical implementation plan. The resulting architecture and its remaining
risks were audited later in
[RFC 0001](../rfc/0001-core-pipeline-hardening.md).

## Goal

Annotate complete Spanish and Galician documents with a replaceable POS
tagger, persist a provider-neutral UPOS JSONL corpus, and extract n-grams with
their observed UPOS distributions. With `--keep-punctuation`, n-grams may
cross punctuation and sentence boundaries but never document boundaries.

## Phase 1: tagging contract and application

Status: complete

- [x] Define a versioned, provider-neutral annotated-document model.
- [x] Add JSONL readers/writers and a run manifest.
- [x] Add a Stanza adapter for `es` and `gl` using UPOS.
- [x] Add explicit model-download and corpus-annotation CLI commands.
- [x] Add unit tests and verify the tagging subsystem before phase 2.

Verification: `5 passed` in the tagging suite and `76 passed` in the complete
suite before starting phase 2.

## Phase 2: annotated n-gram extraction and storage

Status: complete

- [x] Read annotated JSONL without retokenizing or retagging.
- [x] Preserve exact punctuation between lexical tokens and allow
      cross-sentence windows under `--keep-punctuation`.
- [x] Count one textual n-gram plus its UPOS-pattern distribution.
- [x] Store and compact UPOS counts in separate DuckDB relations.
- [x] Export `upos_counts` and `cross_sentence_count` with each textual row.
- [x] Verify migrations, compaction, deletion, export, MWTs, punctuation, and
      cross-sentence extraction before phase 3.

Verification: `31 passed` in the n-gram-focused suite after the initial
integration, followed by `82 passed` in the complete suite with an end-to-end
annotated JSONL extraction test.

## Phase 3: end-to-end verification and documentation

Status: complete

- [x] Run the complete automated test suite and static formatting checks.
- [x] Smoke-test the CLI flow with deterministic local fixtures.
- [x] Add the operational guide from corpus download through tagging and
      n-gram extraction.
- [x] Update existing documentation and mark this plan complete.
- [x] Stream durable partial output, checkpoint it periodically, and support
      validated restart without duplicate documents.
- [x] Persist source/output byte cursors for constant-time resume, migrate
      legacy partials with resumable byte progress, and defer Stanza loading
      until recovery completes.

Verification: both CLI entry points load and expose the documented options;
Ruff passes for the tagging and n-gram implementation and their tests; the
complete project suite finishes with `84 passed`. A live Spanish Stanza smoke
run processed the first Wikisource document (6,461 characters) as 34 sentences
and 1,279 tokens while displaying document-level progress. Interruption tests
also verify persisted document checkpoints, truncated-line recovery, and
duplicate-free resume. The subsequent checkpoint-v2 hardening adds tests for
direct cursor resume, safe uncheckpointed-suffix truncation, one-pass legacy
indexing, interruption during indexing, and source cursor positioning.

Latest verification: `89 passed` in the complete suite; Ruff passes for the
tagging package and its focused tests. The real 9,567-document legacy
checkpoint was also accepted read-only without constructing a Stanza pipeline.

## Acceptance criteria

- A surface such as `bajo el` has one total count and multiple UPOS counts.
- `niña, el` and `camino. Antes` can be extracted with their inherited UPOS
  tags when `--keep-punctuation` is enabled.
- Sentence order, document text, and absolute offsets survive serialization.
- Multi-word tokens retain surface-token identity and use `+` between their
  underlying UPOS values, for example `ADP+DET NOUN`.
- Existing plain-text and JSONL n-gram extraction remains compatible.
- The stored format contains no Stanza-specific object or field dependency.
- Tagging keeps at most one source/annotated document in application memory and
  can resume a compatible `.part` stream after interruption.
