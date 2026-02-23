import bz2
import re
import xml.etree.ElementTree as ET

from semordnilap.extract.base import BaseLanguageEngine


def iter_gl_conj_templates(dump_path: str):
    with bz2.open(dump_path, "rb") as f:
        for _, elem in ET.iterparse(f, events=("end",)):
            if not elem.tag.endswith("page"):
                continue

            ns = elem.findtext(".//{*}ns")
            if ns != "10":
                elem.clear()
                continue

            title = elem.findtext(".//{*}title") or ""
            if not title.startswith("Modelo:conx.gl"):
                elem.clear()
                continue

            text = elem.findtext(".//{*}text") or ""
            yield title, text
            elem.clear()


def classify_conj_template(text: str) -> str:
    """
    Classify Galician conjugation templates.
    pattern  -> parametric (uses {{{1}}})
    lexical  -> closed list (no parameters)
    """
    param_re = re.compile(r"\{\{\{\s*(\d+)")
    params = {int(m.group(1)) for m in param_re.finditer(text or "")}

    if not params:
        return "lexical"

    return f"pattern_{params}"


def extract_pattern_rules(template_text: str):
    rule_re = re.compile(r"\{\{gl\|\{\{\{(\d+)\}\}\}([^\}]+)\}\}")
    rules = []
    for m in rule_re.finditer(template_text or ""):
        param_index = int(m.group(1))
        ending = m.group(2).strip()

        if ending:
            rules.append((param_index, ending))

    return rules


def extract_irregular_forms(template_text: str) -> set[str]:
    form_re = re.compile(r"\{\{gl\|([^\}\|]+)\}\}")
    return {
        m.group(1)
        for m in form_re.finditer(template_text)
        if m.group(1).isalpha()
    }


def build_expansion_templates(dump_path: str) -> dict:
    conj = {}

    for title, text in iter_gl_conj_templates(dump_path):
        name = title.replace("Modelo:", "")
        kind = classify_conj_template(text)

        if kind == "lexical":
            conj[name] = {
                "type": "lexical",
                "forms": sorted(extract_irregular_forms(text)),
            }
        else:
            conj[name] = {"type": kind, "rules": extract_pattern_rules(text)}

    return conj


def expand_pattern(stems, rules):
    forms = set()

    for param_index, ending in rules:
        if param_index > len(stems):
            continue

        stem = stems[param_index - 1]
        forms.add(stem + ending)

    return forms


GL_SECTION_RE = re.compile(r"\{\{-(gl|glref)-\}\}", re.I)
SON_RE = re.compile(r"\{\{son\|\|\|gl\}\}", re.I)
GL_PO_RE = re.compile(
    r"\{\{-(?P<root>verbo|subst|adx|adv|prep|conx|interx|pron|num)(?P<feat>[a-z]*)-(?:\|gl)?\}\}",
    re.I,
)
CONJ_CALL_RE = re.compile(
    r"\{\{\s*(conx\.gl[^\|\}]+)\|([^}]*)\}\}",
    re.I,
)


class GalicianEngine(BaseLanguageEngine):
    def __init__(self, dump_path: str):
        super().__init__(dump_path)
        self.templates = build_expansion_templates(dump_path)

    def extract_section(self, text: str) -> str:
        if not text:
            return None
        m = GL_SECTION_RE.search(text)
        if not m:
            return None
        start = m.end()
        return text[start:]

    def extract_pos(self, section: str) -> set[str]:
        gl_pos_map = {
            "subst": "sustantivo",
            "verbo": "verbo",
            "adx": "adjetivo",
            "adv": "adverbio",
            "prep": "preposición",
            "conx": "conjunción",
            "interx": "interjección",
            "pron": "pronombre",
            "num": "numeral",
        }
        if not section:
            return set()
        m = SON_RE.search(section)
        if not m:
            return set()
        rest = section[m.end() :]

        m2 = GL_PO_RE.search(rest)
        if not m2:
            return set()
        key = m2.group("root").lower()

        if key in gl_pos_map:
            return {gl_pos_map[key]}

        return set()

    def expand(
        self,
        lemma: str,
        section: str,
    ) -> list[str]:

        if "verbo" not in self.extract_pos(section):
            return []
        forms = set()

        m = CONJ_CALL_RE.search(section)
        if not m:
            return []

        tmpl = m.group(1)
        raw_params = m.group(2)

        if tmpl not in self.templates:
            return []
        stems = [p.strip() for p in raw_params.split("|") if p.strip()]
        info = self.templates[tmpl]

        if info["type"] == "lexical":
            forms.update(info["formas"])
        else:
            # pattern
            if not stems:
                # fallback: infer stem from lemma
                stems = (
                    lemma[:-2] if lemma.endswith(("ar", "er", "ir")) else lemma
                )

            forms = expand_pattern(stems, info["rules"])

        return [(f, "forma_verbal") for f in forms]
