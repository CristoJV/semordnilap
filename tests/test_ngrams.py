import csv
import logging
from collections import Counter
from dataclasses import replace
from types import SimpleNamespace

import pytest

from semordnilap.ngrams.application import (
    ExtractNgramsCommand,
    count_corpus,
    export_tsv,
    run_extraction,
)
from semordnilap.ngrams.cli.extract import (
    build_argparser,
    command_from_args,
    log_stats,
)
from semordnilap.ngrams.domain import (
    ExtractedNgram,
    NgramExtractionPolicy,
    build_ngram_count,
    extract_counts_from_text,
)
from semordnilap.ngrams.domain.filters import is_all_stopwords
from semordnilap.ngrams.domain.normalize import normalize_ngram
from semordnilap.ngrams.domain.tokenize import (
    iter_sentence_chunks,
    tokenize_sentence,
)
from semordnilap.ngrams.infrastructure import DuckDbNgramCountRepository
from semordnilap.utils.io import iter_texts


def build_options(corpus, output, lang, *, corpus_name="test"):
    return ExtractNgramsCommand(
        input_path=corpus,
        output_path=output,
        corpus=corpus_name,
        input_format="txt",
        text_field="text",
        min_count=1,
        max_results=0,
        export_n=0,
        min_export_norm_len=0,
        max_export_norm_len=0,
        export_log_every=0,
        limit_docs=0,
        flush_unique_ngrams=250_000,
        reset=False,
        export_only=False,
        export_after_count=True,
        delete_only=False,
        policy=NgramExtractionPolicy(lang=lang, max_n=2),
    )


def collect_counts(opts, db_path):
    repository = DuckDbNgramCountRepository(db_path)
    count_corpus(opts, repository)
    counts = Counter()
    for row in repository.iter_counts(
        lang=opts.policy.lang, corpus=opts.corpus, min_count=1
    ):
        counts[row.tokens] = row.count
    repository.close()
    return counts


def test_sentence_chunks_split_on_every_punctuation_character():
    chunks = list(iter_sentence_chunks("La niña, el perro—y la gata"))
    assert [tokenize_sentence(chunk) for chunk in chunks] == [
        ["la", "niña"],
        ["el", "perro"],
        ["y", "la", "gata"],
    ]


def test_default_extraction_keeps_and_crosses_punctuation():
    counts = extract_counts_from_text(
        "La niña, el perro.", NgramExtractionPolicy(lang="es", max_n=2)
    )
    assert counts[ExtractedNgram(("niña", "el"), "niña, el")] == 1


def test_punctuation_boundary_filter_is_opt_in():
    counts = extract_counts_from_text(
        "La niña, el perro.",
        NgramExtractionPolicy(
            lang="es", max_n=2, filter_punctuation_boundaries=True
        ),
    )
    assert ExtractedNgram(("niña", "el"), "niña, el") not in counts


def test_all_stopword_ngrams_are_included_by_default_and_filter_is_opt_in():
    default = extract_counts_from_text(
        "De a casa", NgramExtractionPolicy(lang="gl", max_n=2)
    )
    filtered = extract_counts_from_text(
        "De a casa",
        NgramExtractionPolicy(
            lang="gl", max_n=2, filter_all_stopword_ngrams=True
        ),
    )
    key = ExtractedNgram(("de", "a"), "de a")
    assert key in default
    assert key not in filtered
    assert ExtractedNgram(("a", "casa"), "a casa") in filtered


def test_default_normalization_folds_nasal_n_and_can_preserve_it():
    assert normalize_ngram("niña") == "nina"
    assert normalize_ngram("niña", preserve_nasal_letters=True) == "niña"
    assert normalize_ngram("coração") == "coracao"


def test_build_count_tracks_punctuation_and_default_normalization():
    row = build_ngram_count(
        ("niña,", "el"), count=1, lang="es", corpus="test"
    )
    assert row.text == "niña, el"
    assert row.tokens == ("niña", "el")
    assert row.norm_key == "ninael"
    assert row.has_punctuation is True


