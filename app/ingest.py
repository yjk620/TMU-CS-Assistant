# turns stored pages (documents) into chunks for search
# 1. parse each document by its kind into chunk texts
# 2. rewrite course codes to the stored form (CPS 803)
# 3. (step 4) replace the document's chunks, reusing embeddings when content_hash matches
# 4. (step 5) embed new chunks with Voyage in batches

import argparse
import os

import psycopg
from bs4 import BeautifulSoup, Comment
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


#dates page: one chunk per row of the first table, each value labelled with its column name
#(the second table only links to older years' dates)
def date_chunks(html, url):
    table = BeautifulSoup(html, "html.parser").find("table")
    rows = [[cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"])]
            for tr in table.find_all("tr")]
    headers = [h.replace("YYYY-MM-DD", "").strip() for h in rows[0]]

    chunks = []
    for cells in rows[1:]:
        row = dict(zip(headers, cells))
        parts = [f"Category: {row['Category']}.", f"Subject: {row['Subject'].rstrip('.')}."]
        parts.append(f"Start Date: {row['Start Date']}. End Date: {row['End Date']}.")
        if row["Description"] and row["Description"] != row["Subject"]:
            parts.append(f"Description: {row['Description']}")
        chunks.append(chunk("Significant Dates — " + " ".join(parts)))
    return chunks


#the heading a piece of text sits in: h2, h3, or an accordion title button; None for body text
def heading_of(text):
    return text.find_parent(["h2", "h3"]) or text.find_parent("div", class_="panel-title")


#policy page: one chunk per section (h2, h3 or accordion title), each starting with page title and heading
def policy_chunks(html, url):
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")
    #screen-reader link notes, the table 'swipe' hint and the accordion Open All / Close All buttons
    for noise in main.select("script, style, .sr-only-no-select, .scrollIndicator, .resAccordionControl"):
        noise.decompose()
    title = main.h1.get_text(" ", strip=True)
    main.h1.decompose()

    #(heading, [texts]) in page order; text before the first heading goes under the page title
    sections = [(title, [])]
    current = None
    for text in main.find_all(string=True):
        if isinstance(text, Comment) or not text.strip():
            continue
        heading = heading_of(text)
        if heading is not None:
            if heading is not current:
                current = heading
                sections.append((heading.get_text(" ", strip=True), []))
            continue
        sections[-1][1].append(text.strip())

    chunks = []
    for heading, texts in sections:
        if texts:
            chunks.append(chunk(f"{title} — {heading}: {' '.join(texts)}"))
    return chunks


#kind -> function that turns that kind of page into chunks
CHUNKERS = {
    "course": course_chunks,
    "date": date_chunks,
    "policy": policy_chunks,
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
