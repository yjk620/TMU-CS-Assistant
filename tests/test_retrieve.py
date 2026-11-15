import pytest

from app.retrieve import code_tokens, join_codes, rrf


@pytest.mark.parametrize("text, expected", [
    ("What is CPS 803 about?", "What is CPS803 about?"),
    ("CCPS 109 and MTH 108", "CCPS109 and MTH108"),
    ("Fall 2026 and any 400-level course", "Fall 2026 and any 400-level course"),
])
def test_join_codes(text, expected):
    assert join_codes(text) == expected


@pytest.mark.parametrize("question, expected", [
    ("Can I take CPS 714 after CPS 406?", "cps714 | cps406"),
    ("Is CCPS 109 the same as CPS 109?", "ccps109 | cps109"),
    ("Is there a course about computer graphics?", ""),
])
def test_code_tokens(question, expected):
    assert code_tokens(question) == expected


def test_rrf_sums_scores_across_rankings():
    # 2 is ranked 2nd in both lists, so it beats 1 and 3, which each appear in only one list
    assert rrf([1, 2], [3, 2]) == [2, 1, 3]


def test_rrf_ties_keep_first_ranking_order():
    assert rrf([1, 2], [2, 1]) == [1, 2]


def test_rrf_single_ranking_keeps_order():
    assert rrf([5, 4, 3], []) == [5, 4, 3]
