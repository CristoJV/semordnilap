# ADR 0001: Provider-neutral UPOS JSONL

Status: accepted

## Decision

The canonical persisted **tagged** corpus is provider-neutral, versioned UD
JSONL. It stores the original text, ordered sentences, absolute token offsets,
surface tokens, underlying syntactic words and Universal Dependencies fields.
This contract belongs to the standalone tagging utility. Lexical n-gram
extraction consumes source-corpus text directly and does not consume this
format.

Physical v2 uses independently checksummed gzip JSONL shards. Its default
`compact` profile stores UPOS and FEATS; `full` also stores lemma and XPOS.
Token surfaces are reconstructed from the document and offsets. Readers keep
v1 compatibility.

The schema belongs to Semordnilap. Stanza is an infrastructure adapter and its
Python objects or serialization formats do not cross the adapter boundary.

## Consequences

- A future tagger can replace Stanza by producing the same domain model.
- Direct source extraction avoids the tagged artifact's runtime and disk cost.
- Tagged artifacts can serve future or external consumers, but no longer
  affect n-gram storage or export.
- Exact cross-sentence surfaces can be reconstructed from document text and
  offsets.
- JSONL remains streamable by document while gzip shards reduce expansion and
  failure domains.
- Schema changes require an explicit version and reader migration.
