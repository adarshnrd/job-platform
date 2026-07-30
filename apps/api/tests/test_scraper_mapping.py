"""Pure-function mapping tests for the global-source scrapers.

Each case here corresponds to a real defect observed against live data while
these scrapers were built — they are regression guards, not coverage filler.
"""
import pytest

from scrapers.arc import ArcScraper
from scrapers.base import BaseScraper
from scrapers.flexjobs import FlexJobsScraper
from scrapers.peerlist import PeerlistScraper
from scrapers.remoteok import RemoteOKScraper
from scrapers.weworkremotely import WeWorkRemotelyScraper
from scrapers.wellfound import WellfoundScraper


# ══════════════════════════════════════════════════════════════
#  SHARED TERM MATCHER
# ══════════════════════════════════════════════════════════════

LEVELS = {"junior": "entry", "senior": "senior", "lead": "lead", "vp": "exec", "staff": "principal"}
TYPES = {"contract": "contract", "part-time": "pt", "go": "go", "ai": "ai", "c#": "csharp"}


@pytest.mark.parametrize("text,expected", [
    ("Senior Backend Engineer", "senior"),
    ("VP of Engineering", "exec"),
    ("Staff Engineer", "principal"),
    # The bug this guards: substring matching read "vp" out of "ADVPL" and
    # labelled a junior ERP role as executive.
    ("ADVPL Junior Developer", "entry"),
    ("Developer, ADVPL stack", None),
])
def test_match_terms_respects_word_boundaries(text, expected):
    assert BaseScraper.match_terms(text, LEVELS) == expected


@pytest.mark.parametrize("text,expected", [
    ("Part-time role", "pt"),
    ("Contract position", "contract"),
    ("Golang developer", None),      # not "go"
    ("Django developer", None),      # not "go"
    ("Email marketing lead", None),  # not "ai"
    ("AI engineer", "ai"),
    ("C# developer", "csharp"),      # punctuation-bearing key still matches
])
def test_match_terms_handles_punctuation_and_false_positives(text, expected):
    assert BaseScraper.match_terms(text, TYPES) == expected


def test_match_terms_returns_the_default_when_nothing_matches():
    assert BaseScraper.match_terms("Product Manager", LEVELS, "fallback") == "fallback"
    assert BaseScraper.match_terms("", LEVELS, "fallback") == "fallback"
    assert BaseScraper.match_terms(None, LEVELS, "fallback") == "fallback"


# ══════════════════════════════════════════════════════════════
#  REMOTE OK
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,expected", [
    # RemoteOK stores some listings double-encoded; the response itself is
    # valid UTF-8, so this is upstream corruption we repair on read.
    ("JÃºnior", "Júnior"),
    ("SoluÃ§Ãµes de NegÃ³cios", "Soluções de Negócios"),
    ("EspaÃ±a", "España"),
    # Clean text must pass through untouched.
    ("Señor Developer", "Señor Developer"),
    ("Plain ASCII", "Plain ASCII"),
    ("", ""),
])
def test_remoteok_repairs_double_encoded_text(raw, expected):
    assert RemoteOKScraper._fix_mojibake(raw) == expected


@pytest.mark.parametrize("value,expected", [
    (0, None),        # RemoteOK's "not disclosed" sentinel
    ("0", None),
    (None, None),
    ("", None),
    (120000, 120000),
    ("95000", 95000),
    ("not-a-number", None),
])
def test_remoteok_salary_sentinels(value, expected):
    assert RemoteOKScraper._salary(value) == expected


# ══════════════════════════════════════════════════════════════
#  WE WORK REMOTELY
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,company,title", [
    ("Tether: AI Research Engineer", "Tether", "AI Research Engineer"),
    ("Acme Corp | Senior Developer", "Acme Corp", "Senior Developer"),
    # No separator: the feed gives us no company, so say so rather than
    # slicing the title arbitrarily.
    ("Standalone Role Title", "Company (via WWR)", "Standalone Role Title"),
    ("Trailing separator:", "Company (via WWR)", "Trailing separator:"),
])
def test_wwr_title_split(raw, company, title):
    assert WeWorkRemotelyScraper._split_title(raw) == (company, title)


def test_wwr_parses_rfc822_pubdate():
    """RSS dates are RFC-822 — the base ISO/epoch parser cannot read them."""
    dt = WeWorkRemotelyScraper._parse_pubdate("Tue, 30 Jun 2026 20:33:23 +0000")
    assert dt is not None and (dt.year, dt.month, dt.day) == (2026, 6, 30)
    assert dt.tzinfo is None  # naive, matching the rest of the pipeline
    assert WeWorkRemotelyScraper._parse_pubdate("") is None
    assert WeWorkRemotelyScraper._parse_pubdate("garbage") is None


