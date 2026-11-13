# turns stored pages (documents) into chunks for search
# 1. parse each document by its kind into chunk texts
# 2. rewrite course codes to the stored form (CPS 803)
# 3. (step 4) replace the document's chunks, reusing embeddings when content_hash matches
# 4. (step 5) embed new chunks with Voyage in batches

import argparse
import os

import psycopg
from dotenv import load_dotenv

from app.scrape import page_parser
from app.text import normalize_codes, normalize_url


#every subject prefix in courses (CPS, MTH, ...) plus CCPS, which has no course pages
def load_subjects(conn):
    rows = conn.execute("select distinct split_part(code, ' ', 1) from courses").fetchall()
    return {row[0] for row in rows} | {"CCPS"}


#one chunk dict; semester and format are only set on program chunks
def chunk(content, semester=None, format=None):
    return {"content": content, "semester": semester, "format": format}


#course page: one chunk with code, title, description and prerequisites
def course_chunks(html, url):
    course = page_parser(html, url)
    parts = [f"{course['code']} {course['title']}."]
    if course["description"]:
        parts.append(course["description"])
    if course["prereq_text"]:
        parts.append(f"Prerequisites: {course['prereq_text']}")
    return [chunk(" ".join(parts))]


#kind -> function that turns that kind of page into chunks
CHUNKERS = {
    "course": course_chunks,
}


#all chunks for one stored document, with course codes normalized
def document_chunks(conn, url, subjects):
    row = conn.execute("select kind, html from documents where url = %s", (url,)).fetchone()
    if row is None:
        raise ValueError(f"not in documents: {url}")
    kind, html = row
    chunks = CHUNKERS[kind](html, url)
    for c in chunks:
        c["content"] = normalize_codes(c["content"], subjects)
    return chunks


def main():
    parser = argparse.ArgumentParser(description="Turn stored pages into chunks")
    parser.add_argument("--show", help="print one stored page's chunks without saving")
    args = parser.parse_args()

    load_dotenv()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        subjects = load_subjects(conn)
        if args.show:
            for c in document_chunks(conn, normalize_url(args.show), subjects):
                print(f"semester={c['semester']} format={c['format']}")
                print(c["content"])
                print("-" * 40)
            return
    parser.error("only --show is supported so far")


if __name__ == "__main__":
    main()
