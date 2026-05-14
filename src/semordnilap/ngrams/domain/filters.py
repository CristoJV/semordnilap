"""N-gram filtering rules."""

from __future__ import annotations

from semordnilap.ngrams.domain.normalize import normalize_ngram
from semordnilap.utils.text import strip_accents


ONE_LETTER_WHITELIST = {
    "en": {"a", "i"},
    "es": {"a", "e", "o", "y"},
    "fr": {"a", "à", "y"},
    "gl": {"a", "e", "o"},
    "pt": {"a", "e", "o"},
}

STOPWORDS = {
    "en": {
        "a",
        "an",
        "and",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "he",
        "her",
        "his",
        "i",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "she",
        "that",
        "the",
        "to",
        "was",
        "we",
        "with",
        "you",
    },
    "es": {
        "a",
        "al",
        "con",
        "de",
        "del",
        "e",
        "el",
        "en",
        "la",
        "las",
        "lo",
        "los",
        "o",
        "por",
        "que",
        "se",
        "su",
        "sus",
        "un",
        "una",
            "y",
    },
    "fr": {
        "à",
        "au",
        "aux",
        "avec",
        "ce",
        "ces",
        "dans",
        "de",
        "des",
        "du",
        "elle",
        "en",
        "et",
        "il",
        "je",
        "la",
        "le",
        "les",
        "mais",
        "ne",
        "nous",
        "ou",
        "par",
        "pas",
        "pour",
        "que",
        "qui",
        "se",
        "sur",
        "un",
        "une",
        "vous",
        "y",
    },
    "gl": {
        "a",
        "ao",
        "as",
        "co",
        "coa",
        "con",
        "da",
        "das",
        "de",
        "do",
        "dos",
        "e",
        "en",
        "na",
        "nas",
        "no",
        "nos",
        "o",
        "os",
        "ou",
        "por",
        "que",
        "se",
        "un",
        "unha",
    },
    "pt": {
        "a",
        "ao",
        "as",
        "com",
        "da",
        "das",
        "de",
        "do",
        "dos",
        "e",
        "em",
        "o",
        "os",
        "ou",
        "por",
        "que",
        "se",
        "um",
        "uma",
    },
}


def is_valid_token(
    token: str,
    *,
    lang: str,
    min_token_len: int,
    max_token_len: int,
) -> bool:
    if len(token) > max_token_len:
        return False
    if len(token) >= min_token_len:
        return True
    return strip_accents(token) in ONE_LETTER_WHITELIST.get(lang, set())


def is_all_stopwords(tokens: tuple[str, ...], lang: str) -> bool:
    stopwords = STOPWORDS.get(lang, set())
    return bool(tokens) and all(
        strip_accents(token) in stopwords for token in tokens
    )


def is_valid_ngram(
    tokens: tuple[str, ...],
    *,
    lang: str,
    min_token_len: int,
    max_token_len: int,
    min_norm_len: int,
    include_all_stopword_ngrams: bool,
    fold_nasal_letters: bool,
) -> bool:
    if not tokens:
        return False
    for token in tokens:
        if not is_valid_token(
            token,
            lang=lang,
            min_token_len=min_token_len,
            max_token_len=max_token_len,
        ):
            return False
    norm_key = normalize_ngram(
        " ".join(tokens), fold_nasal_letters=fold_nasal_letters
    )
    if len(norm_key) < min_norm_len:
        return False
    if not include_all_stopword_ngrams and is_all_stopwords(tokens, lang):
        return False
    return True
