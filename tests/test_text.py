import pytest

from app.text import extract_codes, normalize_codes, normalize_url, should_skip

BASE = "https://www.torontomu.ca"
CPS_803 = f"{BASE}/calendar/2026-2027/courses/computer-science/CPS/803/"
CS_PAGE = f"{BASE}/cs/current-undergraduate-students/curriculum-courses/computer-science-program/"
SUBJECTS = {"CPS", "MTH", "CCPS"}


@pytest.mark.parametrize(
    "href, expected",
    [
        (f"{BASE}/content/ryerson/calendar/2026-2027/courses/computer-science/CPS/803.html", CPS_803),
        (f"{BASE}/calendar/2026-2027/courses/computer-science/CPS/803", CPS_803),
        (CPS_803, CPS_803),
        (f"{BASE}/calendar/2026-2027/courses/computer-science/CPS/803/?foo=1#bar", CPS_803),
        (f"{BASE}/content/ryerson/calendar/2026-2027/courses/computer-science/CPS/803.html#top", CPS_803),
        ("http://torontomu.ca/calendar/2026-2027/courses/computer-science/CPS/803/", CPS_803),
        (CS_PAGE.rstrip("/"), CS_PAGE),
        (CS_PAGE, CS_PAGE),
    ],
)
def test_normalize_url(href, expected):
    assert normalize_url(href) == expected


@pytest.mark.parametrize(
    "href, expected",
    [
        ("/content/ryerson/calendar/2026-2027/dates.html", f"{BASE}/calendar/2026-2027/dates/"),
        ("/calendar/2026-2027/courses/computer-science/CPS/803/", CPS_803),
        ("803.html", CPS_803),
    ],
)
def test_normalize_url_relative(href, expected):
    page = f"{BASE}/content/ryerson/calendar/2026-2027/courses/computer-science/CPS/109.html"
    assert normalize_url(href, page) == expected


@pytest.mark.parametrize(
    "url",
    [
        f"{BASE}/content/ryerson/calendar/2019-2020/courses/work-term/WKT/503.html",
        f"{BASE}/calendar/2025-2026/courses/computer-science/CPS/803/",
        f"{BASE}/content/ryerson/calendar/2026-2027/jcr:content/root/responsivegrid.html",
        f"{BASE}/content/dam/cs/prerequisite-table.pdf",
        f"{BASE}/content/dam/cs/prerequisite-table.PDF",
    ],
)
def test_should_skip(url):
    assert should_skip(url)


@pytest.mark.parametrize(
    "url",
    [
        f"{BASE}/content/ryerson/calendar/2026-2027/courses/computer-science/CPS/803.html",
        CPS_803,
        CS_PAGE,
        f"{BASE}/calendar/2026-2027/dates/",
    ],
)
def test_should_not_skip(url):
    assert not should_skip(url)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("MTH 108 and MTH 207 and CPS 305 and ( MTH 380 or MTH 304 )",
         ["MTH 108", "MTH 207", "CPS 305", "MTH 380", "MTH 304"]),
        ("CPS 109 or CPS 109", ["CPS 109"]),
        ("CCPS109", ["CCPS 109"]),
        ("CPS-803", ["CPS 803"]),
        ("cps 803", []),
        ("Fall 2026", []),
        ("", []),
    ],
)
def test_extract_codes(text, expected):
    assert extract_codes(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("What is cps803 about?", "What is CPS 803 about?"),
        ("Can I take CPS-803?", "Can I take CPS 803?"),
        ("CPS803 after mth 108", "CPS 803 after MTH 108"),
        ("Is CCPS109 part-time?", "Is CCPS 109 part-time?"),
        ("CPS 803 is fine", "CPS 803 is fine"),
        ("When is the last day to drop a Fall 2026 course?", "When is the last day to drop a Fall 2026 course?"),
        ("Can I take any 400-level electives?", "Can I take any 400-level electives?"),
        ("The course has 120 hours", "The course has 120 hours"),
        ("What about the 300 level?", "What about the 300 level?"),
        ("Is ENG 104 on Table A?", "Is ENG 104 on Table A?"),
        ("is eng104 on table a?", "is eng104 on table a?"),
    ],
)
def test_normalize_codes(text, expected):
    assert normalize_codes(text, SUBJECTS) == expected

