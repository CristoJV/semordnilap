import json

from semordnilap.tagging.freeling import FreelingAnalyzer


def enrich_json(input_path: str, output_path: str):
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    words = list(data.keys())

    analyzer = FreelingAnalyzer()
    freeling_results = analyzer.analyze(words)

    enriched = {}
    for word, original_pos in data.items():
        estimated = freeling_results.get(word, None)
        enriched[word] = {
            "original": {"pos": original_pos},
            "estimated": estimated
            or {"pos": None, "lemma": None, "conf": None},
        }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
