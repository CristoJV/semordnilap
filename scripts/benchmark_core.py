"""Repeatable local throughput/RSS benchmark for the streaming core.

Run with, for example:
    uv run python scripts/benchmark_core.py --windows 10000 1000000
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import resource
from time import perf_counter

from semordnilap.ngrams.domain import (
    NgramExtractionPolicy,
    iter_ngrams_from_text,
)
from semordnilap.tagging.domain import (
    AnnotatedDocument,
    AnnotatedSentence,
    AnnotatedToken,
    AnnotatedWord,
)


def benchmark(target: int, *, oversized: bool = False) -> dict:
    sentence = "La niña camina. Antes, el camino continúa bajo el puente. "
    repeats = max(1, target // 20)
    text = sentence * repeats
    if oversized:
        text += " palabra" * 250_000
    policy = NgramExtractionPolicy(lang="es", max_n=3)
    started = perf_counter()
    generated = 0
    for _ in iter_ngrams_from_text(text, policy):
        generated += 1
        if not oversized and generated >= target:
            break
    elapsed = perf_counter() - started
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "requested_windows": target,
        "generated_windows": generated,
        "input_chars": len(text),
        "elapsed_seconds": round(elapsed, 6),
        "windows_per_second": round(generated / elapsed, 2),
        "peak_rss_platform_units": peak_rss,
        "oversized_document": oversized,
    }


def encoding_benchmark() -> dict:
    text = "La niña camina. Antes, el camino continúa. " * 1_000
    tokens = []
    for index, match in enumerate(re.finditer(r"\w+|[^\w\s]", text), 1):
        surface = match.group()
        upos = "PUNCT" if not surface.isalnum() else "X"
        tokens.append(
            AnnotatedToken(
                id=(index,),
                text=surface,
                start_char=match.start(),
                end_char=match.end(),
                words=(AnnotatedWord(index, surface, upos),),
            )
        )
    document = AnnotatedDocument(
        doc_id="encoding-benchmark",
        lang="es",
        text=text,
        sentences=(AnnotatedSentence(0, 0, len(text), tuple(tokens)),),
    )
    v1 = json.dumps(document.to_dict(), ensure_ascii=False).encode()
    v2 = json.dumps(
        document.to_dict(schema_version=2, profile="compact"),
        ensure_ascii=False,
    ).encode()
    compressed = gzip.compress(v2, mtime=0)
    return {
        "encoding": "tagged-v2-compact-gzip",
        "input_utf8_bytes": len(text.encode()),
        "v1_json_bytes": len(v1),
        "v2_json_bytes": len(v2),
        "v2_gzip_bytes": len(compressed),
        "v2_gzip_to_input_ratio": round(
            len(compressed) / len(text.encode()), 4
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--windows", type=int, nargs="+", default=[10_000, 1_000_000]
    )
    parser.add_argument("--oversized-document", action="store_true")
    args = parser.parse_args()
    reports = [benchmark(value) for value in args.windows]
    if args.oversized_document:
        reports.append(benchmark(max(args.windows), oversized=True))
    reports.append(encoding_benchmark())
    print(json.dumps(reports, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
