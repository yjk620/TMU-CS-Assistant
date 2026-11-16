# TMU CS Assistant

A question-answering assistant for Toronto Metropolitan University Computer Science students. It answers questions about program requirements, electives, courses, prerequisites, deadlines and academic policies, using the 2026–27 Undergraduate Calendar and the CS department's curriculum page.

- Every answer cites the pages it came from.
- It answers "I don't know - check with your program advisor." when those pages don't answer the question.
- Retrieval quality is measured on a hand-labelled 40-question test set, across three retriever versions.

> Not official academic advice. Confirm with your program advisor.

## Example questions

- What do I take in 3rd semester?
- What do I need before CPS 616?
- Can CS students take PCS 111 as a liberal studies course?
- When is the Winter 2027 exam period?

## The problem

The answers students need are spread across hundreds of calendar pages: a course page for each prerequisite, separate liberal-studies tables with program-specific restrictions, a significant-dates table and policy pages. A question like "I've done CPS 209 and MTH 110, what else do I need before CPS 633?" needs several of those pages at once. This assistant finds the right pages and answers only from them.

## Architecture

```
scrape.py  ──>  documents, courses        (604 pages: 596 course pages, curriculum, dates, tables, policies)
ingest.py  ──>  chunks + embeddings       (983 chunks, Voyage voyage-4-lite, 1024 dims, in Neon Postgres + pgvector)
/ask       ──>  retrieve 8 chunks ──> Claude (claude-haiku-5-5) answers only from them ──> logged in queries
```

- **Scraping** (`app/scrape.py`): a polite crawler (generic User-Agent, 1 s delay) stores the fixed pages, then follows course links and each course's prerequisite codes. Prerequisite codes are parsed from the Prerequisites field only.
- **Chunking** (`app/ingest.py`): one chunk per course (description, weekly contact, GPA weight, all requisites), one per significant-date row, one per policy section, one per curriculum semester and format (four-year, part-time, co-op), and elective tables in balanced groups of about 40 courses. Chunks are re-embedded only when their content hash changes.
- **Retrieval** (`app/retrieve.py`): always 8 chunks. A question naming a semester ("3rd semester", "part-time semester 2") gets that curriculum chunk in slot 1; the retriever fills the rest.
- **Answering** (`app/main.py`): the system prompt restricts Claude to the excerpts, requires cited URLs, follows prerequisite and/or rules exactly, and returns a fixed refusal sentence for other programs, other calendar years, instructors, rooms and grades.

**Why no framework:** the pipeline is a handful of SQL queries and one API call. Writing it directly keeps every step visible and testable (the RRF merge and the v3 expansion are pure functions with unit tests), and makes the three retriever versions easy to compare on the same corpus.

### Retriever versions

| Version | How the chunks are chosen | Problem it targets |
|---|---|---|
| **v1** | Vector search (cosine distance) | Baseline |
| **v2** | Reciprocal Rank Fusion of vector search (top 20) and full-text search (top 20) | Course codes like "CPS 803" match badly on embeddings |
| **v3** | v2's top 5, plus up to 3 prerequisite-course chunks of the courses in it, then v2's next ranks | "Can I take X if I've done Y?" needs more than one course page |

Full-text search ORs the question's words (Postgres's default AND matched nothing on natural questions), and ranks chunks containing one of the question's course codes first, because `ts_rank` doesn't weigh rare words above common ones.

## Results

40 questions, written before v2 was built (see the commit history). All three versions ran on the same frozen corpus (983 chunks, fingerprint `2584e0ec899f6856`) with the same question embeddings. Counts, not percentages: the groups are small.

**Answer correctness** (right / partly / wrong):

| Type | Questions | v1 | v2 | v3 |
|---|---|---|---|---|
| lookup | 10 | 9 / 0 / 1 | 9 / 0 / 1 | **10 / 0 / 0** |
| program | 6 | 6 / 0 / 0 | 6 / 0 / 0 | 6 / 0 / 0 |
| elective | 4 | 4 / 0 / 0 | 4 / 0 / 0 | 4 / 0 / 0 |
| prereq_chain | 10 | 1 / 4 / 5 | 2 / 4 / 4 | **8 / 1 / 1** |
| date_policy | 5 | 4 / 1 / 0 | 4 / 1 / 0 | 4 / 1 / 0 |
| unanswerable | 5 | 5 / 0 / 0 | 5 / 0 / 0 | 5 / 0 / 0 |
| **total** | **40** | **29 / 5 / 6** | **30 / 5 / 5** | **37 / 2 / 1** |

**Source recall** (the expected page was retrieved; for prerequisite chains, all expected pages):

| Type | v1 | v2 | v3 |
|---|---|---|---|
| lookup | 9/10 | 9/10 | 10/10 |
| program | 6/6 | 6/6 | 6/6 |
| elective | 4/4 | 4/4 | 4/4 |
| prereq_chain | 0/10 | 1/10 | 6/10 |
| date_policy | 5/5 | 5/5 | 5/5 |

