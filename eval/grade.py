# blind grading of the v1, v2 and v3 answers
#   python -m eval.grade sheet    writes eval/grading/sheet.csv (versions hidden) and key.json
#   python -m eval.grade reveal   after grading: counts right / partly / wrong per version
# identical answers to the same question appear once; rows are shuffled so row order says nothing
# refusal-sentence answers are pre-graded (right if the question is unanswerable, wrong otherwise),
# marked "auto" in the note column; change them if you disagree

import argparse
import csv
import json
import random
import sys
from collections import defaultdict

from app.text import is_refusal
from eval.run import EVAL_DIR, RESULTS, TYPES, load_questions

VERSIONS = ["v1", "v2", "v3"]
GRADING = EVAL_DIR / "grading"
SHEET = GRADING / "sheet.csv"
KEY = GRADING / "key.json"
GRADES = ["right", "partly", "wrong"]
COLUMNS = ["row", "question_id", "type", "question", "expected_sources", "answer", "grade", "note"]


def load_answers(version):
    with open(RESULTS / f"{version}.jsonl") as f:
        return [json.loads(line) for line in f if line.strip()]


#one row per distinct (question, answer); key: row -> the versions that gave that answer
def build_rows(questions, answers_by_version):
    by_question = {q["id"]: q for q in questions}
    versions_of = defaultdict(list)
    for version, answers in answers_by_version.items():
        for a in answers:
            versions_of[(a["id"], a["answer"].strip())].append(version)

    items = list(versions_of.items())
    random.shuffle(items)
    rows, key = [], {}
    for number, ((question_id, answer), versions) in enumerate(items, 1):
        q = by_question[question_id]
        grade, note = "", ""
        if is_refusal(answer):
            grade, note = ("wrong" if q["answerable"] else "right"), "auto"
        rows.append({
            "row": number,
            "question_id": question_id,
            "type": q["type"],
            "question": q["question"],
            "expected_sources": " ".join(q.get("expected_sources", [])),
            "answer": answer,
            "grade": grade,
            "note": note,
        })
        key[str(number)] = versions
    return rows, key


def write_sheet():
    if SHEET.exists():
        sys.exit(f"{SHEET} exists; delete it first (grades in it would be lost)")
    answers = {v: load_answers(v) for v in VERSIONS}
    rows, key = build_rows(load_questions(), answers)
    GRADING.mkdir(exist_ok=True)
    with open(SHEET, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    KEY.write_text(json.dumps(key, indent=2) + "\n")
    auto = sum(r["note"] == "auto" for r in rows)
    print(f"{len(rows)} rows ({auto} refusals pre-graded, {len(rows) - auto} to grade) -> {SHEET}")


#counts per version and type, e.g. {"v1": {"lookup": {"right": 7, "partly": 1, "wrong": 2}, ...}}
def count_grades(rows, key):
    counts = {v: {t: dict.fromkeys(GRADES, 0) for t in TYPES} for v in VERSIONS}
    for row in rows:
        for version in key[row["row"]]:
            counts[version][row["type"]][row["grade"]] += 1
    return counts


def reveal():
    with open(SHEET, newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["grade"] = row["grade"].strip().lower()
    bad = [r["row"] for r in rows if r["grade"] not in GRADES]
    if bad:
        sys.exit(f"rows not graded right/partly/wrong: {', '.join(bad)}")

    counts = count_grades(rows, json.loads(KEY.read_text()))
    (RESULTS / "graded_summary.json").write_text(json.dumps(counts, indent=2) + "\n")

    print(f"{'type':<13}" + "".join(f"{v + ' right/partly/wrong':>24}" for v in VERSIONS))
    for t in TYPES + ["total"]:
        cells = []
        for v in VERSIONS:
            c = counts[v][t] if t != "total" else {g: sum(counts[v][x][g] for x in TYPES) for g in GRADES}
            cells.append(f"{c['right']}/{c['partly']}/{c['wrong']}")
        print(f"{t:<13}" + "".join(f"{cell:>24}" for cell in cells))


def main():
    parser = argparse.ArgumentParser(description="Blind grading of the eval answers")
    parser.add_argument("command", choices=["sheet", "reveal"])
    args = parser.parse_args()
    write_sheet() if args.command == "sheet" else reveal()


if __name__ == "__main__":
    main()
