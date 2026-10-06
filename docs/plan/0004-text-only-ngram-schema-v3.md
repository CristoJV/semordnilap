# Text-only n-gram schema v3

Status: complete

## Objective

Remove UPOS and sentence-crossing persistence from the n-gram subsystem. Keep
only textual counts plus `has_punctuation`, preserve existing textual legacy
and generation data, and require an explicit migration to schema version 3.
Tagging remains an independent utility but is no longer an n-gram input.

## Phase 1 — Schema v3 and safe migration

Status: complete

- [x] Introduce strict database schema-version detection with current version
      3 and rejection of unsupported future versions.
- [x] Migrate unversioned legacy databases by preserving counts and adding
      `has_punctuation = false` where absent.
- [x] Migrate v2 databases by preserving textual legacy/generation tables and
      dropping legacy, staging and final UPOS tables.
- [x] Remove UPOS writes, joins, compaction and statistics from the repository.
- [x] Test v0-to-v3 and v2-to-v3 migrations, data preservation, idempotence,
      explicit migration requirements and rollback-safe behavior.

Verification: migration tests cover unversioned legacy data, v2 textual
generation preservation, removal of all four UPOS tables, an injected rollback,
idempotent replay and future-version rejection.

## Phase 2 — Text-only n-grams and documentation

Status: complete

- [x] Remove tagged/UPOS models and annotated extraction from `ngrams`.
- [x] Remove `upos_counts` and `cross_sentence_count` from TSV export while
      retaining `has_punctuation`.
- [x] Reject `ud-jsonl` as n-gram input with a clear error.
- [x] Supersede UPOS storage decisions and update architecture, guides, README
      and completed adapter-plan wording.
- [x] Run focused and complete tests, Ruff, CLI smoke checks and diff checks.

Verification: the complete suite passes with 85 tests. Ruff lint and formatter
checks pass for every changed Python file; `git diff --check` passes. CLI help
shows only `auto|txt|jsonl` input formats and exposes the explicit v3 migration
command. ADR 0009 records the final contract and supersedes ADR 0003.
