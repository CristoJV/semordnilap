import csv
from collections import Counter
from dataclasses import replace

from semordnilap.ngrams.cli.extract import build_argparser, command_from_args
from semordnilap.ngrams.application import (
    ExtractNgramsCommand,
    count_corpus,
    export_tsv,
    compact_all_counts,
    run_extraction,
)
from semordnilap.ngrams.domain import NgramExtractionPolicy
from semordnilap.ngrams.domain.filters import is_all_stopwords
from semordnilap.ngrams.domain.normalize import normalize_ngram
from semordnilap.ngrams.domain.tokenize import (
    iter_sentence_chunks,
    tokenize_sentence,
)
from semordnilap.ngrams.infrastructure import DuckDbNgramCountRepository
from semordnilap.utils.io import iter_texts


def build_options(corpus, output, lang):
    return ExtractNgramsCommand(
        input_path=corpus,
        output_path=output,
        corpus="test",
        input_format="txt",
        text_field="text",
        min_count=1,
        max_results=0,
        export_n=0,
        min_export_norm_len=0,
        max_export_norm_len=0,
        export_source="auto",
        export_log_every=0,
        limit_docs=0,
        chunk_docs=1000,
        flush_unique_ngrams=250_000,
        reset=False,
        export_only=False,
        export_after_count=True,
        delete_only=False,
        compact_only=False,
        compact_n=0,
        compact_after_count=True,
        policy=NgramExtractionPolicy(lang=lang, max_n=2),
    )


def test_sentence_chunks_do_not_cross_strong_punctuation():
    text = "La casa. El camino"

    chunks = list(iter_sentence_chunks(text))
    tokenized = [tokenize_sentence(chunk) for chunk in chunks]

    assert tokenized == [["la", "casa"], ["el", "camino"]]


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


def test_count_corpus_does_not_cross_sentence_boundaries(tmp_path):
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("La casa. El camino\n", encoding="utf-8")

    opts = build_options(corpus, tmp_path / "ngrams.tsv", "es")

    counts = collect_counts(opts, tmp_path / "ngrams.duckdb")

    assert ("casa", "el") not in counts
    assert counts[("la", "casa")] == 1
    assert counts[("el", "camino")] == 1


def test_export_ngrams_writes_expected_tsv(tmp_path):
    corpus = tmp_path / "corpus.txt"
    output = tmp_path / "ngrams.tsv"
    corpus.write_text("À dor. A dor.\n", encoding="utf-8")

    opts = build_options(corpus, output, "pt")

    repository = DuckDbNgramCountRepository(tmp_path / "ngrams.duckdb")
    count_corpus(opts, repository)
    export_tsv(opts, repository)
    repository.close()

    with output.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    assert any(
        row["text"] == "à dor" and row["norm_key"] == "ador" for row in rows
    )
    assert normalize_ngram("coração") == "coracao"


def test_tokenization_ignores_urls_and_markers():
    text = "A casa {{marca}} https://example.com. O caminho [[nota]]"

    chunks = list(iter_sentence_chunks(text))
    tokenized = [tokenize_sentence(chunk) for chunk in chunks]

    assert tokenized == [["a", "casa"], ["o", "caminho"]]


def test_extraction_supports_english_french_and_galician():
    examples = [
        ("en", "I saw a house.", ("i", "saw")),
        ("fr", "Il va à Paris.", ("va", "à")),
        ("gl", "A casa e o camiño.", ("casa", "e")),
    ]

    for lang, text, expected in examples:
        counts = extract_counts_for_lang(text, lang)
        assert expected in counts


def extract_counts_for_lang(text, lang):
    from semordnilap.ngrams.domain import extract_counts_from_text

    return extract_counts_from_text(
        text,
        NgramExtractionPolicy(lang=lang, max_n=2),
    )


def test_stopword_filters_include_new_languages():
    assert is_all_stopwords(("the", "and"), "en")
    assert is_all_stopwords(("de", "la"), "fr")
    assert is_all_stopwords(("de", "a"), "gl")


