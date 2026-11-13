# 1. a polite fetcher: one httpx client with clear User-Agent
#    and a 1 second pause between requests
# 2. a course-page parser: given the page, returns code, title, description, prerequisites
#    From prerequisites, extract_codes produce prereq_codes
# 3. save to db: store the extracted info into db documents

import argparse
import logging
import os
import time
from collections import deque

import httpx
import psycopg
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from app.text import CALENDAR_YEAR, SITE, extract_codes, normalize_url, should_skip

log = logging.getLogger("scrape")

#constants
USER_AGENT = "TMU-CS-assistant/0.1 (student portfolio project)"
DELAY_SECONDS = 1
CALENDAR = f"{SITE}/calendar/{CALENDAR_YEAR}"
COURSE_PATH = f"/calendar/{CALENDAR_YEAR}/courses/"

#fixed pages: (url, kind, follow its course links?)
FIXED_PAGES = [
    (f"{SITE}/cs/current-undergraduate-students/curriculum-courses/computer-science-program/", "program", True),
    (f"{CALENDAR}/programs/science/computer_sci/table_i/", "elective_table", True),
    (f"{CALENDAR}/liberal-studies/table_a/", "elective_table", True),
    (f"{CALENDAR}/liberal-studies/table_b/", "elective_table", True),
    (f"{CALENDAR}/open-electives/", "elective_table", False),
    (f"{CALENDAR}/dates/", "date", False),
    (f"{CALENDAR}/policies-and-procedures/enrolment-records/enrolment/", "policy", False),
    (f"{CALENDAR}/policies-and-procedures/enrolment-records/curriculum_info/", "policy", False),
]

client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)

#fetch one page, waiting first so we never send more than one request per second
def polite_fetcher(url):
    time.sleep(DELAY_SECONDS)
    response = client.get(url)
    response.raise_for_status()
    return response.text

#page title: the page's h1, or the first part of <title> if there is no h1
def page_title(soup, url):
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(" ", strip=True)
    if soup.title:
        return soup.title.get_text(strip=True).split(" - ")[0]
    return url

#every course page link on a page, normalized, skipping other years / PDFs / jcr:content
def course_links(soup, page_url):
    links = []
    for a in soup.find_all("a", href=True):
        url = normalize_url(a["href"], page_url)
        if "/courses/" not in url:
            continue
        if should_skip(url):
            log.info("skipped %s", url)
            continue
        if url.startswith(SITE + COURSE_PATH):
            links.append(url)
    return list(dict.fromkeys(links))

#course-page parser: code, title, description, prerequisites, and links to the prerequisite pages
def page_parser(html, url):
    soup = BeautifulSoup(html, "html.parser")
    block = soup.select_one("div.resCalendarCourse")
    if block is None or block.h1 is None:
        raise ValueError(f"not a course page: {url}")

    description = block.select_one("div.courseDescription")
    course = {
        "code": block.h1.get_text(" ", strip=True),
        "title": block.h2.get_text(" ", strip=True) if block.h2 else "",
        "description": description.get_text(" ", strip=True) if description else "",
        "prereq_text": None,
        "prereq_codes": [],
        "prereq_links": [],
    }

    #only the Prerequisites field: co-requisites, antirequisites and custom requisites are ignored
    for req in block.select("div.requisites"):
        if req.h3 is None or req.h3.get_text(strip=True) != "Prerequisites":
            continue
        words = list(req.stripped_strings)[1:]
        text = " ".join(words)
        if text and text != "None":
            course["prereq_text"] = text
            course["prereq_codes"] = extract_codes(text)
            course["prereq_links"] = course_links(req, url)
    return course

#save a page into documents (insert, or update if the url is already there); returns its id
def store_data(conn, url, kind, title, html):
    row = conn.execute(
        """
        insert into documents (url, kind, title, html, fetched_at)
        values (%s, %s, %s, %s, now())
        on conflict (url) do update
            set kind = excluded.kind, title = excluded.title,
                html = excluded.html, fetched_at = excluded.fetched_at
        returning id
        """,
        (url, kind, title, html),
    ).fetchone()
    return row[0]

#save a course row (insert, or update if the code is already there)
def store_course(conn, course, document_id):
    conn.execute(
        """
        insert into courses (code, document_id, prereq_text, prereq_codes)
        values (%s, %s, %s, %s)
        on conflict (code) do update
            set document_id = excluded.document_id,
                prereq_text = excluded.prereq_text,
                prereq_codes = excluded.prereq_codes
        """,
        (course["code"], document_id, course["prereq_text"], course["prereq_codes"]),
    )

#the whole crawl: fixed pages first, then every course they link to, then prerequisites until none are new
def crawl(conn):
    queue = deque()
    seen = set()
    failed = []

    for url, kind, follow in FIXED_PAGES:
        try:
            html = polite_fetcher(url)
        except httpx.HTTPError as error:
            log.warning("failed %s: %s", url, error)
            failed.append(url)
            continue
        soup = BeautifulSoup(html, "html.parser")
        with conn.transaction():
            store_data(conn, url, kind, page_title(soup, url), html)
        log.info("stored %s %s", kind, url)
        if follow:
            queue.extend(course_links(soup, url))

    while queue:
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        try:
            html = polite_fetcher(url)
            course = page_parser(html, url)
        except (httpx.HTTPError, ValueError) as error:
            log.warning("failed %s: %s", url, error)
            failed.append(url)
            continue
        with conn.transaction():
            document_id = store_data(conn, url, "course", f"{course['code']} {course['title']}", html)
            store_course(conn, course, document_id)
        queue.extend(link for link in course["prereq_links"] if link not in seen)
        log.info("[%d done, %d queued] %s", len(seen), len(queue), course["code"])

    return failed

def main():
    parser = argparse.ArgumentParser(description="Scrape the TMU CS curriculum and 2026-27 calendar pages")
    parser.add_argument("--course", help="fetch one course page and print what was parsed, without saving")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.course:
        url = normalize_url(args.course)
        course = page_parser(polite_fetcher(url), url)
        for key, value in course.items():
            print(f"{key}: {value}")
        return

    load_dotenv()
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        failed = crawl(conn)
        documents = conn.execute("select count(*) from documents").fetchone()[0]
        courses = conn.execute("select count(*) from courses").fetchone()[0]
    log.info("done: %d documents, %d courses, %d failed", documents, courses, len(failed))
    for url in failed:
        log.info("failed: %s", url)

if __name__ == "__main__":
    main()
