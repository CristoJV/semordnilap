import csv

import pytest

from semordnilap.search.cli.concat_pairs import concat_pair_tsvs


FIELDS = ["pair_id", "lexical_pair_id", "source_text", "target_text"]


def write_pairs(path, rows, *, fields=FIELDS):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def test_concat_pair_tsvs_writes_one_header(tmp_path):
    first = tmp_path / "first.tsv"
    second = tmp_path / "second.tsv"
    output = tmp_path / "combined.tsv"
    write_pairs(
        first,
        [
            {
                "pair_id": "pair:1",
                "lexical_pair_id": "lexical:1",
                "source_text": "roda",
                "target_text": "a dor",
            }
        ],
    )
    write_pairs(
        second,
        [
            {
                "pair_id": "pair:2",
                "lexical_pair_id": "lexical:1",
                "source_text": "roda",
                "target_text": "a dor",
            }
        ],
    )

    rows_written = concat_pair_tsvs([first, second], output)

    with output.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        rows = list(reader)
    assert rows_written == 2
    assert reader.fieldnames == FIELDS
    assert [row["pair_id"] for row in rows] == ["pair:1", "pair:2"]


def test_concat_pair_tsvs_rejects_different_headers_atomically(tmp_path):
    first = tmp_path / "first.tsv"
    second = tmp_path / "second.tsv"
    output = tmp_path / "combined.tsv"
    write_pairs(first, [])
    write_pairs(second, [], fields=[*FIELDS, "pair_score"])
    output.write_text("previous\n", encoding="utf-8")

    with pytest.raises(ValueError, match="header does not match"):
        concat_pair_tsvs([first, second], output)

    assert output.read_text(encoding="utf-8") == "previous\n"


def test_concat_pair_tsvs_rejects_output_as_input(tmp_path):
    pairs = tmp_path / "pairs.tsv"
    write_pairs(pairs, [])

    with pytest.raises(ValueError, match="cannot also be an input"):
        concat_pair_tsvs([pairs], pairs)
