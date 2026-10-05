import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from semordnilap.tagging import application as tagging_application
from semordnilap.tagging.application import (
    TagCorpusCommand,
    manifest_path,
    partial_manifest_path,
    partial_output_path,
    tag_corpus,
)
from semordnilap.tagging.cli import build_argparser
from semordnilap.tagging.domain import (
    AnnotatedDocument,
    AnnotatedSentence,
    AnnotatedToken,
    AnnotatedWord,
    SourceDocument,
)
from semordnilap.tagging.io import (
    count_source_documents,
    iter_annotated_documents,
    iter_source_records,
)
from semordnilap.tagging.stanza import StanzaPosTagger


def sample_document(doc_id="doc-1", text="Bajo el puente."):
    tokens = (
        AnnotatedToken(
            id=(1,),
            text="Bajo",
            start_char=0,
            end_char=4,
            spaces_after=" ",
            words=(AnnotatedWord(1, "Bajo", "ADP", lemma="bajo"),),
        ),
        AnnotatedToken(
            id=(2,),
            text="el",
            start_char=5,
            end_char=7,
            spaces_after=" ",
            words=(AnnotatedWord(2, "el", "DET", lemma="el"),),
        ),
        AnnotatedToken(
            id=(3,),
            text="puente",
            start_char=8,
            end_char=14,
            words=(AnnotatedWord(3, "puente", "NOUN", lemma="puente"),),
        ),
        AnnotatedToken(
            id=(4,),
            text=".",
            start_char=14,
            end_char=15,
            words=(AnnotatedWord(4, ".", "PUNCT", lemma="."),),
        ),
    )
    return AnnotatedDocument(
        doc_id=doc_id,
        lang="es",
        text=text,
        sentences=(AnnotatedSentence(0, 0, len(text), tokens),),
    )


def test_annotated_document_json_round_trip_is_provider_neutral():
    document = sample_document()

    encoded = document.to_dict()
    decoded = AnnotatedDocument.from_dict(encoded)

    assert decoded == document
    assert encoded["schema"] == "semordnilap.ud-jsonl"
    assert encoded["schema_version"] == 1
    assert "stanza" not in json.dumps(encoded).lower()


def test_compact_v2_round_trip_keeps_upos_and_feats_without_lemma_xpos():
    document = sample_document()
    value = document.to_dict(
        schema_version=2, profile="compact", ordinal=7
    )
    decoded = AnnotatedDocument.from_dict(value)

    assert value["schema_version"] == 2
    assert value["ordinal"] == 7
    assert "text" not in value["sentences"][0]["t"][0]
    assert decoded.sentences[0].tokens[0].text == "Bajo"
    assert decoded.sentences[0].tokens[0].words[0].upos == "ADP"
    assert decoded.sentences[0].tokens[0].words[0].lemma is None


def test_full_v2_round_trip_keeps_optional_lemma_and_xpos():
    document = sample_document()
    value = document.to_dict(schema_version=2, profile="full")
    decoded = AnnotatedDocument.from_dict(value)

    decoded_word = decoded.sentences[0].tokens[0].words[0]
    assert decoded_word.lemma == "bajo"
    assert decoded_word.upos == "ADP"


def test_domain_rejects_non_upos_tags():
    with pytest.raises(ValueError, match="Invalid UPOS"):
        AnnotatedWord(1, "casa", "NCFS")


def test_domain_coerces_token_ids_and_rejects_incorrect_spans():
    value = sample_document().to_dict()
    value["sentences"][0]["tokens"][0]["id"] = ["1"]
    assert AnnotatedDocument.from_dict(value).sentences[0].tokens[0].id == (1,)

    value["sentences"][0]["tokens"][0]["text"] = "Otra"
    with pytest.raises(ValueError, match="does not match document span"):
        AnnotatedDocument.from_dict(value)


