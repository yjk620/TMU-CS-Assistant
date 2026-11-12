# TMU CS Assistant

A question-answering assistant for Toronto Metropolitan University Computer Science students. It answers questions about program requirements, electives, courses, prerequisites, deadlines and academic policies, using the 2026–27 Undergraduate Calendar and the CS department's curriculum page.

- Every answer cites the pages it came from.
- It says "I don't know" when those pages don't answer the question.
- Retrieval quality is measured on a hand-labelled test set.

> Work in progress. Not official academic advice — confirm with your program advisor.

## Example questions

- What courses do I need to take in 3rd semester?
- Which lower-level liberal studies courses can I take?
- What is CPS 803 about?
- Can I take CPS 803 if I've only done MTH 108?
- When is the last day to drop a Fall course?

## Stack

Python, FastAPI, PostgreSQL with pgvector (Neon), Voyage AI embeddings, Claude API.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
cp .env.example .env   # then fill in the keys
```