def test_iter_texts_accepts_corpus_directory(tmp_path):
    (tmp_path / "one.txt").write_text("uno\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "two.txt").write_text("dos\n", encoding="utf-8")

    assert list(iter_texts(tmp_path, "txt")) == ["uno\n", "dos\n"]


def test_extract_subcommand_counts_without_exporting():
    args = build_argparser().parse_args(
        [
            "extract",
            "--input",
            "corpus.jsonl",
            "--lang",
            "ES",
            "--corpus",
            "wikisource",
            "--format",
            "jsonl",
        ]
    )

    command = command_from_args(args)

    assert command.policy.lang == "es"
    assert command.input_path.name == "corpus.jsonl"
    assert command.export_after_count is False
    assert command.compact_after_count is True


def test_export_subcommand_uses_existing_database_counts():
    args = build_argparser().parse_args(
        [
            "export",
            "--lang",
            "es",
            "--corpus",
            "wikisource",
            "--out",
            "ngrams.tsv",
        ]
    )

    command = command_from_args(args)

    assert command.export_only is True
    assert command.export_after_count is True
    assert command.output_path.name == "ngrams.tsv"


def test_db_delete_subcommand_targets_lang_corpus():
    args = build_argparser().parse_args(
        [
            "db",
            "delete",
            "--lang",
            "es",
            "--corpus",
            "wikisource",
        ]
    )

    command = command_from_args(args)

    assert command.delete_only is True
    assert command.corpus == "wikisource"


def test_reset_recomputes_lang_corpus_counts(tmp_path):
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("La casa\n", encoding="utf-8")
    db_path = tmp_path / "ngrams.duckdb"

    opts = build_options(corpus, tmp_path / "ngrams.tsv", "es")
    collect_counts(opts, db_path)
    doubled = collect_counts(opts, db_path)

    reset_opts = ExtractNgramsCommand(
        input_path=opts.input_path,
        output_path=opts.output_path,
        corpus=opts.corpus,
        input_format=opts.input_format,
        text_field=opts.text_field,
        min_count=opts.min_count,
        max_results=opts.max_results,
        export_n=opts.export_n,
        min_export_norm_len=opts.min_export_norm_len,
        max_export_norm_len=opts.max_export_norm_len,
        export_source=opts.export_source,
        export_log_every=opts.export_log_every,
        limit_docs=opts.limit_docs,
        chunk_docs=opts.chunk_docs,
        flush_unique_ngrams=opts.flush_unique_ngrams,
        reset=True,
        export_only=opts.export_only,
        export_after_count=opts.export_after_count,
        delete_only=opts.delete_only,
        compact_only=opts.compact_only,
        compact_n=opts.compact_n,
        compact_after_count=opts.compact_after_count,
        policy=opts.policy,
    )
    reset = collect_counts(reset_opts, db_path)

    assert doubled[("la", "casa")] == 2
    assert reset[("la", "casa")] == 1


def test_partial_count_rows_are_aggregated(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    repository = DuckDbNgramCountRepository(db_path)

    repository.add_counts(
        Counter({("la", "casa"): 2}),
        lang="es",
        corpus="test",
        fold_nasal_letters=False,
    )
    repository.add_counts(
        Counter({("la", "casa"): 3}),
        lang="es",
        corpus="test",
        fold_nasal_letters=False,
    )

    rows = list(repository.iter_counts(lang="es", corpus="test", min_count=1))
    repository.close()

    assert len(rows) == 1
    assert rows[0].tokens == ("la", "casa")
    assert rows[0].count == 5


def test_export_tsv_respects_max_results(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    output = tmp_path / "ngrams.tsv"
    repository = DuckDbNgramCountRepository(db_path)
    repository.add_counts(
        Counter({("la", "casa"): 10, ("el", "camino"): 8}),
        lang="es",
        corpus="test",
        fold_nasal_letters=False,
    )

    opts = ExtractNgramsCommand(
        input_path=None,
        output_path=output,
        corpus="test",
        input_format="txt",
        text_field="text",
        min_count=1,
        max_results=1,
        export_n=0,
        min_export_norm_len=0,
        max_export_norm_len=0,
        export_source="auto",
        export_log_every=0,
        limit_docs=0,
        chunk_docs=1000,
        flush_unique_ngrams=250_000,
        reset=False,
        export_only=True,
        export_after_count=True,
        delete_only=False,
        compact_only=False,
        compact_n=0,
        compact_after_count=True,
        policy=NgramExtractionPolicy(lang="es", max_n=2),
    )
    exported = export_tsv(opts, repository)
    repository.close()

    with output.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    assert exported == 1
    assert rows[0]["text"] == "la casa"


def test_export_tsv_can_filter_by_n_and_norm_length(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    output = tmp_path / "ngrams.tsv"
    repository = DuckDbNgramCountRepository(db_path)
    repository.add_counts(
        Counter(
            {
                ("casa",): 10,
                ("la", "casa"): 9,
                ("el", "largo", "camino"): 8,
            }
        ),
        lang="es",
        corpus="test",
        fold_nasal_letters=False,
    )

    opts = ExtractNgramsCommand(
        input_path=None,
        output_path=output,
        corpus="test",
        input_format="txt",
        text_field="text",
        min_count=1,
        max_results=0,
        export_n=2,
        min_export_norm_len=5,
        max_export_norm_len=8,
        export_source="auto",
        export_log_every=0,
        limit_docs=0,
        chunk_docs=1000,
        flush_unique_ngrams=250_000,
        reset=False,
        export_only=True,
        export_after_count=True,
        delete_only=False,
        compact_only=False,
        compact_n=0,
        compact_after_count=True,
        policy=NgramExtractionPolicy(lang="es", max_n=3),
    )
    exported = export_tsv(opts, repository)
    repository.close()

    with output.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    assert exported == 1
    assert rows[0]["text"] == "la casa"


def test_compacted_counts_can_be_used_for_export(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    output = tmp_path / "ngrams.tsv"
    repository = DuckDbNgramCountRepository(db_path)
    repository.add_counts(
        Counter({("la", "casa"): 2}),
        lang="es",
        corpus="test",
        fold_nasal_letters=False,
    )
    repository.add_counts(
        Counter({("la", "casa"): 3, ("casa",): 7}),
        lang="es",
        corpus="test",
        fold_nasal_letters=False,
    )

    compacted = repository.compact_counts(lang="es", corpus="test", n=2)

    opts = ExtractNgramsCommand(
        input_path=None,
        output_path=output,
        corpus="test",
        input_format="txt",
        text_field="text",
        min_count=1,
        max_results=0,
        export_n=2,
        min_export_norm_len=0,
        max_export_norm_len=0,
        export_source="auto",
        export_log_every=0,
        limit_docs=0,
        chunk_docs=1000,
        flush_unique_ngrams=250_000,
        reset=False,
        export_only=True,
        export_after_count=True,
        delete_only=False,
        compact_only=False,
        compact_n=0,
        compact_after_count=True,
        policy=NgramExtractionPolicy(lang="es", max_n=2),
    )
    exported = export_tsv(opts, repository)
    repository.close()

    with output.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    assert compacted == 1
    assert exported == 1
    assert rows[0]["text"] == "la casa"
    assert rows[0]["count"] == "5"


def test_adding_raw_counts_invalidates_stale_compaction(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    repository = DuckDbNgramCountRepository(db_path)
    repository.add_counts(
        Counter({("casa",): 2}),
        lang="es",
        corpus="test",
        fold_nasal_letters=False,
    )
    repository.compact_counts(lang="es", corpus="test", n=1)

    repository.add_counts(
        Counter({("casa",): 3}),
        lang="es",
        corpus="test",
        fold_nasal_letters=False,
    )
    stats = repository.stats(lang="es", corpus="test")
    rows = list(repository.iter_counts(lang="es", corpus="test", min_count=1))
    repository.close()

    assert stats["compacted"] == []
    assert stats["totals_by_n"] == []
    assert rows[0].text == "casa"
    assert rows[0].count == 5


def test_delete_only_removes_lang_corpus_storage(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    repository = DuckDbNgramCountRepository(db_path)
    repository.add_counts(
        Counter({("casa",): 2}),
        lang="es",
        corpus="test",
        fold_nasal_letters=False,
    )
    repository.compact_counts(lang="es", corpus="test", n=1)
    repository.add_counts(
        Counter({("house",): 4}),
        lang="en",
        corpus="test",
        fold_nasal_letters=False,
    )
    repository.close()

    opts = replace(
        build_options(tmp_path / "unused.txt", tmp_path / "unused.tsv", "es"),
        delete_only=True,
    )
    deleted = run_extraction(opts, DuckDbNgramCountRepository(db_path))

    repository = DuckDbNgramCountRepository(db_path)
    es_stats = repository.stats(lang="es", corpus="test")
    en_rows = list(
        repository.iter_counts(lang="en", corpus="test", min_count=1)
    )
    repository.close()

    assert deleted == 3
    assert es_stats["by_lang_corpus"] == []
    assert es_stats["totals_by_n"] == []
    assert es_stats["compacted"] == []
    assert len(en_rows) == 1
    assert en_rows[0].text == "house"


def test_stats_include_filtered_table_counts(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    repository = DuckDbNgramCountRepository(db_path)
    repository.add_counts(
        Counter({("casa",): 2}),
        lang="es",
        corpus="test",
        fold_nasal_letters=False,
    )
    repository.compact_counts(lang="es", corpus="test", n=1)
    repository.add_counts(
        Counter({("house",): 4}),
        lang="en",
        corpus="test",
        fold_nasal_letters=False,
    )

    stats = repository.stats(lang="fr", corpus="test")
    global_counts = dict(repository.stats()["table_counts"])
    filtered_counts = dict(stats["filtered_table_counts"])
    repository.close()

    assert filtered_counts == {
        "ngram_compactions": 0,
        "ngram_counts": 0,
        "ngram_totals": 0,
    }
    assert global_counts["ngram_counts"] == 2
    assert global_counts["ngram_totals"] == 1
    assert global_counts["ngram_compactions"] == 1


def test_export_auto_uses_complete_compaction_for_all_n(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    repository = DuckDbNgramCountRepository(db_path)
    repository.add_counts(
        Counter({("casa",): 2, ("la", "casa"): 3}),
        lang="es",
        corpus="test",
        fold_nasal_letters=False,
    )
    repository.compact_counts(lang="es", corpus="test", n=1)
    repository.compact_counts(lang="es", corpus="test", n=2)

    table = repository._select_counts_table(
        lang="es",
        corpus="test",
        export_n=0,
        source="auto",
    )
    repository.close()

    assert table == "ngram_totals"


def test_run_extraction_compacts_after_count(tmp_path):
    corpus = tmp_path / "corpus.txt"
    output = tmp_path / "ngrams.tsv"
    db_path = tmp_path / "ngrams.duckdb"
    corpus.write_text("La casa. La casa.\n", encoding="utf-8")

    opts = build_options(corpus, output, "es")
    repository = DuckDbNgramCountRepository(db_path)

    exported = run_extraction(opts, repository)

    repository = DuckDbNgramCountRepository(db_path)
    stats = repository.stats(lang="es", corpus="test")
    repository.close()

    compacted_n = {row[2] for row in stats["compacted"]}

    assert exported > 0
    assert compacted_n == {1, 2}


def test_compact_all_counts_runs_progressively(tmp_path):
    db_path = tmp_path / "ngrams.duckdb"
    repository = DuckDbNgramCountRepository(db_path)
    repository.add_counts(
        Counter({("casa",): 2, ("la", "casa"): 3, ("la", "casa", "azul"): 4}),
        lang="es",
        corpus="test",
        fold_nasal_letters=False,
    )

    opts = ExtractNgramsCommand(
        input_path=None,
        output_path=tmp_path / "ngrams.tsv",
        corpus="test",
        input_format="txt",
        text_field="text",
        min_count=1,
        max_results=0,
        export_n=0,
        min_export_norm_len=0,
        max_export_norm_len=0,
        export_source="auto",
        export_log_every=0,
        limit_docs=0,
        chunk_docs=1000,
        flush_unique_ngrams=250_000,
        reset=False,
        export_only=False,
        export_after_count=False,
        delete_only=False,
        compact_only=True,
        compact_n=0,
        compact_after_count=True,
        policy=NgramExtractionPolicy(lang="es", max_n=3),
    )

    compacted = compact_all_counts(opts, repository)
    stats = repository.stats(lang="es", corpus="test")
    repository.close()

    compacted_n = {row[2] for row in stats["compacted"]}

    assert compacted == 3
    assert compacted_n == {1, 2, 3}
