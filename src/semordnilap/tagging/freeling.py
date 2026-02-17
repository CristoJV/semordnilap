import logging
import subprocess

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = log


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
