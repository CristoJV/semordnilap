# ADR 0008: Direct source-corpus n-gram adapters

Status: accepted

## Context

Persisting contextual UD annotations is substantially slower and larger than
the downloaded text. Lexical candidate generation does not require those
annotations, and the n-gram domain already has a Unicode raw-text tokenizer.
Generic recursive directory reading, however, is unsafe for managed corpus
collections because stale or interrupted children may coexist below the same
root.

## Decision

`sp_ngrams extract` supports manifest-aware `wikisource` and `corpusnos`
source adapters plus `auto` selection and the existing generic `raw` reader.
Language remains an explicit required argument.

The Wikisource adapter resolves a collection to exactly one complete artifact
matching `--lang`. The CorpusNOS adapter accepts either one configured
artifact or a complete collection and only accepts `--lang gl`. Collection
membership and ordering come from the collection manifest; filesystem
discovery is used only to locate matching child artifact IDs. Unlisted and
partial directories are ignored.

Adapters set JSONL/text-field configuration and derive a readable corpus alias
that `--corpus` may override. They stream the selected source shards directly
through the raw tokenizer and transactional DuckDB extraction. They do not
create an intermediate dataset.

## Consequences

- Wikisource and CorpusNOS can be processed without running Stanza or storing
  tagged shards.
- `has_punctuation` is derived from each textual surface; no grammatical or
  sentence-crossing metadata is persisted.
- Adapter and source artifact identity participate in idempotent extraction;
  retry and bounded-memory behavior remain unchanged.
- The generic raw reader remains backward compatible. Tagged UD is rejected
  by `sp_ngrams` with an explicit error.
- Supporting another managed corpus requires a manifest resolver, language
  validation and tests, not a new n-gram engine or database schema.