def test_stanza_metadata_hashes_exact_model_files(tmp_path):
    model_dir = tmp_path / "models"
    language = model_dir / "es" / "pos"
    language.mkdir(parents=True)
    model = language / "model.pt"
    model.write_bytes(b"first")

    first = StanzaPosTagger("es", model_dir=model_dir).metadata["model_digest"]
    model.write_bytes(b"second")
    second = StanzaPosTagger("es", model_dir=model_dir).metadata[
        "model_digest"
    ]

    assert first != second


def test_stanza_adapter_preserves_mwt_and_offsets():
    words = [
        SimpleNamespace(
            id=1,
            text="a",
            lemma="a",
            upos="ADP",
            xpos="SPS00",
            feats=None,
        ),
        SimpleNamespace(
            id=2,
            text="el",
            lemma="el",
            upos="DET",
            xpos="DA0MS0",
            feats="Gender=Masc|Number=Sing",
        ),
    ]
    token = SimpleNamespace(
        id=(1, 2),
        text="al",
        start_char=0,
        end_char=2,
        spaces_before="",
        spaces_after=" ",
        words=words,
    )

    def pipeline(text):
        return SimpleNamespace(sentences=[SimpleNamespace(tokens=[token])])

    tagger = StanzaPosTagger("es", pipeline=pipeline)

    document = tagger.annotate(SourceDocument("doc", "al "))

    converted = document.sentences[0].tokens[0]
    assert converted.id == (1, 2)
    assert converted.upos_slot == "ADP+DET"
    assert converted.start_char == 0
    assert converted.end_char == 2
    assert converted.words[1].feats == (
        ("Gender", ("Masc",)),
        ("Number", ("Sing",)),
    )


def test_stanza_pipeline_is_loaded_only_for_first_annotation():
    tagger = StanzaPosTagger("es")

    assert tagger._pipeline is None


class FakeTagger:
    metadata = {"adapter": "fake", "tagset": "UPOS"}

    def annotate(self, source):
        return sample_document(source.doc_id, source.text)


class InterruptingTagger(FakeTagger):
    def __init__(self, fail_on_call):
        self.calls = 0
        self.fail_on_call = fail_on_call

    def annotate(self, source):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("simulated interruption")
        return super().annotate(source)


class RecordingTagger(FakeTagger):
    def __init__(self):
        self.doc_ids = []

    def annotate(self, source):
        self.doc_ids.append(source.doc_id)
        return super().annotate(source)


class EchoTagger:
    lang = "es"
    metadata = {"adapter": "echo", "tagset": "UPOS"}

    def annotate(self, source):
        token = AnnotatedToken(
            id=(1,),
            text=source.text,
            start_char=0,
            end_char=len(source.text),
            words=(AnnotatedWord(1, source.text, "NOUN"),),
        )
        return AnnotatedDocument(
            doc_id=source.doc_id,
            lang="es",
            text=source.text,
            sentences=(
                AnnotatedSentence(0, 0, len(source.text), (token,)),
            ),
        )


