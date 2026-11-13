# turns stored pages (documents) into chunks for search
# 1. parse each document by its kind into chunk texts
# 2. rewrite course codes to the stored form (CPS 803)
# 3. (step 4) replace the document's chunks, reusing embeddings when content_hash matches
# 4. (step 5) embed new chunks with Voyage in batches

import argparse
import math
import os
import re

import psycopg
from bs4 import BeautifulSoup, Comment, NavigableString
from dotenv import load_dotenv

from app.scrape import page_parser
from app.text import CODE_RE, normalize_codes, normalize_url


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


#screen-reader link notes, the table 'swipe' hint and the accordion Open All / Close All buttons
NOISE = "script, style, .sr-only-no-select, .scrollIndicator, .resAccordionControl"
COURSES_PER_CHUNK = 40
ORDINALS = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth"]
SEMESTER_RE = re.compile(rf"({'|'.join(ORDINALS)}) Semester")


#a page's <main> area with the noise removed
def clean_main(html):
    main = BeautifulSoup(html, "html.parser").find("main")
    for noise in main.select(NOISE):
        noise.decompose()
    return main


#take the page title (h1) out of the page and return it
def pop_title(main):
    title = main.h1.get_text(" ", strip=True)
    main.h1.decompose()
    return title


#every non-blank piece of text in page order, skipping HTML comments
def texts_in(element):
    for text in element.find_all(string=True):
        if not isinstance(text, Comment) and text.strip():
            yield text


#replace each table with one line per row, each value labelled with its column header,
#e.g. "Fall: Year 1 Semester 1, Year 2 Semester 3" (plain text would lose which column a value is in)
def flatten_tables(main):
    for table in main.find_all("table"):
        rows = [[cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"])]
                for tr in table.find_all("tr")]
        lines = [table.caption.get_text(" ", strip=True) + ":"] if table.caption else []
        headers = rows[0]
        for cells in rows[1:]:
            pairs = [f"{h} {v}" for h, v in zip(headers[1:], cells[1:]) if v]
            lines.append(f"{cells[0]}: {', '.join(pairs)}.")
        table.replace_with(NavigableString(" ".join(lines)))


#the heading a piece of text sits in: h2, h3, or an accordion title button; None for body text
def heading_of(text):
    return text.find_parent(["h2", "h3"]) or text.find_parent(class_="panel-title")


#split a page into (heading, [texts]) in page order; text before the first heading goes under the page title
def sections(main, title):
    result = [(title, [])]
    current = None
    for text in texts_in(main):
        heading = heading_of(text)
        if heading is not None:
            if heading is not current:
                current = heading
                result.append((heading.get_text(" ", strip=True).rstrip(":"), []))
            continue
        result[-1][1].append(text.strip())
    return [(heading, texts) for heading, texts in result if texts]


#group size that splits n courses into equal parts of at most 40 (41 -> 21 + 20, not 40 + 1)
def group_size(n):
    if n == 0:
        return COURSES_PER_CHUNK
    return math.ceil(n / math.ceil(n / COURSES_PER_CHUNK))


#split texts into equal groups of at most 40 courses; a new group starts at a course code
def split_courses(texts):
    size = group_size(sum(1 for text in texts if CODE_RE.fullmatch(text)))
    groups = [[]]
    count = 0
    for text in texts:
        if CODE_RE.fullmatch(text):
            if count == size:
                groups.append([])
                count = 0
            count += 1
        groups[-1].append(text)
    return groups


#one chunk per section (long course lists split in parts), each starting with page title and heading
def section_chunks(title, page_sections):
    chunks = []
    for heading, texts in page_sections:
        groups = split_courses(texts)
        for i, group in enumerate(groups):
            label = heading if len(groups) == 1 else f"{heading} (part {i + 1} of {len(groups)})"
            chunks.append(chunk(f"{title} — {label}: {' '.join(group)}"))
    return chunks


#policy page: one chunk per section (h2, h3 or accordion title)
def policy_chunks(html, url):
    main = clean_main(html)
    flatten_tables(main)
    title = pop_title(main)
    return section_chunks(title, sections(main, title))


#Table A / B list "not available for credit" courses for every TMU program; return Computer Science's
def cs_restrictions(panel):
    for h2 in panel.find_all("h2"):
        if h2.get_text(strip=True) != "Computer Science":
            continue
        block = h2.find_parent("div", class_="resTitle")
        texts = []
        for sibling in block.find_next_siblings():
            if sibling.find("h2"):
                break
            texts.extend(t.strip() for t in texts_in(sibling))
        return " ".join(texts)
    return None


#elective tables: the course list in equal groups of at most 40, the CS restrictions, then the other sections
def elective_chunks(html, url):
    main = clean_main(html)
    title = pop_title(main)
    chunks = []

    #Table A / B course list: a table whose header row is "Course | Title"
    for table in main.find_all("table"):
        rows = [[cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"])]
                for tr in table.find_all("tr")]
        if rows[0][:2] != ["Course", "Title"]:
            continue
        courses = [f"{cells[0]} {cells[1]}" for cells in rows[1:]]
        size = group_size(len(courses))
        for start in range(0, len(courses), size):
            group = courses[start:start + size]
            label = f"courses {start + 1}–{start + len(group)} of {len(courses)}"
            chunks.append(chunk(f"{title} — {label}: {'; '.join(group)}."))
        table.decompose()

    #per-faculty restriction panels (they hold program headings): keep Computer Science's entry, drop the rest
    for panel in main.select("div.panel"):
        if panel.select_one("div.resTitle h2") is None:
            continue
        restrictions = cs_restrictions(panel)
        if restrictions:
            chunks.append(chunk(f"{title} — Computer Science restrictions: {restrictions}"))
        panel.decompose()

    flatten_tables(main)
    return chunks + section_chunks(title, sections(main, title))


#which program format an h2 on the curriculum page starts
def program_format(heading):
    if "Co-op" in heading:
        return "co-op"
    if "Part-Time" in heading:
        return "part-time"
    if "Four-Year" in heading:
        return "four-year"
    return None


#curriculum page: one chunk per semester for four-year and part-time, one co-op work-term chunk
def program_chunks(html, url):
    main = clean_main(html)
    flatten_tables(main)
    title = pop_title(main)

    #(format, semester) -> texts; the co-op schedule has no semester
    parts = {}
    format_names = {}
    format = semester = None
    for text in texts_in(main):
        value = text.strip()
        if text.find_parent("h2"):
            format, semester = program_format(value), None
            format_names[format] = value
            continue
        if format is None:
            continue  #links before the first program heading
        label = SEMESTER_RE.fullmatch(value)
        if label and text.find_parent(["b", "strong"]):
            semester = ORDINALS.index(label.group(1)) + 1
            continue
        if format != "co-op" and text.find_parent(class_="panel-title"):
            continue  #accordion titles like "First and Second Semester"
        parts.setdefault((format, semester), []).append(value)

    chunks = []
    for (format, semester), texts in parts.items():
        if format != "co-op" and semester is None:
            continue
        heading = f"{ORDINALS[semester - 1]} Semester" if semester else "Work Term Schedule"
        content = f"{title} — {format_names[format]} — {heading}: {' '.join(texts)}"
        chunks.append(chunk(content, semester, format))
    return chunks


#kind -> function that turns that kind of page into chunks
CHUNKERS = {
    "course": course_chunks,
    "date": date_chunks,
    "policy": policy_chunks,
    "elective_table": elective_chunks,
    "program": program_chunks,
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
