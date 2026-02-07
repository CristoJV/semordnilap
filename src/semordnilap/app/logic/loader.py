import json
from pathlib import Path


def load_semordnilaps(semordnilaps_filepath: str):
    json_file = Path(semordnilaps_filepath)
    if not json_file.exists():
        raise FileNotFoundError(
            f"Semordnilaps file not found at: {semordnilaps_filepath}"
        )
    with json_file.open("r", encoding="utf-8") as f:
        json_data = json.load(f)

    json_data = {
        word: {
            int(word_count): set(phrases)
            for word_count, phrases in by_count.items()
        }
        for word, by_count in json_data.items()
    }

    return json_data


def load_words_filter(words_filter_filepath: str):
    words_filter_file = Path(words_filter_filepath)
    if not words_filter_file.exists():
        raise FileNotFoundError(
            f"Words filters file not found at: {words_filter_file}"
        )
    words: set[str] = set()
    with words_filter_file.open("r", encoding="utf-8") as f:
        for line in f:
            word = line.strip()
            if word:
                words.add(word)
    return words
