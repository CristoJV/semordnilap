from semordnilap.review.application import (
    build_detail_markdown,
    filter_rows,
    rows_to_table,
)
from semordnilap.review.cli.gradio_app import load_rows, resolve_uploaded_path
from semordnilap.review.domain import ReviewFilters, ReviewRow
from semordnilap.review.infrastructure import TsvReviewRepository


def sample_row(**overrides):
    values = {
        "source_text": "roda",
        "target_text": "a dor",
        "pair_score": 4.2,
        "source_count": 5,
        "target_count": 7,
        "source_n": 1,
        "target_n": 2,
        "source_norm_key": "roda",
        "target_norm_key": "ador",
        "source_lang": "es",
        "target_lang": "pt",
        "source_corpus": "wiki",
        "target_corpus": "wiki",
    }
    values.update(overrides)
    return ReviewRow(**values)


def test_review_filters_match_text_score_counts_and_n():
    rows = [
        sample_row(),
        sample_row(
            source_text="casa",
            target_text="mesa",
            pair_score=1.0,
            source_count=20,
            target_count=20,
            source_n=1,
            target_n=1,
        ),
    ]

    filtered = filter_rows(
        rows,
        ReviewFilters(
            source_contains="rod",
            target_contains="dor",
            min_pair_score=2.0,
            min_source_count=5,
            min_target_count=7,
            source_n=1,
            target_n=2,
        ),
    )

    assert filtered == [rows[0]]


def test_rows_to_table_uses_expected_order():
    table = rows_to_table([sample_row()])

    assert table[0][:5] == ["roda", "a dor", 4.2, 5, 7]


def test_detail_markdown_shows_reverse_check():
    detail = build_detail_markdown(sample_row())

    assert "roda ⇄ a dor" in detail
    assert "reverse(roda) = ador" in detail
    assert "match" in detail


def test_tsv_repository_loads_search_export(tmp_path):
    path = tmp_path / "pairs.tsv"
    path.write_text(
        "\t".join(
            [
                "source_lang",
                "source_corpus",
                "source_text",
                "source_n",
                "source_count",
                "source_norm_key",
                "target_lang",
                "target_corpus",
                "target_text",
                "target_n",
                "target_count",
                "target_norm_key",
                "pair_score",
            ]
        )
        + "\n"
        + "\t".join(
            [
                "es",
                "wiki",
                "roda",
                "1",
                "5",
                "roda",
                "pt",
                "wiki",
                "a dor",
                "2",
                "7",
                "ador",
                "4.2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = TsvReviewRepository().load(path)

    assert rows == [sample_row()]


def test_review_load_rows_rejects_directories(tmp_path):
    rows, message = load_rows(str(tmp_path))

    assert rows == []
    assert "Not a file" in message


def test_resolve_uploaded_path_accepts_gradio_file_shapes():
    assert resolve_uploaded_path("/tmp/pairs.tsv") == "/tmp/pairs.tsv"
    assert resolve_uploaded_path({"path": "/tmp/pairs.tsv"}) == "/tmp/pairs.tsv"
