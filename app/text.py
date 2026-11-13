import re
from urllib.parse import urljoin, urlsplit

#constants
SITE = "https://www.torontomu.ca"
CALENDAR_YEAR = "2026-2027"

#for reading course code off websites
CODE_RE = re.compile(r"\b(C?[A-Z]{3})[ -]?(\d{3})\b")
#re.compile: turns pattern string into ready to use pattern object

#case insensitive version of CODE_RE
CODE_RE_ANY_CASE = re.compile(CODE_RE.pattern, re.IGNORECASE)

#date format
YEAR_RE = re.compile(r"/calendar/(\d{4}-\d{4})/")

#function to find every course code in piece of text and return them as clean list
def extract_codes(text):
    #CODE_RE.finditer: goes thorugh everey match
    codes = [f"{m.group(1)} {m.group(2)}" for m in CODE_RE.finditer(text)]
    return list(dict.fromkeys(codes))

#turn any url into one standard form
def normalize_url(href, base=None):
    parts = urlsplit(urljoin(base or SITE + "/", href))
    path = parts.path
    if path.startswith("/content/ryerson/calendar/"):
        path = path.removeprefix("/content/ryerson").removesuffix(".html")
    if not path.endswith("/"):
        path += "/"
    host = parts.netloc.lower()
    if host in ("torontomu.ca", "www.torontomu.ca"):
        return SITE + path
    return f"{parts.scheme}://{host}{path}"


#function to decide if a link should not be fetched: PDFs, jcr:content, other calendar years
def should_skip(url):
    path = urlsplit(url).path
    if path.lower().endswith(".pdf"):
        return True
    if "jcr:content" in path:
        return True
    year = YEAR_RE.search(path)
    return year is not None and year.group(1) != CALENDAR_YEAR


#function to rewrite course codes in any case to the stored form, only for known subjects
def normalize_codes(text, subjects):
    def rewrite(m):
        letters = m.group(1).upper()
        if letters not in subjects:
            return m.group(0)
        return f"{letters} {m.group(2)}"

    return CODE_RE_ANY_CASE.sub(rewrite, text)


#the exact sentence the assistant replies with when the excerpts don't answer the question
REFUSAL = "I don't know - check with your program advisor."

#curly quotes -> straight, en/em dashes -> "-"
PUNCTUATION_MAP = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


#lowercase, straight quotes, plain dashes, single spaces, no trailing punctuation
def normalize_answer(text):
    text = " ".join(text.lower().translate(PUNCTUATION_MAP).split())
    return text.rstrip(" .!?")


#is this answer the refusal sentence (ignoring case, quote/dash style, spacing, trailing punctuation)?
def is_refusal(answer):
    return normalize_answer(answer) == normalize_answer(REFUSAL)


SEMESTER_WORDS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth"]
#"3rd semester", "semester 3", "third semester" (also "sem 3")
SEMESTER_RES = [
    re.compile(r"\b([1-8])(?:st|nd|rd|th)\s+sem(?:ester)?\b", re.IGNORECASE),
    re.compile(r"\bsem(?:ester)?\s*([1-8])\b", re.IGNORECASE),
    re.compile(rf"\b({'|'.join(SEMESTER_WORDS)})\s+sem(?:ester)?\b", re.IGNORECASE),
]
PART_TIME_RE = re.compile(r"\bpart[- ]?time\b", re.IGNORECASE)
CO_OP_RE = re.compile(r"\bco-?op\b|\bwork[- ]?terms?\b", re.IGNORECASE)


#(semester, format) of the program chunk a question asks about, or None
#part-time only if the question says so, otherwise four-year; co-op work terms -> (None, "co-op")
def find_semester(question):
    for pattern in SEMESTER_RES:
        match = pattern.search(question)
        if match:
            value = match.group(1).lower()
            semester = int(value) if value.isdigit() else SEMESTER_WORDS.index(value) + 1
            return semester, "part-time" if PART_TIME_RE.search(question) else "four-year"
    if CO_OP_RE.search(question):
        return None, "co-op"
    return None
