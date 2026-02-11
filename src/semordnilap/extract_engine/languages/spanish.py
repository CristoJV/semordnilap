import re

from semordnilap.extract_engine.base import BaseLanguageEngine

DEFAULT_DESIRED_CATEGORIES = {
    "adjetivo",
    "adverbio",
    "sustantivo",
    "verbo",
    "locución",
    "interjección",
    "preposición",
    "conjunción",
    "pronombre",
    "determinante",
    "numeral",
    "onomatopeya",
    "forma",
}


WORD_RE = re.compile(r"^[a-záéíóúüñ]+$", re.IGNORECASE)
POS_HEADER_RE = re.compile(
    r"^(?P<eq>={3,5})\s*(?P<body>.*?)\s*(?P=eq)\s*$", re.M
)
SPANISH_SECTION_RE = re.compile(r"^==\s*\{\{lengua\|es\}\}\s*==\s*$", re.M)
HEADER_TEMPLATE_RE = re.compile(r"\{\{\s*([^|}\n]+)\s*(\|[^}]*)?\}\}")


def normalize_label(text: str) -> str:
    """Normalize template or heading names."""
    whitespace_re = re.compile(r"\s+")
    return whitespace_re.sub(" ", (text or "").strip().lower())


def get_base_category(label: str) -> str:
    """
    Convert extended categories to base POS

    Examples:
        "forma verbo" -> "forma"
        "sustantivo masculino" -> "sustantivo"
        "adjetivo demostrativo" -> "adjetivo"
    """
    label = normalize_label(label)
    return label.split(" ", 1)[0] if label else ""


def is_clean_word(word: str) -> bool:
    if not word:
        return False
    if " " in word:
        return False
    return WORD_RE.fullmatch(word) is not None


class SpanishEngine(BaseLanguageEngine):
    def extract_section(
        self,
        text: str,
    ) -> str | None:
        """
        Extract only the Spanish section from a Wiktionary entry.

        Everything outside == {{lengua|es}} == is ignored.
        """
        next_lang_header_re = re.compile(r"^==[^=].*==\s*$", re.M)

        if not text:
            return None

        m = SPANISH_SECTION_RE.search(text or "")
        if not m:
            return None

        start = m.end()
        rest = text[start:]
        m2 = next_lang_header_re.search(rest)

        end = start + (m2.start() if m2 else len(rest))
        return text[start:end]

    def extract_pos(self, section: str) -> set[str]:
        """
        Extract grammatical base categories from Spanish headings.

        Examples detected:
            === Sustantivo ===
            ==== {{forma verbal}} ====
            ==== {{adjetivo demostrativo}} ====

        Ignored:
            Traducciones, Véase, Etimología, Información, etc.
        """
        categories: set[str] = set()
        SPANISH_POS_RE = re.compile(
            r"^(={3,5})\s*(?:\{\{\s*([^}|]+).*?\}\}|([^=\n]+))\s*\1\s*$",
            re.M,
        )
        for m in SPANISH_POS_RE.finditer(section):
            template_label = m.group(2)
            text_label = m.group(3)

            label = template_label or text_label
            base_category = get_base_category(label)

            if base_category in DEFAULT_DESIRED_CATEGORIES:
                categories.add(base_category)

        return categories
