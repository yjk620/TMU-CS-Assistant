from eval.grade import build_rows, count_grades

QUESTIONS = [
    {"id": 1, "type": "lookup", "question": "q1", "expected_sources": ["u1"], "answerable": True},
    {"id": 2, "type": "unanswerable", "question": "q2", "answerable": False},
]
REFUSAL = "I don't know - check with your program advisor."


def answers(a1, a2):
    return [{"id": 1, "answer": a1}, {"id": 2, "answer": a2}]


def test_identical_answers_appear_once():
    rows, key = build_rows(QUESTIONS, {
        "v1": answers("A", REFUSAL),
        "v2": answers("A", REFUSAL),
        "v3": answers("B", REFUSAL),
    })
    assert len(rows) == 3
    by_answer = {(r["question_id"], r["answer"]): key[str(r["row"])] for r in rows}
    assert by_answer[(1, "A")] == ["v1", "v2"]
    assert by_answer[(1, "B")] == ["v3"]
    assert by_answer[(2, REFUSAL)] == ["v1", "v2", "v3"]


def test_refusals_pre_graded():
    rows, _ = build_rows(QUESTIONS, {"v1": answers(REFUSAL, REFUSAL)})
    grades = {r["question_id"]: (r["grade"], r["note"]) for r in rows}
    assert grades[1] == ("wrong", "auto")
    assert grades[2] == ("right", "auto")


def test_count_grades_credits_every_version_of_a_row():
    rows = [
        {"row": "1", "type": "lookup", "grade": "right"},
        {"row": "2", "type": "lookup", "grade": "partly"},
    ]
    counts = count_grades(rows, {"1": ["v1", "v2"], "2": ["v3"]})
    assert counts["v1"]["lookup"] == {"right": 1, "partly": 0, "wrong": 0}
    assert counts["v2"]["lookup"]["right"] == 1
    assert counts["v3"]["lookup"]["partly"] == 1