def test_unicode_tokenizer_keeps_apostrophe_and_hyphen_words():
    counts = extract_counts_from_text(
        "D'Artagnan fala co-operar.", NgramExtractionPolicy(lang="gl", max_n=1)
    )
    tokens = {ngram.tokens for ngram in counts}
    assert ("d'artagnan",) in tokens
    assert ("co-operar",) in tokens


def test_stopword_tables_cover_supported_languages():
    assert is_all_stopwords(("the", "and"), "en")
    assert is_all_stopwords(("de", "la"), "fr")
    assert is_all_stopwords(("de", "a"), "gl")


def test_iter_texts_accepts_corpus_directory(tmp_path):
    (tmp_path / "one.txt").write_text("uno\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "two.txt").write_text("dos\n", encoding="utf-8")
    assert list(iter_texts(tmp_path, "txt")) == ["uno\n", "dos\n"]


def test_extract_cli_has_minimally_restrictive_defaults():
    args = build_argparser().parse_args(
        ["extract", "--input", "corpus.txt", "--lang", "GL"]
    )
    policy = command_from_args(args).policy
    assert policy.lang == "gl"
    assert policy.filter_min_token_len == 2
    assert policy.filter_max_token_len == 30
    assert policy.filter_min_norm_len == 2
    assert policy.filter_all_stopword_ngrams is False
    assert policy.filter_punctuation_boundaries is False
    assert policy.preserve_nasal_letters is False


def test_extract_cli_exposes_explicit_filter_options_only():
    parser = build_argparser()
    extract = parser._subparsers._group_actions[0].choices["extract"]
    rendered = extract.format_help()
    assert "--filter-min-token-len" in rendered
    assert "--filter-max-token-len" in rendered
    assert "--filter-min-norm-len" in rendered
    assert "--filter-all-stopword-ngrams" in rendered
    assert "--filter-punctuation-boundaries" in rendered
    assert "--preserve-nasal-letters" in rendered
    for obsolete in (
        "--min-token-len",
        "--include-all-stopword-ngrams",
        "--fold-nasal-letters",
        "--omit-punctuation",
        "--chunk-docs",
        "--no-compact-after-count",
    ):
        assert obsolete not in rendered
    db = parser._subparsers._group_actions[0].choices["db"]
    assert "compact" not in db._subparsers._group_actions[0].choices


def test_extract_cli_can_enable_filters_and_preserve_nasal_letters():
    args = build_argparser().parse_args(
        [
            "extract",
            "--input",
            "corpus.txt",
            "--lang",
            "es",
            "--filter-min-token-len",
            "3",
            "--filter-max-token-len",
            "20",
            "--filter-min-norm-len",
            "4",
            "--filter-all-stopword-ngrams",
            "--filter-punctuation-boundaries",
            "--preserve-nasal-letters",
        ]
    )
    policy = command_from_args(args).policy
    assert policy.filter_min_token_len == 3
    assert policy.filter_max_token_len == 20
    assert policy.filter_min_norm_len == 4
    assert policy.filter_all_stopword_ngrams is True
    assert policy.filter_punctuation_boundaries is True
    assert policy.preserve_nasal_letters is True


def test_count_corpus_finalizes_generation_and_is_idempotent(tmp_path):
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("La casa. El camino\n", encoding="utf-8")
    opts = build_options(corpus, tmp_path / "ngrams.tsv", "es")
    first = collect_counts(opts, tmp_path / "ngrams.duckdb")
    replay = collect_counts(opts, tmp_path / "ngrams.duckdb")
    assert first == replay
    assert replay[("casa", "el")] == 1


def test_reset_rebuilds_only_matching_dataset(tmp_path):
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("La casa\n", encoding="utf-8")
    db_path = tmp_path / "ngrams.duckdb"
    opts = build_options(corpus, tmp_path / "ngrams.tsv", "es")
    collect_counts(opts, db_path)
    reset = collect_counts(replace(opts, reset=True), db_path)
    assert reset[("la", "casa")] == 1


def test_export_reads_only_final_generation_and_applies_read_filters(tmp_path):
    corpus = tmp_path / "corpus.txt"
    output = tmp_path / "ngrams.tsv"
    corpus.write_text("Casa casa. La casa azul.\n", encoding="utf-8")
    opts = replace(
        build_options(corpus, output, "es"),
        export_n=1,
        min_export_norm_len=4,
        max_results=1,
    )
    repository = DuckDbNgramCountRepository(tmp_path / "ngrams.duckdb")
    count_corpus(opts, repository)
    assert export_tsv(opts, repository) == 1
    repository.close()
    with output.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    assert rows[0]["text"].casefold() == "casa"
    assert rows[0]["count"] == "3"


def test_punctuation_metadata_is_persisted_and_exported(tmp_path):
    corpus = tmp_path / "corpus.txt"
    output = tmp_path / "ngrams.tsv"
    corpus.write_text("La niña, el perro.\n", encoding="utf-8")
    opts = build_options(corpus, output, "es")
    repository = DuckDbNgramCountRepository(tmp_path / "ngrams.duckdb")
    count_corpus(opts, repository)
    rows = list(repository.iter_counts(lang="es", corpus="test", min_count=1))
    export_tsv(opts, repository)
    repository.close()
    punctuated = next(row for row in rows if row.text == "niña, el")
    assert punctuated.has_punctuation is True
    assert punctuated.norm_key == "ninael"


def test_delete_only_removes_one_collection(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    es = tmp_path / "es.txt"
    en = tmp_path / "en.txt"
    es.write_text("La casa\n", encoding="utf-8")
    en.write_text("The house\n", encoding="utf-8")
    collect_counts(build_options(es, tmp_path / "es.tsv", "es"), db_path)
    collect_counts(build_options(en, tmp_path / "en.tsv", "en"), db_path)
    opts = replace(
        build_options(es, tmp_path / "unused.tsv", "es"), delete_only=True
    )
    assert run_extraction(opts, DuckDbNgramCountRepository(db_path)) > 0
    repository = DuckDbNgramCountRepository(db_path)
    assert repository.stats(lang="es", corpus="test")["datasets"] == []
    assert list(repository.iter_counts(lang="en", corpus="test", min_count=1))
    repository.close()


def test_stats_describe_only_generation_storage(tmp_path, caplog):
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("A casa azul\n", encoding="utf-8")
    db_path = tmp_path / "ngrams.duckdb"
    collect_counts(build_options(corpus, tmp_path / "out.tsv", "gl"), db_path)
    repository = DuckDbNgramCountRepository(db_path)
    stats = repository.stats(lang="gl", corpus="test", include_top_rows=True)
    inventory = {row[0] for row in stats["table_inventory"]}
    assert stats["schema_version"] == 4
    assert stats["datasets"][0][7] == "complete"
    assert stats["generation_by_n"]
    assert stats["top_rows"]
    assert {"ngram_counts", "ngram_totals", "ngram_compactions"}.isdisjoint(
        inventory
    )
    caplog.set_level(logging.INFO, logger="semordnilap.ngrams.cli.extract")
    log_stats(repository, SimpleNamespace(lang="gl", corpus="test", verbose=True))
    repository.close()
    assert "matching final counts by n:" in caplog.text
    assert "ngram_counts" not in caplog.text


def test_extract_rejects_detected_annotated_input(tmp_path):
    annotated = tmp_path / "annotated.jsonl"
    annotated.write_text(
        '{"schema":"semordnilap.ud-jsonl","schema_version":2}\n',
        encoding="utf-8",
    )
    args = build_argparser().parse_args(
        ["extract", "--input", str(annotated), "--lang", "gl"]
    )
    with pytest.raises(ValueError, match="no longer supported"):
        command_from_args(args)
