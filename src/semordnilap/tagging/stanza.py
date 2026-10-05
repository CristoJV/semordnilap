"""Stanza adapter for the provider-neutral tagging domain."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path
from typing import Any

from semordnilap.utils.artifacts import sha256_file, stable_id

from semordnilap.tagging.domain import (
    AnnotatedDocument,
    AnnotatedSentence,
    AnnotatedToken,
    AnnotatedWord,
    SourceDocument,
)

SUPPORTED_LANGS = frozenset({"es", "gl"})
PROCESSORS = "tokenize,mwt,pos,lemma"


def _feature_items(raw: str | None):
    if not raw:
        return ()
    values: dict[str, tuple[str, ...]] = {}
    for item in raw.split("|"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        values[key] = tuple(part for part in value.split(",") if part)
    return tuple(sorted(values.items()))


def _token_id(raw: Any) -> tuple[int, ...]:
    if isinstance(raw, int):
        return (raw,)
    return tuple(int(value) for value in raw)


class StanzaPosTagger:
    def __init__(
        self,
        lang: str,
        *,
        model_dir: Path | None = None,
        package: str = "default",
        use_gpu: bool = False,
        pipeline=None,
    ) -> None:
        lang = lang.lower()
        if lang not in SUPPORTED_LANGS:
            supported = ", ".join(sorted(SUPPORTED_LANGS))
            raise ValueError(
                f"Unsupported tagging language {lang!r}: {supported}"
            )
        self.lang = lang
        self.model_dir = model_dir
        self.package = package
        self.use_gpu = use_gpu
        self._pipeline = pipeline
        self._model_digest: str | None = None

    def _get_model_digest(self) -> str:
        if self._model_digest is not None:
            return self._model_digest
        root = self.model_dir or (Path.home() / "stanza_resources")
        candidates = []
        language_root = root / self.lang
        if language_root.exists():
            candidates.extend(
                path for path in language_root.rglob("*") if path.is_file()
            )
        resources = root / "resources.json"
        if resources.is_file():
            candidates.append(resources)
        if not candidates:
            raise FileNotFoundError(
                f"No Stanza model files found for {self.lang!r} in {root}"
            )
        files = [
            {
                "path": str(path.relative_to(root)),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sorted(candidates)
        ]
        self._model_digest = stable_id("stanza-model", files)
        return self._model_digest

    def _get_pipeline(self):
        if self._pipeline is None:
            import stanza

            options = {
                "lang": self.lang,
                "package": self.package,
                "processors": PROCESSORS,
                "use_gpu": self.use_gpu,
                "download_method": None,
            }
            if self.model_dir is not None:
                options["dir"] = str(self.model_dir)
            self._pipeline = stanza.Pipeline(**options)
        return self._pipeline

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "adapter": "stanza",
            "provider": "stanza",
            "provider_version": version("stanza"),
            "lang": self.lang,
            "package": self.package,
            "processors": PROCESSORS.split(","),
            "model_dir": str(self.model_dir) if self.model_dir else None,
            "use_gpu": self.use_gpu,
            "tagset": "UPOS",
            "model_digest": self._get_model_digest(),
        }

    def annotate(self, source: SourceDocument) -> AnnotatedDocument:
        parsed = self._get_pipeline()(source.text)
        sentences = []
        for sentence_index, sentence in enumerate(parsed.sentences):
            tokens = tuple(
                self._convert_token(token) for token in sentence.tokens
            )
            if tokens:
                start_char = tokens[0].start_char
                end_char = tokens[-1].end_char
            else:
                start_char = end_char = 0
            sentences.append(
                AnnotatedSentence(
                    index=sentence_index,
                    start_char=start_char,
                    end_char=end_char,
                    tokens=tokens,
                )
            )
        return AnnotatedDocument(
            doc_id=source.doc_id,
            lang=self.lang,
            text=source.text,
            metadata=source.metadata,
            sentences=tuple(sentences),
        )

    @staticmethod
    def _convert_token(token) -> AnnotatedToken:
        return AnnotatedToken(
            id=_token_id(token.id),
            text=token.text,
            start_char=int(token.start_char),
            end_char=int(token.end_char),
            spaces_before=getattr(token, "spaces_before", "") or "",
            spaces_after=getattr(token, "spaces_after", "") or "",
            words=tuple(
                AnnotatedWord(
                    id=int(word.id),
                    text=word.text,
                    lemma=getattr(word, "lemma", None),
                    upos=getattr(word, "upos", None) or "X",
                    xpos=getattr(word, "xpos", None),
                    feats=_feature_items(getattr(word, "feats", None)),
                )
                for word in token.words
            ),
        )


def download_models(
    langs: list[str],
    *,
    model_dir: Path | None = None,
    package: str = "default",
) -> None:
    import stanza

    for lang in langs:
        normalized = lang.lower()
        if normalized not in SUPPORTED_LANGS:
            supported = ", ".join(sorted(SUPPORTED_LANGS))
            raise ValueError(
                f"Unsupported tagging language {normalized!r}: {supported}"
            )
        options = {
            "lang": normalized,
            "package": package,
            "processors": PROCESSORS,
        }
        if model_dir is not None:
            options["model_dir"] = str(model_dir)
        stanza.download(**options)
