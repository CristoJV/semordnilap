from abc import ABC


class BaseLanguageEngine(ABC):
    def __init__(self, dump_path: str):
        self.dump_path = dump_path

    def extract_section(self, text: str):
        raise NotImplementedError

    def extract_pos(self, section: str):
        raise NotImplementedError

    def expand(self, lemma: str, section: str):
        return []

    def process_page(self, title: str, text: str):

        section = self.extract_section(text)
        if not section:
            return None, []

        pos = self.extract_pos(section)
        if not pos:
            return None, []

        lemma = title.strip().lower()

        expansions = self.expand(lemma, section)
        return (lemma, pos), expansions