def test_tag_corpus_writes_document_jsonl_and_manifest(tmp_path):
    source = tmp_path / "corpus.jsonl"
    source.write_text(
        json.dumps({"id": "doc-1", "text": "Bajo el puente."}) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "tagged.ud.jsonl"

    manifest = tag_corpus(
        TagCorpusCommand(source, output, "es", input_format="jsonl"),
        FakeTagger(),
    )

    documents = list(iter_annotated_documents(output))
    written_manifest = json.loads(
        manifest_path(output).read_text(encoding="utf-8")
    )
    assert documents[0].doc_id == "doc-1"
    assert manifest["documents"] == 1
    assert written_manifest["tagger"]["tagset"] == "UPOS"


def test_count_source_documents_reports_jsonl_progress_total(tmp_path):
    source = tmp_path / "corpus.jsonl"
    source.write_text(
        '{"id":"1","text":"uno"}\n\n{"id":"2","text":"dos"}\n',
        encoding="utf-8",
    )

    assert count_source_documents(source, "jsonl") == 2


def test_tag_corpus_resumes_partial_jsonl_without_duplicates(tmp_path):
    source = tmp_path / "corpus.jsonl"
    source.write_text(
        "".join(
            json.dumps({"id": str(index), "text": "Bajo el puente."}) + "\n"
            for index in range(1, 4)
        ),
        encoding="utf-8",
    )
    output = tmp_path / "tagged.ud.jsonl"
    first_command = TagCorpusCommand(
        source,
        output,
        "es",
        input_format="jsonl",
        checkpoint_docs=10,
    )

    with pytest.raises(RuntimeError, match="simulated interruption"):
        tag_corpus(first_command, InterruptingTagger(fail_on_call=2))

    partial = partial_output_path(output)
    checkpoint = partial_manifest_path(output)
    assert output.exists() is False
    assert [doc.doc_id for doc in iter_annotated_documents(partial)] == ["1"]
    # The partial stream, not a potentially stale checkpoint counter, is the
    # source of truth for the resume position.
    assert json.loads(checkpoint.read_text(encoding="utf-8"))["documents"] == 0

    # Simulate a hard stop midway through writing the next JSONL record.
    with partial.open("ab") as stream:
        stream.write(b'{"incomplete":')

    manifest = tag_corpus(
        TagCorpusCommand(
            source,
            output,
            "es",
            input_format="jsonl",
            resume=True,
            checkpoint_docs=10,
        ),
        FakeTagger(),
    )

    assert [doc.doc_id for doc in iter_annotated_documents(output)] == [
        "1",
        "2",
        "3",
    ]
    assert manifest["documents"] == 3
    assert partial.exists() is False
    assert checkpoint.exists() is False


def test_v2_checkpoint_resumes_at_source_and_output_offsets(tmp_path):
    source = tmp_path / "corpus.jsonl"
    source.write_text(
        "".join(
            json.dumps({"id": str(index), "text": "Bajo el puente."}) + "\n"
            for index in range(1, 4)
        ),
        encoding="utf-8",
    )
    output = tmp_path / "tagged.ud.jsonl"

    with pytest.raises(RuntimeError, match="simulated interruption"):
        tag_corpus(
            TagCorpusCommand(
                source,
                output,
                "es",
                input_format="jsonl",
                checkpoint_docs=1,
            ),
            InterruptingTagger(fail_on_call=2),
        )

    checkpoint = json.loads(
        partial_manifest_path(output).read_text(encoding="utf-8")
    )
    assert checkpoint["checkpoint_version"] == 2
    assert checkpoint["documents"] == 1
    assert checkpoint["partial_byte_offset"] > 0
    assert checkpoint["source_cursor"]["line_number"] == 1

    tagger = RecordingTagger()
    tag_corpus(
        TagCorpusCommand(
            source,
            output,
            "es",
            input_format="jsonl",
            resume=True,
            checkpoint_docs=1,
        ),
        tagger,
    )

    assert tagger.doc_ids == ["2", "3"]
    assert [doc.doc_id for doc in iter_annotated_documents(output)] == [
        "1",
        "2",
        "3",
    ]


def test_legacy_checkpoint_is_indexed_once_with_progress(tmp_path, capsys):
    source = tmp_path / "corpus.jsonl"
    source.write_text(
        "".join(
            json.dumps({"id": str(index), "text": "Bajo el puente."}) + "\n"
            for index in range(1, 4)
        ),
        encoding="utf-8",
    )
    output = tmp_path / "tagged.ud.jsonl"

    with pytest.raises(RuntimeError, match="simulated interruption"):
        tag_corpus(
            TagCorpusCommand(
                source,
                output,
                "es",
                input_format="jsonl",
                checkpoint_docs=10,
            ),
            InterruptingTagger(fail_on_call=2),
        )

    checkpoint_path = partial_manifest_path(output)
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    for field in (
        "checkpoint_version",
        "partial_byte_offset",
        "source_cursor",
        "reader",
        "source_snapshot",
    ):
        checkpoint.pop(field)
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    tagger = RecordingTagger()
    tag_corpus(
        TagCorpusCommand(
            source,
            output,
            "es",
            input_format="jsonl",
            resume=True,
            checkpoint_docs=1,
        ),
        tagger,
    )

    assert "Indexing partial output" in capsys.readouterr().err
    assert tagger.doc_ids == ["2", "3"]


def test_interrupted_legacy_indexing_resumes_from_its_cursor(
    tmp_path, monkeypatch
):
    source = tmp_path / "corpus.jsonl"
    source.write_text(
        "".join(
            json.dumps({"id": str(index), "text": "Bajo el puente."}) + "\n"
            for index in range(1, 4)
        ),
        encoding="utf-8",
    )
    output = tmp_path / "tagged.ud.jsonl"

    with pytest.raises(RuntimeError, match="simulated interruption"):
        tag_corpus(
            TagCorpusCommand(
                source,
                output,
                "es",
                input_format="jsonl",
                checkpoint_docs=10,
            ),
            InterruptingTagger(fail_on_call=3),
        )

    checkpoint_path = partial_manifest_path(output)
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    for field in (
        "checkpoint_version",
        "partial_byte_offset",
        "source_cursor",
        "reader",
        "source_snapshot",
    ):
        checkpoint.pop(field)
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    original_iterator = tagging_application.iter_annotated_document_records

    def interrupted_iterator(*args, **kwargs):
        records = original_iterator(*args, **kwargs)
        yield next(records)
        raise RuntimeError("indexing interrupted")

    monkeypatch.setattr(tagging_application, "RECOVERY_CHECKPOINT_DOCS", 1)
    monkeypatch.setattr(
        tagging_application,
        "iter_annotated_document_records",
        interrupted_iterator,
    )
    command = TagCorpusCommand(
        source,
        output,
        "es",
        input_format="jsonl",
        resume=True,
        checkpoint_docs=1,
    )
    with pytest.raises(RuntimeError, match="indexing interrupted"):
        tag_corpus(command, FakeTagger())

    recovering = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert recovering["status"] == "recovering"
    assert recovering["documents"] == 1

    monkeypatch.setattr(
        tagging_application,
        "iter_annotated_document_records",
        original_iterator,
    )
    tagger = RecordingTagger()
    tag_corpus(command, tagger)

    assert tagger.doc_ids == ["3"]
    assert [doc.doc_id for doc in iter_annotated_documents(output)] == [
        "1",
        "2",
        "3",
    ]


def test_source_cursor_starts_at_next_jsonl_document(tmp_path):
    source = tmp_path / "corpus.jsonl"
    source.write_text(
        '{"id":"1","text":"uno"}\n\n{"id":"2","text":"dos"}\n',
        encoding="utf-8",
    )

    records = iter_source_records(source, "jsonl")
    first = next(records)
    resumed = list(
        iter_source_records(source, "jsonl", start_cursor=first.next_cursor)
    )

    assert first.document.doc_id == "1"
    assert [record.document.doc_id for record in resumed] == ["2"]
    assert resumed[0].next_cursor.line_number == 3


def test_v2_tagging_writes_resumable_compressed_shards(tmp_path):
    source = tmp_path / "corpus.jsonl"
    source.write_text(
        "".join(
            json.dumps({"id": str(index), "text": "Bajo el puente."})
            + "\n"
            for index in range(1, 4)
        ),
        encoding="utf-8",
    )
    output = tmp_path / "tagged-v2"
    command = TagCorpusCommand(
        source,
        output,
        "es",
        input_format="jsonl",
        output_format="ud-jsonl-v2",
        shard_docs=1,
        on_document_error="fail",
    )

    with pytest.raises(RuntimeError, match="simulated interruption"):
        tag_corpus(command, InterruptingTagger(fail_on_call=2))

    partial = output.with_name(output.name + ".part")
    checkpoint = json.loads(
        (partial / "manifest.json").read_text(encoding="utf-8")
    )
    assert checkpoint["documents"] == 1
    assert checkpoint["shards"][0]["path"].endswith(".jsonl.gz")

    manifest = tag_corpus(
        replace(command, resume=True),
        RecordingTagger(),
    )
    assert manifest["status"] == "complete"
    assert manifest["schema_version"] == 2
    assert len(manifest["shards"]) == 3
    assert [item.doc_id for item in iter_annotated_documents(output)] == [
        "1",
        "2",
        "3",
    ]


def test_v2_long_document_splits_with_global_offsets(tmp_path):
    source = tmp_path / "corpus.jsonl"
    text = "uno dos tres cuatro cinco"
    source.write_text(
        json.dumps({"id": "long", "text": text}) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "tagged-v2"

    tag_corpus(
        TagCorpusCommand(
            source,
            output,
            "es",
            input_format="jsonl",
            output_format="ud-jsonl-v2",
            max_document_chars=9,
        ),
        EchoTagger(),
    )

    document = next(iter_annotated_documents(output))
    assert document.text == text
    assert len(document.sentences) > 1
    assert document.metadata["tagging_chunks"][0]["start_char"] == 0
    for sentence in document.sentences:
        token = sentence.tokens[0]
        assert document.text[token.start_char : token.end_char] == token.text


def test_v2_quarantines_an_unsplittable_document_and_continues(tmp_path):
    source = tmp_path / "corpus.jsonl"
    source.write_text(
        json.dumps({"id": "bad", "text": "x" * 20})
        + "\n"
        + json.dumps({"id": "good", "text": "dos palabras"})
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "tagged-v2"

    manifest = tag_corpus(
        TagCorpusCommand(
            source,
            output,
            "es",
            input_format="jsonl",
            output_format="ud-jsonl-v2",
            max_document_chars=12,
            on_document_error="quarantine",
            shard_docs=1,
        ),
        EchoTagger(),
    )

    assert manifest["documents"] == 2
    assert manifest["quarantined_documents"] == 1
    assert [item.doc_id for item in iter_annotated_documents(output)] == [
        "good"
    ]


def test_v2_completed_resume_is_noop(tmp_path):
    source = tmp_path / "corpus.jsonl"
    source.write_text(
        json.dumps({"id": "one", "text": "dos palabras"}) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "tagged-v2"
    command = TagCorpusCommand(
        source,
        output,
        "es",
        input_format="jsonl",
        output_format="ud-jsonl-v2",
    )
    first = tag_corpus(command, EchoTagger())
    second = tag_corpus(replace(command, resume=True), EchoTagger())

    assert second["artifact_id"] == first["artifact_id"]


def test_v2_storage_failures_are_not_quarantined(tmp_path, monkeypatch):
    source = tmp_path / "corpus.jsonl"
    source.write_text(
        json.dumps({"id": "one", "text": "dos palabras"}) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "tagged-v2"

    def fail_storage(*args, **kwargs):
        raise OSError("disk failure")

    from semordnilap.tagging import sharded

    monkeypatch.setattr(sharded, "_write_shard", fail_storage)
    with pytest.raises(OSError, match="disk failure"):
        tag_corpus(
            TagCorpusCommand(
                source,
                output,
                "es",
                input_format="jsonl",
                output_format="ud-jsonl-v2",
                shard_docs=1,
            ),
            EchoTagger(),
        )

    state = json.loads(
        (output.with_name(output.name + ".part") / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["quarantined_documents"] == 0


def test_tag_cli_supports_es_and_gl():
    parser = build_argparser()
    annotate = parser.parse_args(
        [
            "annotate",
            "--input",
            "corpus.jsonl",
            "--out",
            "tagged.jsonl",
            "--lang",
            "gl",
            "--resume",
            "--checkpoint-docs",
            "25",
        ]
    )
    download = parser.parse_args(["download", "--langs", "es", "gl"])

    assert annotate.lang == "gl"
    assert annotate.resume is True
    assert annotate.checkpoint_docs == 25
    assert download.langs == ["es", "gl"]
