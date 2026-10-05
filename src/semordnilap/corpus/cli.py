"""Command line entry point for corpus downloaders."""

from __future__ import annotations

import argparse

from semordnilap.corpus import corpusnos, wikisource


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download and prepare source corpora."
    )
    subparsers = parser.add_subparsers(dest="corpus", required=True)

    wikisource_parser = subparsers.add_parser(
        "wikisource", help="download Spanish and/or Galician Wikisource"
    )
    wikisource.configure_parser(wikisource_parser)
    wikisource_parser.set_defaults(handler=wikisource.run)

    corpusnos_parser = subparsers.add_parser(
        "corpusnos", help="download selected Galician CorpusNOS subsets"
    )
    corpusnos.configure_parser(corpusnos_parser)
    corpusnos_parser.set_defaults(handler=corpusnos.run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
