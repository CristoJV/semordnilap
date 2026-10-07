# ADR 0011: Unrestricted search and reproducible pair exports

Status: accepted

## Context

The semordnilap search CLI previously applied implicit reductions: minimum
counts of three, exclusion of normalized palindromes and identical text, and
magic zero values for “all sizes”, “no length bound” and “unlimited results”.
Its option names did not distinguish dataset selection from filtering. Pair
TSVs were written directly, had no manifest and could be left truncated after
a failed process.

These defaults conflicted with the extraction policy established by ADR 0010:
retain the widest useful dataset and make lossy decisions explicit. They also
made a command line insufficient to explain whether an omitted option widened
or narrowed the result.

## Decision

Search defaults to the complete available result set:

- stored counts from one upward are eligible;
- all stored n-gram sizes and normalized-key lengths are eligible;
- punctuation, numeric characters and all-stopword policy do not remove
  candidates;
- normalized palindromes and identical text are included;
- output has no row limit.

Every option that reduces this set uses the `--filter-` prefix. Optional
bounds are represented by absence, not by a magic zero. In particular,
`--filter-max-results` accepts positive integers and is omitted for an
unlimited result. Former option names are removed rather than retained as
aliases, so commands cannot silently preserve the old semantics.

The CLI provides `--dry-run`, which resolves and validates both datasets and
computes exact candidate, matching-pair and `source_n × target_n` counts
without writing an artifact. It is exact rather than sampled, so it still
executes the aggregate join.

Pair exports use an advisory writer lock, a sibling partial file, filesystem
synchronization and atomic promotion. A sidecar manifest records the checksum,
artifact identity, exact datasets and generations, search policy, ordering,
score formula, row count, size distribution, punctuation count and score
summary. Periodic progress is configurable independently of filtering.

## Consequences

- Omitting a filter never silently removes a class of candidate or pair.
- Potentially very large exports are possible by design; users should run
  `--dry-run` or add explicit filters when operational limits matter.
- Old command lines must be updated to the `--filter-*` names and must omit a
  result-limit option instead of passing zero.
- Palindromic keys in an auto-join can produce a Cartesian product of their
  stored surfaces; this is visible in dry-run and final size distributions.
- A failed row iteration cannot replace a previously complete TSV.
- Completed outputs can be tied to their immutable inputs and verified by
  checksum after aliases move to newer active generations.
