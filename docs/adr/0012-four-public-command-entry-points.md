# ADR 0012: Four public command entry points

Status: accepted

## Context

The package exposed separate compatibility and helper executables alongside
its primary workflows. `sp_corpus_wikisource` duplicated functionality now
available through the `wikisource` subcommand of `sp_corpus`.
`sp_search_ngrams` exposed an implementation detail in its name, while pair
concatenation did not warrant a separate top-level application.

## Decision

The installed `[project.scripts]` surface contains exactly four commands:

| Command | Responsibility |
|---|---|
| `sp_corpus` | Download and prepare supported source corpora. |
| `sp_tag` | Run the independent contextual-tagging utility. |
| `sp_ngrams` | Extract, inspect, migrate and export corpus n-grams. |
| `sp_semord` | Search finalized n-gram generations for semordnilaps. |

`sp_semord` replaces the former `sp_search_ngrams` name.
`sp_corpus_wikisource` and `sp_concat_pairs` are no longer installed entry
points. Their internal modules may remain as implementation or library code;
this decision concerns the public executable surface.

## Consequences

- Users invoke Wikisource acquisition as `sp_corpus wikisource`.
- Search documentation and examples use `sp_semord`.
- Existing automation using any removed executable must update its command.
- Adding another installed executable requires a new explicit command-surface
  decision; helper operations should normally become subcommands.