**Refusal accuracy** (refuses unanswerable questions, answers the rest): v1 34/40, v2 35/40, v3 39/40. All three refused all 5 unanswerable questions; the other misses were refusals on answerable questions whose pages weren't retrieved.

**How it was graded:** `eval/grade.py sheet` writes one CSV of all 120 answers, shuffled, with versions hidden; identical answers to the same question appear once (104 rows). Answers that are exactly the refusal sentence are pre-graded mechanically. `eval/grade.py reveal` maps the grades back to versions. See `eval/grading/sheet.csv` for every grade and its note.

### What still fails

- **Q26, "I've only done CPS 209. What do I still need before CPS 616?"** All three versions refuse. CPS 616 needs `(CPS 305 and MTH 210) or (CPS 305 and CPS 420)`, and CPS 420 itself needs CPS 305. Retrieval found CPS 616's page but not enough of the chain, so Claude correctly declined to guess. v3 only follows *direct* prerequisites of the top-ranked chunks.
- **Q24, "I've done CPS 209 and MTH 110. What else do I need before CPS 633?"** v3 answers "CPS 420" but can't add that CPS 420 needs CPS 305: a two-level chain again (CPS 633 → CPS 420 → CPS 305).
- **Q35, "How do I withdraw from a course?"** All versions get the how-to right but say Nov 20, 2026 is only a *program* withdrawal deadline. It is also the last day to drop a Fall course. The question says "withdraw"; the calendar row for courses says "drop", so retrieval fetched five program-withdrawal date rows and missed the course one.
- **Q9, "What is the GPA weight of CPS 406?"** (fixed only by v3). Eight course chunks contain "CPS 406", because other courses list it as a prerequisite, and every course chunk contains "GPA Weight", so CPS 406's own page ranked 5th in full-text search and v2 missed it. v3 reached it through CPS 714's and CPS 707's prerequisites.

## How AI was used

Built with Claude Code over a few days. The spec, roadmap and the 40 evaluation questions were written by Kevin; Claude reviewed the spec over several rounds and wrote much of the ingest, retrieval and evaluation code on request, one committed step at a time, with each step explained before it was built.

Problems found by inspecting real output rather than trusting the code:
- Accordion titles leaked into the semester chunks (the curriculum page uses `h3.panel-title`, not `h2`).
- The Table B restrictions chunk kept other faculties' rules, because one panel is titled "The Creative School"; faculty panels are now detected by their markup.
- The first full ingest crashed after 15 minutes: Neon closed the database connection held idle while Voyage rate-limited the embedding calls. Embedding now runs with no connection open.
- The v1 eval showed 5 lookup questions couldn't be answered at all, because course chunks lacked weekly contact hours, GPA weight and antirequisites. The chunks were extended and re-ingested before v2 was built.
- An AND-based full-text query matched zero chunks for natural questions; the OR + code-first design was tuned on questions outside the test set to avoid fitting the eval.

<!-- TODO(Kevin): add in your own words what you wrote yourself, what Claude got wrong, and how you caught it. -->

**Grading disclosure:** the 91 non-refusal answers were graded by Claude (Opus 5.5) against the stored calendar text, blind to version, using the right/partly/wrong rules above; the grades and reasons are in `eval/grading/sheet.csv`. <!-- TODO(Kevin): after spot-checking the sheet, change this to say you reviewed the grades (or re-grade and run `python -m eval.grade reveal`). -->

## Limits

- Computer Science only, 2026–27 calendar only.
- Course discovery is link-based: the CPS course index loads with JavaScript, so a course reachable only from there isn't found.
- Course codes with a letter in the number (e.g. `CPS 40A`) aren't matched in questions.
- Only 2 policy pages are stored.
- v3 follows only direct prerequisites, at most 3.
- Small test set: 40 questions, mostly self-written, no held-out split.
- Rate limiting is in memory, per process.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # fill in DATABASE_URL, VOYAGE_API_KEY, ANTHROPIC_API_KEY
psql "$DATABASE_URL" -f schema.sql
python -m app.scrape              # crawl the calendar
python -m app.ingest              # chunk and embed
uvicorn app.main:app --reload     # chat page at http://localhost:8000
```

Ask from the command line: `python -m app.main "What do I need before CPS 721?" --retriever v3`

Evaluate: `python -m eval.run --retriever v3`, then `python -m eval.grade sheet` / `reveal`.

Tests: `python -m pytest tests`

## Deployment

`render.yaml` deploys the app as one Render web service with `RETRIEVER=v3`. Secrets are set in the Render dashboard. `/ask` allows 10 questions a minute per client IP (read from `X-Forwarded-For` behind Render's proxy), the Claude Console has a monthly spend cap, and the chat page says questions are logged.

## Room for improvement

- Follow prerequisite chains more than one level deep (fixes Q24 and Q26).
- Rank a course's own chunk first when the question names its code.
- Map "withdraw from a course" to the calendar's "drop" wording.
- Scrape Open Electives course pages and more policy pages.
- `sources` lists every retrieved page, not only the ones Claude cited.
- A larger test set with a held-out split, partly written by other students.
