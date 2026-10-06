# ADR 0002: Document-wide n-gram windows

Status: accepted

## Decision

The document is the only hard extraction boundary. Lexical windows cross
punctuation and sentence boundaries by default while retaining intervening
punctuation. `--omit-punctuation` exists only as an explicit compatibility
mode.

Raw and annotated adapters use the same surface rule: from the first lexical
token start through the last lexical token end. Trailing punctuation does not
belong to a unigram. Text identity is NFC, Unicode case-folded and has internal
whitespace collapsed; a normalized-whitespace source spelling is retained for
display.

UPOS tags are inherited from the original sentence-level analysis; a
cross-sentence fragment is never retagged in isolation. Cross-sentence
occurrences are counted separately as metadata.

Raw source-corpus extraction is a first-class mode, not a compatibility
fallback. It uses Unicode lexical spans over each complete source document;
annotated extraction remains available when inherited sentence boundaries and
UPOS patterns justify its extra cost.

## Consequences

- Surfaces such as `niña, el` and `camino. Antes` are representable.
- Consumers can include, filter, or penalize cross-sentence evidence later.
- No window can combine tokens from different documents.
- Raw and tagged input cannot produce different keys for the same spans.
