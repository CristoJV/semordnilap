import logging
import subprocess

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def freeling_pos_to_human(pos: str) -> str | None:

    if pos.startswith("I"):
        return "interjección"

    if pos.startswith(("NC", "NP")):
        return "sustantivo"

    if pos.startswith("AQ"):
        return "adjetivo"

    if pos.startswith(("RG", "RN")):
        return "adverbio"

    if pos.startswith("SP"):
        return "preposición"

    if pos.startswith(("CC", "CS")):
        return "conjunción"

    if pos.startswith("D"):
        return "determinante"

    if pos.startswith("P"):
        return "pronombre"

    if pos.startswith("Z"):
        return "numeral"

    if pos.startswith("VM"):
        if pos.startswith("VMN"):
            return "verbo"
        return "forma"

    return None


class FreelingAnalyzer:
    def __init__(self, config="/usr/local/share/freeling/config/es.cfg"):
        self.config = config

    def analyze(self, text: list[str]) -> list[tuple[str, str, float]]:
        input_text = "\n".join(text)
        logger.info(f"Processing ({len(text)} lines)")

        p = subprocess.run(
            [
                "analyze",
                "-f",
                "/usr/local/share/freeling/config/es.cfg",
                "--nortk",
            ],
            input=input_text,
            text=True,
            capture_output=True,
        )

        if p.returncode != 0:
            raise RuntimeError(f"Freeling error: \n{p.stderr}")

        return self._parse_output(p.stdout)

    def _parse_output(self, text: str):
        results = {}

        logger.info(f"Parsing output")
        for line in text.splitlines():
            parts = line.split()

            if len(parts) >= 3:
                token = parts[0]
                lemma = parts[1]
                pos = parts[2]
                conf = float(parts[3]) if len(parts) > 3 else None

                results[token] = {"pos": pos, "lemma": lemma, "conf": conf}

        return results
