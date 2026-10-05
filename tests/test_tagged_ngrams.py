import csv
import json
from collections import Counter

import pytest

from semordnilap.ngrams.application import export_tsv, run_extraction
from semordnilap.ngrams.cli.extract import build_argparser, command_from_args
from semordnilap.ngrams.domain import (
    ExtractedNgram,
    NgramExtractionPolicy,
    TaggedNgramKey,
    extract_counts_from_annotated_document,
    extract_counts_from_text,
)
from semordnilap.ngrams.infrastructure import DuckDbNgramCountRepository
from semordnilap.tagging.domain import (
    AnnotatedDocument,
    AnnotatedSentence,
    AnnotatedToken,
    AnnotatedWord,
)


def token(index, text, start, end, upos, *, words=None):
    annotated_words = words or (AnnotatedWord(index, text, upos),)
    return AnnotatedToken(
        id=(index,),
        text=text,
        start_char=start,
        end_char=end,
        words=annotated_words,
    )


def punctuated_document():
    text = "niña, el camino. Antes sigue."
    first = AnnotatedSentence(
        0,
        0,
        16,
        (
            token(1, "niña", 0, 4, "NOUN"),
            token(2, ",", 4, 5, "PUNCT"),
            token(3, "el", 6, 8, "DET"),
            token(4, "camino", 9, 15, "NOUN"),
            token(5, ".", 15, 16, "PUNCT"),
        ),
    )
    second = AnnotatedSentence(
        1,
        17,
        29,
        (
            token(1, "Antes", 17, 22, "ADV"),
            token(2, "sigue", 23, 28, "VERB"),
            token(3, ".", 28, 29, "PUNCT"),
        ),
    )
    return AnnotatedDocument("doc", "es", text, (first, second))


def tagged_by_text(counts):
    return {key.ngram.text: key for key in counts}


def test_tagged_extraction_keeps_punctuation_and_crosses_sentences():
    policy = NgramExtractionPolicy(lang="es", max_n=2, omit_punctuation=False)

    counts = extract_counts_from_annotated_document(
        punctuated_document(), policy
    )
    by_text = tagged_by_text(counts)

    assert by_text["niña, el"].upos_pattern == "NOUN DET"
    assert by_text["niña, el"].crosses_sentence is False
    assert by_text["camino. antes"].upos_pattern == "NOUN ADV"
    assert by_text["camino. antes"].crosses_sentence is True


def test_tagged_extraction_crosses_punctuation_by_default():
    policy = NgramExtractionPolicy(lang="es", max_n=2)

    counts = extract_counts_from_annotated_document(
        punctuated_document(), policy
    )
    surfaces = {key.ngram.text for key in counts}

    assert "niña, el" in surfaces
    assert "camino. antes" in surfaces
    assert "el camino" in surfaces


def test_raw_and_tagged_adapters_have_the_same_canonical_surfaces():
    policy = NgramExtractionPolicy(lang="es", max_n=2)
    raw = extract_counts_from_text(punctuated_document().text, policy)
    tagged = extract_counts_from_annotated_document(
        punctuated_document(), policy
    )

    raw_keys = {(key.tokens, key.text) for key in raw}
    tagged_keys = {(key.ngram.tokens, key.ngram.text) for key in tagged}
    assert raw_keys == tagged_keys


