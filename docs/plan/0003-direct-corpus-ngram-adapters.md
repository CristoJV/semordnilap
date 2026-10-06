# Direct corpus n-gram adapters

Status: complete

## Objective

Extract n-grams directly from downloaded Wikisource and CorpusNOS source
artifacts without requiring a persisted UPOS-tagged corpus. Keep tagged input
as an optional richer path, preserve the existing generic raw CLI, and reuse
the current idempotent DuckDB generations rather than introducing new
storage.

## Phase 1 — Source adapters and direct extraction

Status: complete

- [x] Add an explicit `auto|raw|wikisource|corpusnos` source-adapter choice to
      `sp_ngrams extract` while retaining the existing command shape.
- [x] Resolve a Wikisource collection to exactly one language artifact and
      validate that the requested language matches its manifest.
- [x] Resolve a CorpusNOS artifact or complete collection, require Galician,
      and read only the child artifacts named by the collection manifest.
- [x] Derive safe corpus aliases and raw JSONL reader settings, while allowing
      an explicit `--corpus` alias override.
- [x] Feed resolved source shards directly into the existing bounded,
      transactional extraction service without creating tagged data.
- [x] Cover manifest validation, language mismatches, stale partial exclusion,
      CLI compatibility and end-to-end raw extraction into DuckDB.

Acceptance gate: focused adapter, n-gram and recovery tests pass; Ruff passes
for every changed Python file.

Verification: 52 focused adapter, raw, tagged and recovery tests pass. Ruff
passes over the n-gram package and the new adapter suite. A real two-document
CorpusNOS `dta_books` smoke run extracted 85,905 occurrences into 46,106
compacted rows without invoking Stanza or writing tagged data.

## Phase 2 — Decisions, operations and final verification

Status: complete

- [x] Record direct raw extraction as a first-class architectural decision and
      reconcile the UPOS, artifact-identity and core-scope ADRs.
- [x] Update the pipeline, n-gram guide, architecture map and README with
      concrete Wikisource and CorpusNOS commands and their raw/tagged tradeoff.
- [x] Run the complete automated suite, CLI smoke checks and repository diff
      validation.
- [x] Record the final evidence here and mark the plan complete.

Acceptance gate: documentation describes one unambiguous direct path for each
corpus and the complete test suite passes without changing existing tagged or
generic raw behavior.

Verification: ADR 0008 records the direct-adapter decision and ADRs 0001–0007
were reviewed and reconciled where their tagged/source/storage scope changed.
The complete suite passes with 90 tests. Ruff lint passes repository-wide and
all changed Python files pass the formatter check. The `extract --help` smoke
lists `auto`, `raw`, `wikisource` and `corpusnos`; `git diff --check` passes.
