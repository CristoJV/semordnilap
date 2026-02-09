import pytest

from semordnilap.app.logic.filtering import should_filter_ngram_fast


@pytest.mark.parametrize(
    "ngram,filters",
    [
        ("a b", {"a"}),  # single token
        ("a b c", {"a b"}),  # multi-token-contiguous
        ("a", {"a"}),  # exact match
        ("a b c d", {"b", "c d"}),  # multiple possible matches
    ],
)
def test_should_filter_ngram_fast_positive_cases(ngram, filters):
    assert should_filter_ngram_fast(ngram, filters) is True


@pytest.mark.parametrize(
    "ngram,filters",
    [
        ("a b c", {"a c"}),  # non-contiguous
        ("a", {"b"}),  # no overlap
        ("a b", set()),  # empty filters
        ("", {"a"}),  # empty ngram
        ("a b c", {"b a"}),
    ],
)
def test_should_filter_ngram_fast_negative_cases(ngram, filters):
    assert should_filter_ngram_fast(ngram, filters) is False


def test_should_filter_ngram_fast_is_case_sensitive():
    assert should_filter_ngram_fast("A b", {"a"}) is False
