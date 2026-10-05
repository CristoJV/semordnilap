"""Provider-neutral domain model for contextual UD annotations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

SCHEMA_NAME = "semordnilap.ud-jsonl"
SCHEMA_VERSION = 1
CURRENT_SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2})
UPOS_TAGS = frozenset(
    {
        "ADJ",
        "ADP",
        "ADV",
        "AUX",
        "CCONJ",
        "DET",
        "INTJ",
        "NOUN",
        "NUM",
        "PART",
        "PRON",
        "PROPN",
        "PUNCT",
        "SCONJ",
        "SYM",
        "VERB",
        "X",
    }
)


def _require_upos(value: str) -> str:
    tag = value.upper()
    if tag not in UPOS_TAGS:
        raise ValueError(f"Invalid UPOS tag: {value!r}")
    return tag


@dataclass(frozen=True)
class SourceDocument:
    doc_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnnotatedWord:
    id: int
    text: str
    upos: str
    lemma: str | None = None
    xpos: str | None = None
    feats: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "upos", _require_upos(self.upos))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "lemma": self.lemma,
            "upos": self.upos,
            "xpos": self.xpos,
            "feats": {key: list(values) for key, values in self.feats},
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AnnotatedWord:
        raw_feats = value.get("feats") or {}
        return cls(
            id=int(value["id"]),
            text=str(value["text"]),
            lemma=value.get("lemma"),
            upos=str(value["upos"]),
            xpos=value.get("xpos"),
            feats=tuple(
                (str(key), tuple(str(item) for item in values))
                for key, values in sorted(raw_feats.items())
            ),
        )


@dataclass(frozen=True)
class AnnotatedToken:
    id: tuple[int, ...]
    text: str
    start_char: int
    end_char: int
    words: tuple[AnnotatedWord, ...]
    spaces_before: str = ""
    spaces_after: str = ""

    def __post_init__(self) -> None:
        if not self.id or any(
            not isinstance(value, int) or value < 1 for value in self.id
        ):
            raise ValueError("Token IDs must be positive integers")
        if tuple(sorted(self.id)) != self.id or len(set(self.id)) != len(
            self.id
        ):
            raise ValueError("Token IDs must be ordered and unique")
        if self.start_char < 0 or self.end_char < self.start_char:
            raise ValueError("Invalid token character offsets")
        if not self.words:
            raise ValueError(
                "An annotated token must contain at least one word"
            )

    @property
    def upos_slot(self) -> str:
        return "+".join(word.upos for word in self.words)

    @property
    def is_punctuation(self) -> bool:
        return all(word.upos == "PUNCT" for word in self.words)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": list(self.id),
            "text": self.text,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "spaces_before": self.spaces_before,
            "spaces_after": self.spaces_after,
            "words": [word.to_dict() for word in self.words],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AnnotatedToken:
        raw_id = value["id"]
        token_id = (
            (int(raw_id),)
            if isinstance(raw_id, int)
            else tuple(int(item) for item in raw_id)
        )
        return cls(
            id=token_id,
            text=str(value["text"]),
            start_char=int(value["start_char"]),
            end_char=int(value["end_char"]),
            spaces_before=str(value.get("spaces_before") or ""),
            spaces_after=str(value.get("spaces_after") or ""),
            words=tuple(
                AnnotatedWord.from_dict(word) for word in value["words"]
            ),
        )


@dataclass(frozen=True)
class AnnotatedSentence:
    index: int
    start_char: int
    end_char: int
    tokens: tuple[AnnotatedToken, ...]

    def __post_init__(self) -> None:
        if self.start_char < 0 or self.end_char < self.start_char:
            raise ValueError("Invalid sentence character offsets")

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "tokens": [token.to_dict() for token in self.tokens],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AnnotatedSentence:
        return cls(
            index=int(value["index"]),
            start_char=int(value["start_char"]),
            end_char=int(value["end_char"]),
            tokens=tuple(
                AnnotatedToken.from_dict(token) for token in value["tokens"]
            ),
        )


@dataclass(frozen=True)
class AnnotatedDocument:
    doc_id: str
    lang: str
    text: str
    sentences: tuple[AnnotatedSentence, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        indexes = [sentence.index for sentence in self.sentences]
        if indexes != list(range(len(indexes))):
            raise ValueError("Sentence indexes must be ordered and contiguous")
        previous_end = 0
        for sentence in self.sentences:
            if sentence.start_char < previous_end:
                raise ValueError("Sentence offsets must be ordered")
            if sentence.end_char > len(self.text):
                raise ValueError("Sentence offset exceeds document text")
            previous_end = sentence.end_char
            previous_token_end = sentence.start_char
            for token in sentence.tokens:
                if token.start_char < previous_token_end:
                    raise ValueError("Token offsets must be ordered")
                if token.end_char > sentence.end_char:
                    raise ValueError("Token ends after its sentence")
                if self.text[token.start_char : token.end_char] != token.text:
                    raise ValueError("Token text does not match document span")
                previous_token_end = token.end_char

    def to_dict(
        self,
        *,
        schema_version: int = SCHEMA_VERSION,
        profile: str = "full",
        ordinal: int | None = None,
    ) -> dict[str, Any]:
        if schema_version == 2:
            return self._to_v2_dict(profile=profile, ordinal=ordinal)
        if schema_version != 1:
            raise ValueError(
                f"Unsupported annotation schema version: {schema_version}"
            )
        return {
            "schema": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "lang": self.lang,
            "doc_id": self.doc_id,
            "text": self.text,
            "metadata": self.metadata,
            "sentences": [sentence.to_dict() for sentence in self.sentences],
        }

    def _to_v2_dict(
        self, *, profile: str, ordinal: int | None
    ) -> dict[str, Any]:
        if profile not in {"compact", "full"}:
            raise ValueError(f"Unsupported annotation profile: {profile}")
        sentences = []
        for sentence in self.sentences:
            tokens = []
            for token in sentence.tokens:
                words = []
                for word in token.words:
                    encoded = {
                        "i": word.id,
                        "t": word.text,
                        "u": word.upos,
                    }
                    if word.feats:
                        encoded["f"] = {
                            key: list(values) for key, values in word.feats
                        }
                    if profile == "full":
                        if word.lemma is not None:
                            encoded["l"] = word.lemma
                        if word.xpos is not None:
                            encoded["x"] = word.xpos
                    words.append(encoded)
                tokens.append(
                    {
                        "i": list(token.id),
                        "s": token.start_char,
                        "e": token.end_char,
                        "w": words,
                    }
                )
            sentences.append(
                {
                    "i": sentence.index,
                    "s": sentence.start_char,
                    "e": sentence.end_char,
                    "t": tokens,
                }
            )
        value: dict[str, Any] = {
            "schema": SCHEMA_NAME,
            "schema_version": 2,
            "profile": profile,
            "lang": self.lang,
            "doc_id": self.doc_id,
            "text": self.text,
            "metadata": self.metadata,
            "sentences": sentences,
        }
        if ordinal is not None:
            value["ordinal"] = ordinal
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AnnotatedDocument:
        if value.get("schema") != SCHEMA_NAME:
            raise ValueError(
                f"Unsupported annotation schema: {value.get('schema')}"
            )
        version = value.get("schema_version")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                "Unsupported annotation schema version: "
                f"{version}"
            )
        if version == 2:
            return cls._from_v2_dict(value)
        return cls(
            doc_id=str(value["doc_id"]),
            lang=str(value["lang"]).lower(),
            text=str(value["text"]),
            metadata=dict(value.get("metadata") or {}),
            sentences=tuple(
                AnnotatedSentence.from_dict(sentence)
                for sentence in value["sentences"]
            ),
        )

    @classmethod
    def _from_v2_dict(cls, value: dict[str, Any]) -> AnnotatedDocument:
        text = str(value["text"])
        sentences = []
        for raw_sentence in value["sentences"]:
            tokens = []
            for raw_token in raw_sentence["t"]:
                start = int(raw_token["s"])
                end = int(raw_token["e"])
                token_text = text[start:end]
                words = []
                for raw_word in raw_token["w"]:
                    raw_feats = raw_word.get("f") or {}
                    words.append(
                        AnnotatedWord(
                            id=int(raw_word["i"]),
                            text=str(raw_word["t"]),
                            upos=str(raw_word["u"]),
                            lemma=raw_word.get("l"),
                            xpos=raw_word.get("x"),
                            feats=tuple(
                                (
                                    str(key),
                                    tuple(str(item) for item in values),
                                )
                                for key, values in sorted(raw_feats.items())
                            ),
                        )
                    )
                tokens.append(
                    AnnotatedToken(
                        id=tuple(int(item) for item in raw_token["i"]),
                        text=token_text,
                        start_char=start,
                        end_char=end,
                        words=tuple(words),
                    )
                )
            sentences.append(
                AnnotatedSentence(
                    index=int(raw_sentence["i"]),
                    start_char=int(raw_sentence["s"]),
                    end_char=int(raw_sentence["e"]),
                    tokens=tuple(tokens),
                )
            )
        return cls(
            doc_id=str(value["doc_id"]),
            lang=str(value["lang"]).lower(),
            text=text,
            metadata=dict(value.get("metadata") or {}),
            sentences=tuple(sentences),
        )


class PosTagger(Protocol):
    @property
    def metadata(self) -> dict[str, Any]:
        raise NotImplementedError

    def annotate(self, source: SourceDocument) -> AnnotatedDocument:
        raise NotImplementedError
