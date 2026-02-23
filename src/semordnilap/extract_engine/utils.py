import json
from typing import Iterable


def export_json(path: str, lexicon: Iterable[str]) -> int:
    ordered = {}
    for k in sorted(lexicon):
        values = lexicon[k]

        if isinstance(values, set):
            ordered[k] = sorted(values)

        elif isinstance(values, list):
            ordered[k] = values

        else:
            ordered[k] = values

    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            ordered,
            f,
            ensure_ascii=False,
            indent=2,
        )
    return len(ordered)
