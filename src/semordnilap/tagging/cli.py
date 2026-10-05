"""CLI for contextual corpus tagging."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from semordnilap.tagging.application import (
    TagCorpusCommand,
    partial_output_path,
    tag_corpus,
)
from semordnilap.tagging.stanza import StanzaPosTagger, download_models
from semordnilap.tagging.domain import SourceDocument

logger = logging.getLogger(__name__)


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        "Annotate Spanish and Galician corpora with contextual UPOS tags"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser(
        "download", help="Download Stanza models."
    )
    download.add_argument(
        "--langs", nargs="+", choices=["es", "gl"], required=True
    )
    download.add_argument("--model-dir", type=Path)
    download.add_argument("--package", default="default")

    smoke = subparsers.add_parser(
        "smoke", help="Run an explicit ES/GL smoke test with local models."
    )
    smoke.add_argument(
        "--langs", nargs="+", choices=["es", "gl"], required=True
    )
    smoke.add_argument("--model-dir", type=Path)
    smoke.add_argument("--package", default="default")
    smoke.add_argument("--use-gpu", action="store_true")

    annotate = subparsers.add_parser("annotate", help="Annotate a corpus.")
    annotate.add_argument("--input", type=Path, required=True)
    annotate.add_argument("--out", type=Path, required=True)
    annotate.add_argument("--lang", choices=["es", "gl"], required=True)
    annotate.add_argument(
        "--format", choices=["auto", "txt", "jsonl"], default="auto"
    )
    annotate.add_argument("--text-field", default="text")
    annotate.add_argument("--id-field", default="id")
    annotate.add_argument("--limit-docs", type=int, default=0)
    annotate.add_argument("--model-dir", type=Path)
    annotate.add_argument("--package", default="default")
    annotate.add_argument("--use-gpu", action="store_true")
    annotate.add_argument(
        "--output-format",
        choices=["auto", "ud-jsonl-v2", "ud-jsonl-v1"],
        default="auto",
        help=(
            "Physical output format. v2 writes compact gzip shards; v1 is "
            "kept for resuming existing single-file partials."
        ),
    )
    annotate.add_argument(
        "--profile",
        choices=["compact", "full"],
        default="compact",
        help="v2 compact stores UPOS+FEATS; full also stores lemma and XPOS.",
    )
    annotate.add_argument("--shard-docs", type=int, default=25)
    annotate.add_argument(
        "--max-document-chars",
        type=int,
        default=250_000,
        help="Deterministically split larger documents at safe boundaries.",
    )
    annotate.add_argument(
        "--on-document-error",
        choices=["quarantine", "fail"],
        default="quarantine",
    )
    annotate.add_argument("--heartbeat-seconds", type=float, default=30.0)
    recovery = annotate.add_mutually_exclusive_group()
    recovery.add_argument(
        "--resume",
        action="store_true",
        help="Resume a compatible .part file without duplicating documents.",
    )
    recovery.add_argument(
        "--force",
        action="store_true",
        help="Discard any partial run and overwrite the completed output.",
    )
    annotate.add_argument(
        "--checkpoint-docs",
        type=int,
        default=10,
        help="Flush and fsync partial output every N documents (default: 10).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    args = build_argparser().parse_args(
        argv if argv is not None else sys.argv[1:]
    )
    if args.command == "download":
        download_models(
            args.langs, model_dir=args.model_dir, package=args.package
        )
        return 0
    if args.command == "smoke":
        samples = {
            "es": "La niña camina bajo el puente.",
            "gl": "A nena camiña baixo a ponte.",
        }
        results = []
        for lang in args.langs:
            tagger = StanzaPosTagger(
                lang,
                model_dir=args.model_dir,
                package=args.package,
                use_gpu=args.use_gpu,
            )
            document = tagger.annotate(
                SourceDocument(f"smoke-{lang}", samples[lang])
            )
            tokens = sum(len(item.tokens) for item in document.sentences)
            if not document.sentences or not tokens:
                raise RuntimeError(f"Stanza smoke test produced no {lang} tags")
            results.append(
                {
                    "lang": lang,
                    "sentences": len(document.sentences),
                    "tokens": tokens,
                    "model_digest": tagger.metadata["model_digest"],
                }
            )
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    if args.limit_docs < 0:
        raise ValueError("--limit-docs must be 0 or greater")
    if args.checkpoint_docs < 1:
        raise ValueError("--checkpoint-docs must be at least 1")
    if args.shard_docs < 1:
        raise ValueError("--shard-docs must be at least 1")
    if args.max_document_chars < 1:
        raise ValueError("--max-document-chars must be at least 1")
    if args.heartbeat_seconds < 0:
        raise ValueError("--heartbeat-seconds must be 0 or greater")
    output_format = args.output_format
    if output_format == "auto":
        legacy_partial = partial_output_path(args.out)
        output_format = (
            "ud-jsonl-v1"
            if args.resume and legacy_partial.is_file()
            else "ud-jsonl-v2"
        )
    command = TagCorpusCommand(
        input_path=args.input,
        output_path=args.out,
        lang=args.lang,
        input_format=args.format,
        text_field=args.text_field,
        id_field=args.id_field,
        limit_docs=args.limit_docs,
        overwrite=args.force,
        resume=args.resume,
        checkpoint_docs=args.checkpoint_docs,
        output_format=output_format,
        profile=args.profile,
        shard_docs=args.shard_docs,
        max_document_chars=args.max_document_chars,
        on_document_error=args.on_document_error,
        heartbeat_seconds=args.heartbeat_seconds,
    )
    tagger = StanzaPosTagger(
        args.lang,
        model_dir=args.model_dir,
        package=args.package,
        use_gpu=args.use_gpu,
    )
    manifest = tag_corpus(command, tagger)
    logger.info(
        "Annotated %d documents, %d sentences and %d tokens to %s",
        manifest["documents"],
        manifest["sentences"],
        manifest["tokens"],
        args.out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
