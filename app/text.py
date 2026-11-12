import re
from urllib.parse import urljoin, urlsplit

#constants
SITE = "https://www.torontomu.ca"
CALENDAR_YEAR = "2026-2027"

#for reading course code off websites
CODE_RE = re.compile(r"\b(C?[A-Z]{3})[ -]?(\d{3})\b")
#re.compile: turns pattern string into ready to use pattern object

#for user question course code reading
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
