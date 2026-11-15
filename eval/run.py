# runs the 40 questions in eval/questions.jsonl through one retriever version and scores them
#   python -m eval.run --retriever v1
# source recall and refusal accuracy are automatic; answers are saved for blind grading later
# writes eval/results/<version>.jsonl (one line per question) and <version>_summary.json (counts per type)

import argparse
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

import psycopg

from app import voyage
from app.main import ask, subjects
from app.retrieve import RETRIEVERS
from app.text import is_refusal, normalize_codes, normalize_url

EVAL_DIR = Path(__file__).parent
QUESTIONS = EVAL_DIR / "questions.jsonl"
RESULTS = EVAL_DIR / "results"
VECTOR_CACHE = EVAL_DIR / ".cache" / "question_vectors.json"
TYPES = ["lookup", "program", "elective", "prereq_chain", "date_policy", "unanswerable"]


def load_questions():
    with open(QUESTIONS) as f:
        return [json.loads(line) for line in f if line.strip()]


#embedding of each normalized question, computed once in one Voyage call and cached,
#so v1, v2 and v3 all search with exactly the same vectors
def question_vectors(texts):
    cache = json.loads(VECTOR_CACHE.read_text()) if VECTOR_CACHE.exists() else {}
    missing = [t for t in dict.fromkeys(texts) if t not in cache]
    if missing:
        cache.update(zip(missing, voyage.embed(missing, "query")))
        VECTOR_CACHE.parent.mkdir(exist_ok=True)
        VECTOR_CACHE.write_text(json.dumps(cache))
    return cache


#url, semester and format of each retrieved chunk, in rank order
def chunk_info(conn, ids):
    rows = conn.execute(
        """
        select c.id, d.url, c.semester, c.format
        from chunks c join documents d on d.id = c.document_id
        where c.id = any(%s)
        """,
        (ids,),
    ).fetchall()
    by_id = {r[0]: {"id": r[0], "url": normalize_url(r[1]), "semester": r[2], "format": r[3]} for r in rows}
    return [by_id[i] for i in ids]


#source recall for one question: True / False, or None for unanswerable questions (not scored)
def source_hit(question, chunks):
    if not question["answerable"]:
        return None
    chunk = question.get("expected_chunk")
    if chunk is not None:
        #program question: the chunk with exactly this semester and format (co-op semester null == None)
        return any(c["semester"] == chunk["semester"] and c["format"] == chunk["format"] for c in chunks)
    urls = {c["url"] for c in chunks}
    wanted = [normalize_url(u) for u in question["expected_sources"]]
    if question["type"] == "prereq_chain":
        return all(u in urls for u in wanted)
    return any(u in urls for u in wanted)


#a hash of every chunk's content_hash: identical only if the corpus is identical
def corpus_fingerprint(conn):
    hashes = [r[0] for r in conn.execute("select content_hash from chunks order by content_hash")]
    return hashlib.sha256("".join(hashes).encode()).hexdigest()[:16], len(hashes)


#warn if another version's results were produced on a different corpus
def check_frozen(fingerprint, version):
    for path in RESULTS.glob("*_summary.json"):
        other = json.loads(path.read_text())
        if other["retriever"] != version and other["corpus_fingerprint"] != fingerprint:
            print(f"WARNING: {other['retriever']} ran on a different corpus ({other['corpus_fingerprint']}). "
                  "Re-run all versions on the same corpus.")


#counts per type, e.g. {"lookup": {"source_recall": "7/10", "refusal_correct": "10/10"}}
def summarize(rows):
    by_type = defaultdict(list)
    for row in rows:
        by_type[row["type"]].append(row)
    summary = {}
    for t in TYPES:
        group = by_type.get(t, [])
        scored = [r for r in group if r["source_hit"] is not None]
        summary[t] = {
            "source_recall": f"{sum(r['source_hit'] for r in scored)}/{len(scored)}" if scored else "n/a",
            "refusal_correct": f"{sum(r['refusal_correct'] for r in group)}/{len(group)}",
        }
    return summary


def main():
    parser = argparse.ArgumentParser(description="Run the evaluation questions through one retriever")
    parser.add_argument("--retriever", required=True, choices=sorted(RETRIEVERS))
    parser.add_argument("--ingest-seconds", type=float, help="time of the last full ingest, recorded with the results")
    args = parser.parse_args()

    questions = load_questions()
    normalized = [normalize_codes(q["question"], subjects()) for q in questions]
    vectors = question_vectors(normalized)

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        fingerprint, chunk_count = corpus_fingerprint(conn)
        check_frozen(fingerprint, args.retriever)

        rows = []
        for q, text in zip(questions, normalized):
            result = ask(q["question"], retriever=args.retriever, source="eval", vector=vectors[text])
            chunks = chunk_info(conn, result["retrieved"])
            refused = is_refusal(result["answer"])
            row = {
                "id": q["id"],
                "type": q["type"],
                "question": q["question"],
                "answer": result["answer"],
                "retrieved": chunks,
                "source_hit": source_hit(q, chunks),
                "refused": refused,
                "refusal_correct": refused == (not q["answerable"]),
            }
            rows.append(row)
            print(f"{q['id']:>2} {q['type']:<13} source={row['source_hit']!s:<5} refused={refused!s:<5} {q['question'][:60]}")

    RESULTS.mkdir(exist_ok=True)
    with open(RESULTS / f"{args.retriever}.jsonl", "w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {
        "retriever": args.retriever,
        "questions": len(rows),
        "chunk_count": chunk_count,
        "corpus_fingerprint": fingerprint,
        "ingest_seconds": args.ingest_seconds,
        "by_type": summarize(rows),
    }
    (RESULTS / f"{args.retriever}_summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    print(f"\n{args.retriever}: {chunk_count} chunks, corpus {fingerprint}")
    print(f"{'type':<13} {'source recall':>14} {'refusal correct':>16}")
    for t, counts in summary["by_type"].items():
        print(f"{t:<13} {counts['source_recall']:>14} {counts['refusal_correct']:>16}")


if __name__ == "__main__":
    main()