# ══════════════════════════════════════════════════════════════
#  ARC
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("text,lo,hi", [
    ("US$35K - 40K", 35000, 40000),
    ("US$120,000 - 150,000", 120000, 150000),
    ("$90K", 90000, 90000),
    ("Hourly rate", None, None),
    ("", None, None),
    # Reversed bands are normalised rather than stored backwards.
    ("US$50K - 30K", 30000, 50000),
])
def test_arc_salary_parsing(text, lo, hi):
    assert ArcScraper._parse_salary(text) == (lo, hi)


@pytest.mark.parametrize("query,location,expected", [
    ("backend", "", "https://arc.dev/remote-jobs/back-end"),
    ("python", "India", "https://arc.dev/en-in/remote-jobs/python"),
    ("react", "United Kingdom", "https://arc.dev/en-gb/remote-jobs/react"),
    # Unknown topic falls back to the unfiltered board, unknown country to global.
    ("underwater basket weaving", "", "https://arc.dev/remote-jobs"),
    ("golang", "Atlantis", "https://arc.dev/remote-jobs/golang"),
    # A multi-word query still finds its most specific known topic.
    ("senior kubernetes engineer", "", "https://arc.dev/remote-jobs/kubernetes"),
])
def test_arc_url_building(query, location, expected):
    assert ArcScraper()._build_url(query, location) == expected


def test_arc_strips_page_chrome_from_the_jd():
    """Detail pages have no description wrapper, so the JD is body text minus
    the nav header and footer."""
    raw = (
        "For companies For talent Log In Find jobs Hire talent "
        "Senior Backend Engineer We are hiring. Copyright ©2026 Arc. All rights reserved."
    )
    out = ArcScraper._strip_chrome(raw)
    assert out == "Senior Backend Engineer We are hiring."
    assert "Log In" not in out and "Copyright" not in out


def test_arc_strip_chrome_is_safe_on_unexpected_shapes():
    assert ArcScraper._strip_chrome("") == ""
    assert ArcScraper._strip_chrome(None) == ""
    # No chrome present → text survives intact.
    assert ArcScraper._strip_chrome("Just   the  job") == "Just the job"
    # A footer marker at position 0 must not blank the whole description.
    assert ArcScraper._strip_chrome("Copyright ©2026 Arc") == "Copyright ©2026 Arc"


def test_arc_location_skips_the_title_line():
    """Titles routinely end in "- Worldwide" and were being read as the location."""
    lines = ["Remote anywhere", "Actively hiring"]
    assert ArcScraper._location_from(lines) == "Remote anywhere"
    assert ArcScraper._location_from(["Min. 5 hr overlap with Stockholm"]).startswith("Min.")
    assert ArcScraper._location_from([]) == ""


# ══════════════════════════════════════════════════════════════
#  PEERLIST / FLEXJOBS
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("slug,expected", [
    ("senior-software-engineer--trading", "Senior Software Engineer - Trading"),
    ("machine-learning-engineer", "Machine Learning Engineer"),
    ("cognitiv_ai", "Cognitiv"),        # disambiguating suffix stripped
    ("alpaca_marke", "Alpaca"),
])
def test_peerlist_deslug(slug, expected):
    assert PeerlistScraper._deslug(slug) == expected


def test_peerlist_job_href_shape():
    from scrapers.peerlist import _JOB_HREF_RE
    good = "/company/autodesk/careers/software-engineer/jobhnn7pkb7o9rog8in966jad7j7ao"
    assert _JOB_HREF_RE.match(good)
    for bad in ("/jobs", "/company/autodesk", "/company/x/careers/y", "/blog/post"):
        assert not _JOB_HREF_RE.match(bad)


def test_flexjobs_public_job_href_shape():
    from scrapers.flexjobs import _JOB_HREF_RE
    good = "/publicjobs/software-engineer-55f16e47-3bcd-4a50-871d-3d50f24b3ba9"
    m = _JOB_HREF_RE.match(good)
    assert m and m.group(1) == "software-engineer"
    for bad in ("/publicjobs/no-uuid-here", "/search?search=x", "/blog/post/remote-jobs"):
        assert not _JOB_HREF_RE.match(bad)


@pytest.mark.parametrize("scraper_cls", [PeerlistScraper, FlexJobsScraper])
def test_headed_sources_declare_it(scraper_cls):
    """Both boards 403 every headless browser — the flag is load-bearing."""
    assert scraper_cls.requires_headed is True
    # Listings with no JD would burn LLM budget for a meaningless score.
    assert scraper_cls.MIN_JD_CHARS > 0


# ══════════════════════════════════════════════════════════════
#  WELLFOUND
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_wellfound_search_is_a_documented_no_op():
    """Its bot wall rejects headed browsers too, so this must not pop a window."""
    assert WellfoundScraper.requires_headed is False
    assert await WellfoundScraper().search_jobs("engineer") == []
