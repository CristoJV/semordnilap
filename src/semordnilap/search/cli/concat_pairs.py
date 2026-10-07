"""Concatenate compatible semordnilap pair TSV files."""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

from semordnilap.utils.artifacts import ArtifactLock, atomic_output


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)
IDENTITY_COLUMNS = {"pair_id", "lexical_pair_id"}


def concat_pair_tsvs(input_paths: list[Path], output_path: Path) -> int:
    """Append pair rows under one validated header and return their count."""

    if not input_paths:
        raise ValueError("At least one input TSV is required")
    output_resolved = output_path.resolve()
    if any(path.resolve() == output_resolved for path in input_paths):
        raise ValueError("Output TSV cannot also be an input TSV")

    expected_fields: list[str] | None = None
    rows_written = 0
    with ArtifactLock(output_path), atomic_output(output_path) as output:
        writer = None
        for input_path in input_paths:
            with input_path.open("r", encoding="utf-8", newline="") as source:
                reader = csv.DictReader(source, delimiter="\t")
                fields = reader.fieldnames
                if not fields:
                    raise ValueError(f"TSV has no header: {input_path}")
                if len(fields) != len(set(fields)):
                    raise ValueError(
                        f"TSV has duplicate columns: {input_path}"
                    )
                missing = IDENTITY_COLUMNS.difference(fields)
                if missing:
                    names = ", ".join(sorted(missing))
                    raise ValueError(
                        f"TSV is missing identity columns ({names}): "
                        f"{input_path}"
                    )
                if expected_fields is None:
                    expected_fields = fields
                    writer = csv.DictWriter(
                        output,
                        fieldnames=expected_fields,
                        delimiter="\t",
                    )
                    writer.writeheader()
                elif fields != expected_fields:
                    raise ValueError(
                        f"TSV header does not match the first input: "
                        f"{input_path}"
                    )

                assert writer is not None
                for row in reader:
                    writer.writerow(row)
                    rows_written += 1

    return rows_written


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        "Concatenate semordnilap pair TSV files under one header"
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("inputs", type=Path, nargs="+")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(
        argv if argv is not None else sys.argv[1:]
    )
    rows = concat_pair_tsvs(args.inputs, args.out)
    logger.info("Concatenated %d rows into %s", rows, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
