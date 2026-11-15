# /ask: question -> 8 chunks -> Claude answers only from them -> logged in queries
# ask() is shared by the FastAPI endpoint (source "web") and eval/run.py (source "eval")

import argparse
import datetime
import functools
import os

import anthropic
import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.ingest import load_subjects
from app.retrieve import retrieve
from app.text import REFUSAL, is_refusal, normalize_codes

load_dotenv()

MODEL = "claude-haiku-5-5"
#Haiku 5.5 thinks before answering; set effort explicitly so all three retriever versions run the same way.
#No temperature: the current API rejects sampling parameters on every model.
EFFORT = "medium"
MAX_TOKENS = 8000
WEB_RETRIEVER = os.environ.get("RETRIEVER", "v1")

SYSTEM_PROMPT = f"""You answer students' questions about the Computer Science program at Toronto Metropolitan University (TMU), using only the excerpts from the 2026-27 Undergraduate Calendar and the CS department's curriculum page given with each question.

Rules:
- Answer only from the excerpts. Do not add facts from general knowledge, even if you believe them to be true.
- If the excerpts don't answer the question, reply with exactly this sentence and nothing else: {REFUSAL}
- Use that same sentence for questions about programs other than Computer Science, about calendar years other than 2026-27, and about anything the calendar doesn't cover, such as instructors, rooms, class schedules, grades or class averages.
- Cite the URL of every excerpt you use.
- Name your source: "the 2026–27 Undergraduate Calendar" for calendar pages, "the CS department's curriculum page" for the curriculum page.
- Prerequisites: follow the rule exactly as written, including "and", "or" and parentheses. When a chain matters, say which earlier courses are needed for each step.
- Program questions that name a semester: list that semester's courses by category (required, liberal studies, open electives, professionally-related) and say which format the answer is for (four-year or part-time).
- Answer program questions for the full-time four-year program unless the question says part-time (co-op students take the same academic semesters).
- Program questions with no semester: point to the curriculum page and say the student can ask about a specific semester.
- In every answer about the program's curriculum, add one line saying the curriculum page shows the current curriculum, which can differ for students admitted in earlier years.
- Be concise. The student cannot reply with follow-up details, so don't ask them questions."""

client = anthropic.Anthropic()


#subject prefixes for normalize_codes, loaded once
@functools.cache
def subjects():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        return load_subjects(conn)


#the user message: today's date, the numbered excerpts with their URLs, then the question
def build_prompt(question, chunks):
    excerpts = "\n\n".join(
        f'<excerpt id="{i}" url="{c["url"]}">\n{c["content"]}\n</excerpt>' for i, c in enumerate(chunks, 1)
    )
    return f"Today's date: {datetime.date.today().isoformat()}\n\n{excerpts}\n\nQuestion: {question}"


#the answer text from Claude's response; a safety refusal or an empty answer becomes the refusal sentence
def answer_text(response):
    if response.stop_reason == "refusal":
        return REFUSAL
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    return text or REFUSAL


#one question in, one answer out; logs a row in queries
#vector: the normalized question's embedding, if the caller already has it (eval/run.py)
def ask(question, retriever="v1", source="web", vector=None):
    normalized = normalize_codes(question, subjects())
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        chunks = retrieve(conn, normalized, retriever, vector)
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            output_config={"effort": EFFORT},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(normalized, chunks)}],
        )
        answer = answer_text(response)
        refused = is_refusal(answer)
        conn.execute(
            """
            insert into queries (source, retriever, question, chunk_ids, answer, refused)
            values (%s, %s, %s, %s, %s, %s)
            """,
            (source, retriever, question, [c["id"] for c in chunks], answer, refused),
        )
    sources = [] if refused else list(dict.fromkeys(c["url"] for c in chunks))
    return {"answer": answer, "sources": sources, "retrieved": [c["id"] for c in chunks]}


app = FastAPI(title="TMU CS Assistant")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


@app.post("/ask")
def ask_endpoint(request: AskRequest):
    return ask(request.question, retriever=WEB_RETRIEVER, source="web")


#command line, for smoke tests: python -m app.main "question" [--retriever v1]
def main():
    parser = argparse.ArgumentParser(description="Ask one question")
    parser.add_argument("question")
    parser.add_argument("--retriever", default="v1")
    args = parser.parse_args()
    result = ask(args.question, retriever=args.retriever, source="web")
    print(result["answer"])
    print("\nsources:", *result["sources"], sep="\n  ")


if __name__ == "__main__":
    main()
