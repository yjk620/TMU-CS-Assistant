import pytest

from app.retrieve import code_tokens, expand_with_prereqs, join_codes, rrf


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

# ranking 1..10; chunk 1 is CPS 803 (prereqs MTH 108, CPS 305, MTH 380), chunk 2 is CPS 305 (prereq CPS 209)
PREREQS = {1: ["MTH 108", "CPS 305", "MTH 380"], 2: ["CPS 209"]}
CHUNKS = {"MTH 108": 50, "CPS 305": 2, "MTH 380": 51, "CPS 209": 52}


def test_v3_adds_prereqs_after_top_k_minus_3():
    # top 5 = 1..5; MTH 108 -> 50, CPS 305 already selected (chunk 2) so skipped, MTH 380 -> 51, then CPS 209 -> 52
    assert expand_with_prereqs(list(range(1, 11)), 8, PREREQS, CHUNKS) == [1, 2, 3, 4, 5, 50, 51, 52]


def test_v3_with_semester_slot_uses_top_k_minus_3_of_7():
    # k = 7 (slot 1 taken by the semester chunk 99): top 4, then up to 3 prerequisites
    assert expand_with_prereqs(list(range(1, 11)), 7, PREREQS, CHUNKS, exclude=[99]) == [1, 2, 3, 4, 50, 51, 52]


def test_v3_skips_codes_without_a_course_page_and_fills_from_next_ranks():
    prereqs = {1: ["CCPS 109", "MTH 108"]}  # CCPS 109 has no course page
    assert expand_with_prereqs(list(range(1, 11)), 8, prereqs, {"MTH 108": 50}) == [1, 2, 3, 4, 5, 50, 6, 7]


def test_v3_skips_excluded_and_duplicate_prereqs():
    prereqs = {1: ["CPS 209"], 2: ["CPS 209", "MTH 110"]}
    chunks = {"CPS 209": 99, "MTH 110": 60}  # 99 is the semester-slot chunk
    assert expand_with_prereqs(list(range(1, 11)), 7, prereqs, chunks, exclude=[99]) == [1, 2, 3, 4, 60, 5, 6]


def test_v3_without_course_chunks_equals_v2():
    assert expand_with_prereqs(list(range(1, 11)), 8, {}, {}) == list(range(1, 9))
