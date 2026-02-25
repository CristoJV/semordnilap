import argparse
import json
import logging
from collections import defaultdict
from itertools import product
from pathlib import Path

from tqdm import tqdm

from semordnilap.lang.agreements import get_agreement_rules
from semordnilap.lang.tagset import get_pos_feature_slots

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


def load_lexicon(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def expand_pattern_from_lexicon(tag_index, pattern: str):

    matches = []

    for tag in tag_index.keys():
        if len(tag) != len(pattern):
            continue

        valid = True

        for t_char, p_char in zip(tag, pattern):
            if p_char == "X":
                continue

            if t_char != p_char:
                valid = False
                break

        if valid:
            matches.append(tag)

    if not matches:
        logger.warning("Pattern produced no real tags: %s", pattern)

    return matches


def get_feature_value(tag: str, feature: str):

    if not tag:
        return None

    pos = tag[0]

    pos_spec = POS_FEATURE_SLOTS.get(pos)
    if not pos_spec:
        return None

    feat_spec = pos_spec.features.get(feature)
    if not feat_spec:
        return None

    slot = feat_spec.slot

    if len(tag) <= slot:
        return None

    value = tag[slot]

    if value == "0":
        return None

    return value


def tags_agree_by_rule(t1: str, t2: str, rule) -> bool:
    if t1[0] not in rule["pos"] or t2[0] not in rule["pos"]:
        return True

    for feature, compat_fn in rule["features"].items():
        v1 = get_feature_value(t1, feature)
        v2 = get_feature_value(t2, feature)

        if v1 is None or v2 is None:
            continue

        if not compat_fn(v1, v2):
            return False
    return True


def filter_agreable_patterns(patterns: list[list[str]]):
    """
    Filter unagreable patterns based on estricty rules:
    For example, consecutive D and N and A should match gender and number
    """
    filtered = []

    for pattern in patterns:
        agree_ok = True

        for i in range(len(pattern) - 1):
            for rule in AGREEMENT_RULES:
                if not tags_agree_by_rule(pattern[i], pattern[i + 1], rule):
                    agree_ok = False
                    break
            if not agree_ok:
                break

        if agree_ok:
            filtered.append(pattern)

    return filtered


def parse_tag(tag: str) -> dict:

    if not tag:
        return {}

    pos = tag[0]
    feats = {"pos": pos}

    pos_spec = POS_FEATURE_SLOTS.get(pos)
    if not pos_spec:
        return feats

    for feat_name, feat_spec in pos_spec.features.items():
        slot = feat_spec.slot

        if len(tag) > slot:
            value = tag[slot]

            if value != "0":
                feats[feat_name] = value

    return feats


def build_tag_index(lexicon):
    index = defaultdict(set)

    for form, analyses in tqdm(
        lexicon.items(),
        total=len(lexicon),
        desc="Building tag index from lexicon",
    ):
        for entry in analyses:
            tag = entry.get("tag")
            if not tag:
                continue
            index[tag].add(form)
    return index


def generate_candidates(tag_index, pattern):
    buckets = []
    for tag in pattern:
        words = tag_index.get(tag, set())

        if not words:
            logger.warning("No forms for TAG=%s", tag)
            return []
        buckets.append(sorted(words))

    raw_candidates = list(product(*buckets))
    return [" ".join(candidate) for candidate in raw_candidates]


def build_parser():
    parser = argparse.ArgumentParser("Pattern generator (tag-based)")
    parser.add_argument("-l", "--lexicon", help="Lexicon JSON filepath")
    parser.add_argument("-o", "--out", help="Output filepath")
    parser.add_argument("-p", "--pattern", nargs="+", help="Tag pattern")
    parser.add_argument(
        "--lang",
        required=True,
        help="Language (es, gl, spa, galician...)",
    )
    return parser


def export_candidates(out_filepath: str, candidates: list[str]):
    with open(out_filepath, "w", encoding="utf-8") as f:
        for candidate in candidates:
            f.write(f"{candidate}\n")


def main():
    args = build_parser().parse_args()

    global POS_FEATURE_SLOTS
    POS_FEATURE_SLOTS = get_pos_feature_slots(args.lang)

    global AGREEMENT_RULES
    AGREEMENT_RULES = get_agreement_rules(args.lang)

    lexicon = load_lexicon(args.lexicon)
    tag_index = build_tag_index(lexicon)

    expanded_lists = [
        expand_pattern_from_lexicon(tag_index, p) for p in args.pattern
    ]
    expanded = [list(combo) for combo in product(*expanded_lists)]
    print(expanded)
    agreeable = filter_agreable_patterns(expanded)
    print(agreeable)
    candidates = []
    for pat in agreeable:
        candidates.extend(generate_candidates(tag_index, pat))
    candidates_filepath = Path(args.out)
    candidates_filepath.parent.mkdir(parents=True, exist_ok=True)
    export_candidates(candidates_filepath, candidates)
    logger.info(
        "Generated %d candidates. Saved them in %s",
        len(candidates),
        candidates_filepath,
    )


if __name__ == "__main__":
    main()
