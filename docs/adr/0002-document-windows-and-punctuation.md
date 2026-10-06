# ADR 0002: Document-wide n-gram windows

Status: accepted

## Decision

The document is the only hard extraction boundary. Lexical windows cross
punctuation and sentence boundaries by default while retaining intervening
punctuation. `--omit-punctuation` exists only as an explicit compatibility
mode.

The raw-text adapter uses the span from the first lexical token start through
the last lexical token end. Trailing punctuation does not belong to a unigram.
Text identity is NFC, Unicode case-folded and has internal whitespace
collapsed; a normalized-whitespace source spelling is retained for display.
`has_punctuation` records whether the stored surface contains punctuation.

Source-corpus extraction uses Unicode lexical spans over each complete source
document. Annotated input is outside the n-gram contract.

## Consequences

- Surfaces such as `niña, el` and `camino. Antes` are representable.
- No window can combine tokens from different documents.
- Sentence crossing is not stored as a separate property; punctuation remains
  observable through the surface and `has_punctuation`.
