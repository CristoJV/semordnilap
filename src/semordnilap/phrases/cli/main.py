"""Phrase CLI."""

from __future__ import annotations

import argparse
import sys

from semordnilap.phrases.cli import generate


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser("Phrase generation tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate phrase candidates to TSV.",
    )
    generate.add_generation_options(generate_parser, include_io=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = build_argparser().parse_args(argv)
    command = args.command
    delattr(args, "command")
    if command == "generate":
        return generate.run_from_args(args)
    raise ValueError(f"Unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