def test_auto_format_detects_ud_schema(tmp_path):
    annotated = tmp_path / "unexpected-name.jsonl"
    annotated.write_text(
        json.dumps(punctuated_document().to_dict(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    args = build_argparser().parse_args(
        [
            "extract",
            "--input",
            str(annotated),
            "--lang",
            "es",
            "--allow-incomplete-input",
        ]
    )

    assert command_from_args(args).input_format == "ud-jsonl"


def test_incomplete_tagged_artifact_is_rejected_by_default(tmp_path):
    annotated = tmp_path / "corpus.jsonl"
    annotated.write_text(
        json.dumps(punctuated_document().to_dict(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    args = build_argparser().parse_args(
        ["extract", "--input", str(annotated), "--lang", "es"]
    )
    command = command_from_args(args)

    with pytest.raises(ValueError, match="manifest is missing"):
        run_extraction(
            command,
            DuckDbNgramCountRepository(tmp_path / "incomplete.duckdb"),
        )


def test_tagged_extraction_preserves_mwt_upos_slots():
    document = AnnotatedDocument(
        "doc",
        "es",
        "al mar",
        (
            AnnotatedSentence(
                0,
                0,
                6,
                (
                    token(
                        1,
                        "al",
                        0,
                        2,
                        "X",
                        words=(
                            AnnotatedWord(1, "a", "ADP"),
                            AnnotatedWord(2, "el", "DET"),
                        ),
                    ),
                    token(3, "mar", 3, 6, "NOUN"),
                ),
            ),
        ),
    )

    counts = extract_counts_from_annotated_document(
        document, NgramExtractionPolicy(lang="es", max_n=2)
    )

    pattern = next(
        key.upos_pattern for key in counts if key.ngram.text == "al mar"
    )
    assert pattern == "ADP+DET NOUN"


def test_repository_aggregates_and_exports_upos_distributions(tmp_path):
    repository = DuckDbNgramCountRepository(tmp_path / "ngrams.duckdb")
    ngram = ExtractedNgram(("bajo", "el"), "bajo el")
    crossing = ExtractedNgram(("camino", "antes"), "camino. antes")
    repository.add_tagged_counts(
        Counter(
            {
                TaggedNgramKey(ngram, "ADP DET"): 73,
                TaggedNgramKey(ngram, "VERB DET"): 4,
                TaggedNgramKey(crossing, "NOUN ADV", True): 2,
            }
        ),
        lang="es",
        corpus="test",
        fold_nasal_letters=False,
    )
    repository.compact_counts(lang="es", corpus="test", n=2)

    rows = list(
        repository.iter_counts(
            lang="es", corpus="test", min_count=1, source="compact"
        )
    )
    by_text = {row.text: row for row in rows}
    assert by_text["bajo el"].count == 77
    assert dict(by_text["bajo el"].upos_counts) == {
        "ADP DET": 73,
        "VERB DET": 4,
    }
    assert by_text["camino. antes"].cross_sentence_count == 2

    output = tmp_path / "ngrams.tsv"
    args = build_argparser().parse_args(
        [
            "export",
            "--lang",
            "es",
            "--corpus",
            "test",
            "--out",
            str(output),
            "--min-count",
            "1",
        ]
    )
    export_tsv(command_from_args(args), repository)
    repository.close()

    with output.open("r", encoding="utf-8", newline="") as stream:
        exported = {
            row["text"]: row for row in csv.DictReader(stream, delimiter="\t")
        }
    assert json.loads(exported["bajo el"]["upos_counts"]) == {
        "ADP DET": 73,
        "VERB DET": 4,
    }
    assert exported["camino. antes"]["cross_sentence_count"] == "2"


def test_extract_cli_accepts_ud_jsonl():
    args = build_argparser().parse_args(
        [
            "extract",
            "--input",
            "tagged.ud.jsonl",
            "--format",
            "ud-jsonl",
            "--lang",
            "es",
            "--keep-punctuation",
            "--allow-incomplete-input",
        ]
    )

    command = command_from_args(args)

    assert command.input_format == "ud-jsonl"
    assert command.policy.omit_punctuation is False


def test_annotated_jsonl_runs_through_complete_extraction(tmp_path):
    annotated = tmp_path / "corpus.ud.jsonl"
    annotated.write_text(
        json.dumps(punctuated_document().to_dict(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "ngrams.duckdb"
    args = build_argparser().parse_args(
        [
            "extract",
            "--input",
            str(annotated),
            "--format",
            "ud-jsonl",
            "--lang",
            "es",
            "--corpus",
            "tagged",
            "--db-path",
            str(db_path),
            "--max-n",
            "2",
            "--keep-punctuation",
            "--allow-incomplete-input",
        ]
    )

    run_extraction(
        command_from_args(args), DuckDbNgramCountRepository(db_path)
    )

    repository = DuckDbNgramCountRepository(db_path)
    rows = list(
        repository.iter_counts(
            lang="es", corpus="tagged", min_count=1, source="compact"
        )
    )
    repository.close()
    by_text = {row.text: row for row in rows}
    assert dict(by_text["niña, el"].upos_counts) == {"NOUN DET": 1}
    assert by_text["camino. Antes"].cross_sentence_count == 1
