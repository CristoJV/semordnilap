from pathlib import Path


def append_word_if_missing(
    filepath: str | Path,
    word: str,
    current_words: set[str],
):
    """
    Añade `word` al archivo si no existe ya.
    """
    if word in current_words:
        return

    filepath = Path(filepath)

    with filepath.open("a", encoding="utf-8") as f:
        f.write(word + "\n")

    current_words.add(word)
