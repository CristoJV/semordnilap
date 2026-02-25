import argparse
import json
import logging
from collections import defaultdict
from itertools import product
from pathlib import Path

from tqdm import tqdm

from semordnilap.candidates.filtering.rules import (
    apply_filters,
    reject_dotted,
    reject_hyphenated,
    reject_non_alphanumeric,
)
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


def build_tag_index_from_word_subset(lexicon, allowed_words):
    index = defaultdict(set)

    for form in tqdm(
        allowed_words,
        total=len(lexicon),
        desc="Building tag index from lexicon",
    ):
        analyses = lexicon.get(form, [])
        for entry in analyses:
            tag = entry.get("tag")
            if not tag:
                continue
            index[tag].add(form)
    return index


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


def export_candidates(out_filepath: str, candidates: list[str]):
    with open(out_filepath, "w", encoding="utf-8") as f:
        for candidate in candidates:
            f.write(f"{candidate}\n")


def build_parser():
    parser = argparse.ArgumentParser("Pattern generator (tag-based)")
    parser.add_argument("-l", "--lexicon", help="Lexicon JSON filepath")
    parser.add_argument("-o", "--out", help="Output filepath")
    parser.add_argument(
        "--lang",
        required=True,
        help="Language (es, gl, spa, galician...)",
    )
    parser.add_argument(
        "-p",
        "--pattern",
        required=False,
        help="Comma separated tag patterns (e.g. DAXXX, NCSXX)",
    )
    parser.add_argument(
        "--words-only",
        action="store_true",
        help="Return only the filtered word list (skip pattern expansion)",
    )
    parser.add_argument(
        "--filter",
        action="store_true",
        help="Apply form filters to the lexicon before canditate generation",
    )
    return parser


def parse_patterns(pattern_arg: str | None, tag_index):
    if not pattern_arg:
        logger.info("No pattern provided → using full tagset")
        return [list(tag_index.keys())]

    raw_patterns = [p.strip() for p in pattern_arg.split(",") if p.strip()]

    logger.info("Patterns: %s", raw_patterns)

    return raw_patterns


def build_output_path(base_path: str | Path, new_suffix: str) -> Path:
    base = Path(base_path)
    return base.with_suffix(new_suffix)


def export_filtering_artifacts(
    out_path: Path, removed: dict, total_lexicon: int
):
    if not removed:
        return
    removed_path = build_output_path(out_path, ".removed.json")

    with open(removed_path, "w", encoding="utf-8") as f:
        json.dump(removed, f, indent=2, ensure_ascii=False)

    removed_set = set()

    for values in removed.values():
        removed_set |= set(values)

    auto_filter_path = build_output_path(out_path, ".automatic.filter")

    with open(auto_filter_path, "w", encoding="utf-8") as f:
        for word in sorted(removed_set):
            f.write(f"{word}\n")


def main():
    args = build_parser().parse_args()

    global POS_FEATURE_SLOTS
    POS_FEATURE_SLOTS = get_pos_feature_slots(args.lang)

    global AGREEMENT_RULES
    AGREEMENT_RULES = get_agreement_rules(args.lang)

    lexicon = load_lexicon(args.lexicon)

    if args.filter:
        logger.info("Applying from filters")

        valid_words, removed = apply_filters(
            lexicon,
            form_rules=[
                reject_hyphenated,
                reject_dotted,
                reject_non_alphanumeric,
            ],
        )
        logger.info(
            "Valid words: %d/%d - Removed: %d",
            len(valid_words),
            len(lexicon),
            len(lexicon) - len(valid_words),
        )
        export_filtering_artifacts(
            args.out, removed, total_lexicon=len(lexicon)
        )
    else:
        valid_words = list(lexicon.keys())
        removed = {}

    # ---------------------------------------------------------
    # Words-only shortcut
    # ---------------------------------------------------------
    if args.words_only:
        logger.info("words-only mode. Skipping tag/pattern generation")

        export_candidates(args.out, valid_words)

        logger.info(
            "Exported %d words to %s",
            len(valid_words),
            args.out,
        )
        return
    # ---------------------------------------------------------
    # Tag index
    # ---------------------------------------------------------
    tag_index = build_tag_index_from_word_subset(lexicon, valid_words)

    # ---------------------------------------------------------
    # Pattern handling
    # ---------------------------------------------------------

    if args.pattern:
        raw_patterns = parse_patterns(args.pattern, tag_index)
        logger.info("Using patterns: %s", raw_patterns)
        expanded_lists = [
            expand_pattern_from_lexicon(tag_index, p) for p in raw_patterns
        ]
        expanded = [list(combo) for combo in product(*expanded_lists)]
    else:
        logger.info("No pattern. Using all words directly")
        expanded = [[tag] for tag in tag_index.keys()]

    candidates = []
    agreeable = filter_agreable_patterns(expanded)
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
