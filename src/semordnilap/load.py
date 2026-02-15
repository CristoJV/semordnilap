from pathlib import Path

import numpy as np


def load_lexicon(words_filepath: Path) -> object:
    with open(words_filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def load_embeddings(npz_filepath: Path) -> tuple[list[str], list[float]]:
    data = np.load(npz_filepath)
    words = data["words"]
    embeddings = data["embeddings"]
    return words, embeddings
