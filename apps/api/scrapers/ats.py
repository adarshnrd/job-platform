"""
ATS-direct aggregator — pulls jobs straight from company career boards.

Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Oracle HCM
Candidate Experience, Workday CXS, BambooHR and Teamtailor power companies' own
careers pages and expose public, keyless JSON APIs. Phase 3 adds Oracle Taleo
career sections, Phenom People sites and Avature sitemaps, which need a little
HTML parsing. No bot-walls, no selectors, no login. One "source" here fans out
across many company boards, so it is the highest-yield / lowest-fragility way to
add coverage: product/startup roles that never hit the big aggregators and, via
Oracle, Workday, BambooHR and Teamtailor, the large Gulf employers that do not
use the startup ATSs.

Seed boards below are verified live: SEED_BOARDS for India/global and
MENA_SEED_BOARDS for the Gulf/Levant/North Africa (docs/mena/
PHASE_1_ATS_EMPLOYERS.md). A board may carry a `regions` tuple so a run only
fetches boards that serve its region — an India run must not pull DP World's
559 jobs. The list also grows via a token harvester (parse apply_urls we
already collect), see services/ats_harvester.py.

Compliance: only vacancy data is copied. Oracle HCM detail payloads carry
ExternalContactName / ExternalContactEmail / HiringManager — those fields are
never read (PDPL, docs/mena/README.md §5.2). Normalizers whitelist the fields
they take instead of copying whole payloads.
"""
import asyncio
import html as _htmllib
import json
import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import unquote

from loguru import logger

from scrapers.api_base import APIBaseScraper
from scrapers.jsonld import find_job_posting, map_job_posting, strip_html
from scrapers.mena_common import scrub_contacts
from models.job import ExperienceLevel, JobListingCreate, Platform
from services.ats_harvester import split_token
from services.geo import mena
from services.prefilter import TECH_ROLE_WORDS

# Verified live 2026-07-07 (each returns real India listings). This is a seed —
# the harvester (services/ats_harvester.py) grows it automatically from apply
# URLs we collect, persisting new boards to data/ats_boards.json.
SEED_BOARDS: list[dict] = [
    # ── Greenhouse ──
    {"ats": "greenhouse", "token": "postman",    "company": "Postman"},
    {"ats": "greenhouse", "token": "groww",      "company": "Groww"},
    {"ats": "greenhouse", "token": "druva",      "company": "Druva"},
    {"ats": "greenhouse", "token": "netskope",   "company": "Netskope"},
    {"ats": "greenhouse", "token": "phonepe",    "company": "PhonePe"},
    {"ats": "greenhouse", "token": "hackerrank", "company": "HackerRank"},
    {"ats": "greenhouse", "token": "mongodb",    "company": "MongoDB"},
    {"ats": "greenhouse", "token": "gitlab",     "company": "GitLab"},
    # ~15 verified MENA roles, so Elastic also serves the mena region.
    {"ats": "greenhouse", "token": "elastic",    "company": "Elastic", "regions": ("india", "global", "mena")},
    {"ats": "greenhouse", "token": "databricks", "company": "Databricks"},
    {"ats": "greenhouse", "token": "razorpaysoftwareprivatelimited", "company": "Razorpay"},
    {"ats": "greenhouse", "token": "stripe",     "company": "Stripe"},
    {"ats": "greenhouse", "token": "twilio",     "company": "Twilio"},
    {"ats": "greenhouse", "token": "rubrik",     "company": "Rubrik"},
    {"ats": "greenhouse", "token": "samsara",    "company": "Samsara"},
    {"ats": "greenhouse", "token": "airbnb",     "company": "Airbnb"},
    {"ats": "greenhouse", "token": "coinbase",   "company": "Coinbase"},
    # ── Lever ──
    {"ats": "lever", "token": "meesho", "company": "Meesho"},
    # ── Ashby ──
    {"ats": "ashby", "token": "sarvam", "company": "Sarvam AI"},
    {"ats": "ashby", "token": "openai", "company": "OpenAI"},
    # ── SmartRecruiters (enterprise boards with large India offices;
    #     verified live 2026-07-16 via ?country=in) ──
    {"ats": "smartrecruiters", "token": "visa", "company": "Visa"},
    {"ats": "smartrecruiters", "token": "boschgroup", "company": "Bosch Group"},
    {"ats": "smartrecruiters", "token": "ubisoft2", "company": "Ubisoft"},
    {"ats": "smartrecruiters", "token": "servicenow", "company": "ServiceNow"},
    # ── Workable (few India-office boards publish via the widget API today;
    #     coverage grows through the harvester as apply URLs surface tokens) ──
    {"ats": "workable", "token": "huggingface", "company": "Hugging Face"},
    # ── Recruitee ──
    {"ats": "recruitee", "token": "hostaway", "company": "Hostaway"},
]

# Boards without a `regions` tag serve india+global (every seed above). Harvested
# boards carry no tag either, but we cannot tell where they hire, so they serve
# every region (see _boards).
_DEFAULT_SEED_REGIONS = ("india", "global")

# Verified live 2026-10-17 (docs/mena/README.md §3.1). MENA-region boards.
# `default_location` replaces the hard-coded "India" fallback in _norm_*.
MENA_SEED_BOARDS: list[dict] = [
    # ── Greenhouse ──
    {"ats": "greenhouse", "token": "tamara",  "company": "Tamara",  "regions": ("mena", "global"), "default_location": "Riyadh, Saudi Arabia"},
    {"ats": "greenhouse", "token": "careem",  "company": "Careem",  "regions": ("mena", "global"), "default_location": "Dubai, United Arab Emirates"},
    {"ats": "greenhouse", "token": "binance", "company": "Binance", "regions": ("mena", "global")},
    # ── Ashby. Token lookup is case-insensitive (verified live), so lowercase
    #     keeps the (ats, token) dedupe key identical to what the harvester emits. ──
    {"ats": "ashby", "token": "ziina",    "company": "Ziina",             "regions": ("mena", "global"), "default_location": "Dubai, United Arab Emirates"},
    {"ats": "ashby", "token": "thndr",    "company": "Thndr",             "regions": ("mena", "global"), "default_location": "Cairo, Egypt"},
    {"ats": "ashby", "token": "leantech", "company": "Lean Technologies", "regions": ("mena", "global"), "default_location": "Riyadh, Saudi Arabia"},
    # ── Workable ──
    {"ats": "workable", "token": "salla",       "company": "Salla",        "regions": ("mena", "global"), "default_location": "Saudi Arabia"},
    {"ats": "workable", "token": "foodics",     "company": "Foodics",      "regions": ("mena", "global"), "default_location": "Riyadh, Saudi Arabia"},
    {"ats": "workable", "token": "progressoft", "company": "ProgressSoft", "regions": ("mena", "global"), "default_location": "Amman, Jordan"},
    # ── SmartRecruiters ──
    {"ats": "smartrecruiters", "token": "deliveryhero",   "company": "Delivery Hero / talabat", "regions": ("mena",)},
    {"ats": "smartrecruiters", "token": "EtihadAirways5", "company": "Etihad Airways",          "regions": ("mena",), "default_location": "Abu Dhabi, United Arab Emirates"},
    # ── Oracle HCM Candidate Experience ──
    {"ats": "oracle_hcm", "token": "dpworld",     "company": "DP World",
     "host": "ehpv.fa.em2.oraclecloud.com", "site": "CX_1", "regions": ("mena",)},
    {"ats": "oracle_hcm", "token": "emiratesnbd", "company": "Emirates NBD",
     "host": "fa-evlo-saasfaprod1.fa.ocs.oraclecloud.com", "site": "CX_1", "regions": ("mena",)},
    {"ats": "oracle_hcm", "token": "fab",         "company": "First Abu Dhabi Bank",
     "host": "ehjd.fa.em2.oraclecloud.com", "site": "fabCareers", "regions": ("mena",)},
    # ── Workday CXS ──
    {"ats": "workday", "token": "murex", "company": "Murex",
     "host": "murex.wd3.myworkdayjobs.com", "tenant": "murex", "site": "MurexCareerPage1", "regions": ("mena", "global")},
    # ── BambooHR ──
    {"ats": "bamboohr", "token": "toters",   "company": "Toters",   "regions": ("mena",), "default_location": "Beirut, Lebanon"},
    {"ats": "bamboohr", "token": "instabug", "company": "Instabug", "regions": ("mena", "global")},
    # ── Teamtailor (public /jobs.json feed) ──
    {"ats": "teamtailor", "token": "careers.chalhoubgroup.com", "company": "Chalhoub Group", "regions": ("mena",), "default_location": "Dubai, United Arab Emirates"},
    # Phase 3 (docs/mena/PHASE_3_BUILD.md B2), verified live 2026-10-17. The four
    # small SmartRecruiters boards use sr_countries=(None,): one unfiltered list
    # call instead of nine (all have <= 10 postings). Rejected
    # look-alikes: stc.teamtailor.com (Swedish), personio nbk (German),
    # smartrecruiters noonacademy (India only), breezy dubizzlelabs (Lahore).
    {"ats": "teamtailor", "token": "propertyfinder.teamtailor.com", "company": "Property Finder", "regions": ("mena",), "default_location": "Dubai, United Arab Emirates"},
    {"ats": "teamtailor", "token": "dubizzle.teamtailor.com",       "company": "Dubizzle",        "regions": ("mena",), "default_location": "Dubai, United Arab Emirates"},
    {"ats": "teamtailor", "token": "rasan.teamtailor.com",          "company": "Rasan",           "regions": ("mena",), "default_location": "Riyadh, Saudi Arabia"},
    {"ats": "teamtailor", "token": "qashio.teamtailor.com",         "company": "Qashio",          "regions": ("mena",), "default_location": "Dubai, United Arab Emirates"},
    {"ats": "recruitee", "token": "unifonic", "company": "Unifonic", "regions": ("mena",), "default_location": "Riyadh, Saudi Arabia"},
    {"ats": "workable", "token": "agility",  "company": "Agility", "regions": ("mena",), "default_location": "Riyadh, Saudi Arabia"},
    {"ats": "workable", "token": "tamatem",  "company": "Tamatem", "regions": ("mena",), "default_location": "Amman, Jordan"},
    {"ats": "workable", "token": "ananinja", "company": "Ninja",   "regions": ("mena",), "default_location": "Riyadh, Saudi Arabia"},
    {"ats": "workable", "token": "lucidya",  "company": "Lucidya", "regions": ("mena",), "default_location": "Riyadh, Saudi Arabia"},
    {"ats": "smartrecruiters", "token": "almosafer", "company": "Almosafer",   "regions": ("mena",), "sr_countries": (None,), "default_location": "Riyadh, Saudi Arabia"},
    {"ats": "smartrecruiters", "token": "seera",     "company": "Seera Group", "regions": ("mena",), "sr_countries": (None,), "default_location": "Dubai, United Arab Emirates"},
    {"ats": "smartrecruiters", "token": "brimore",   "company": "Brimore",     "regions": ("mena",), "sr_countries": (None,), "default_location": "Cairo, Egypt"},
    {"ats": "smartrecruiters", "token": "homzmart",  "company": "Homzmart",    "regions": ("mena",), "sr_countries": (None,), "default_location": "Cairo, Egypt"},
    {"ats": "bamboohr", "token": "nymcard", "company": "NymCard", "regions": ("mena",), "default_location": "Dubai, United Arab Emirates"},
    {"ats": "bamboohr", "token": "bosta",   "company": "Bosta",   "regions": ("mena",), "default_location": "Cairo, Egypt"},
    # ── Oracle Taleo career section: 382 Dubai government jobs (RTA, Dubai
    #     Culture, Department of Finance...). Token = host|section|portal. ──
    {"ats": "taleo", "token": "jobs.dubaicareers.ae|dubaicareers|40505100456", "company": "Dubai Government",
     "host": "jobs.dubaicareers.ae", "site": "dubaicareers", "portal": "40505100456",
     "regions": ("mena",), "default_location": "Dubai, United Arab Emirates"},
    # ── Phenom People: careers.g42.ai serves G42, Core42, Presight, Inception, CPX, Space42... ──
    {"ats": "phenom", "token": "careers.g42.ai|global/en", "company": "G42",
     "host": "careers.g42.ai", "site": "global/en", "regions": ("mena", "global"),
     "default_location": "Abu Dhabi, United Arab Emirates"},
    # ── Avature: Qatar Airways, via its robots.txt-declared sitemap only.
    #     (Emirates Group is also Avature but robots disallows its job list.) ──
    {"ats": "avature", "token": "careers.qatarairways.com|global", "company": "Qatar Airways",
     "host": "careers.qatarairways.com", "site": "global", "regions": ("mena", "global"),
     "default_location": "Doha, Qatar"},
]

# SmartRecruiters' list API has no JD text — each posting needs a detail call.
# The cap bounds those calls per board per run, so a huge enterprise board
# (Delivery Hero lists ~940 postings) costs at most this many detail requests.
_SR_DETAIL_CAP = 12

# SmartRecruiters server-side country filter per run region. Global keeps the
# legacy India-only behaviour; MENA fans out one list call per country because
# Delivery Hero alone has 940 postings and the newest 100 worldwide would hide
# the Gulf ones.
_SR_COUNTRIES = {
    "india": ("in",),
    "global": ("in",),   # unchanged legacy behaviour — do not alter global here
    "mena": ("ae", "sa", "eg", "qa", "kw", "bh", "om", "jo", "ma"),
}

# Oracle HCM: limit=100 and offset paging were verified live (2026-10-17); the
# careers UI itself uses 25. The list usually carries enough description for
# matching, so detail calls are the exception and are bounded per board.
_ORACLE_PAGE = 100
_ORACLE_MAX_JOBS = 200
_ORACLE_DETAIL_CAP = 12
_ORACLE_MIN_JD = 300   # a shorter list-level description is a teaser → fetch detail

# Workday CXS rejects limit > 20. The list has no JD, so detail is mandatory.
_WD_PAGE = 20
_WD_MAX_JOBS = 100
_WD_DETAIL_CAP = 15

# BambooHR's list has neither JD nor (usually) country; detail supplies both.
_BAMBOO_DETAIL_CAP = 15

# Teamtailor's /jobs.json holds 100 items per page.
_TT_MAX_PAGES = 5

# Oracle Taleo (Dubai Careers): 25 rows per page, newest first. Two thirds of the
# rows are "UAE Only", so they are dropped before the (expensive) detail calls.
# The detail-call caps below (Taleo, Phenom, Avature) bound requests per board;
# rate limiting is per host, so boards on different hosts do not slow each other.
_TALEO_MAX_PAGES = 4
_TALEO_DETAIL_CAP = 12
_TALEO_HEADERS = {
    "Content-Type": "application/json", "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest", "tz": "GMT+04:00",
    # Some Taleo hosts send a broken gzip body (httpx DecodingError seen).
    "Accept-Encoding": "identity",
}
_TALEO_PAGE_HEADERS = {"Accept": "text/html,application/xhtml+xml", "Accept-Encoding": "identity"}
_TALEO_DATE = re.compile(r"\d{2}/\d{2}/\d{4}$")
_TALEO_NATIONALS_ONLY = ("uae only", "nationals only")

# Phenom People sites (careers.g42.ai): 10 jobs per search page. Only the
# search-results and job/ paths are used; robots.txt disallows apply/jobcart/px-widgets.
_PHENOM_MAX_JOBS = 100
_PHENOM_DETAIL_CAP = 15
_PHENOM_DDO = re.compile(r"phApp\.ddo\s*=\s*(\{.*?\});\s*phApp", re.S)

# Avature (Qatar Airways): job URLs come from the sitemap, detail pages are HTML.
_AVATURE_DETAIL_CAP = 15
_AVATURE_MAX_SITEMAPS = 3
# Place words that mark a slug ("...-Ahmedabad-India") as clearly outside MENA.
# A slug with no recognisable place is kept and judged by the detail page.
_AVATURE_FOREIGN_WORDS = frozenset({
    "india", "poland", "malaysia", "china", "singapore", "vietnam", "thailand",
    "philippines", "indonesia", "pakistan", "bangladesh", "srilanka", "kenya",
    "nigeria", "uk", "usa", "germany", "france", "italy", "spain", "ireland",
    "canada", "australia", "japan", "korea", "brazil", "mexico", "turkey",
    "kong", "jfk", "lhr", "lax", "mia", "gru", "nce", "cdg", "fra", "sin", "bkk",
})

# Recruitee experience_code → our enum.
_RECRUITEE_LEVELS = {
    "entry_level": ExperienceLevel.entry, "student": ExperienceLevel.entry,
    "mid_level": ExperienceLevel.mid, "senior": ExperienceLevel.senior,
    "executive": ExperienceLevel.executive,
}

# SmartRecruiters experienceLevel.id (LinkedIn-style) → our enum.
_SR_LEVELS = {
    "internship": ExperienceLevel.entry, "entry_level": ExperienceLevel.entry,
    "associate": ExperienceLevel.mid, "mid_senior_level": ExperienceLevel.senior,
    "director": ExperienceLevel.lead, "executive": ExperienceLevel.executive,
}

INDIA_CITY_TOKENS = (
    "india", "bangalore", "bengaluru", "pune", "gurgaon", "gurugram",
    "noida", "delhi", "ncr", "hyderabad", "chennai", "mumbai", "kolkata",
    "ahmedabad", "jaipur", "indore", "kochi", "trivandrum", "chandigarh",
    "remote - india", "remote, india",
)
# Query tokenizer stopwords. Deliberately not mena_common.query_tokens: here "."
# is kept ("node.js") and "developer"/"engineer" are dropped, because they occur
# in nearly every tech JD and would make the any-token match accept everything.
_STOPWORDS = {"the", "and", "for", "with", "job", "jobs", "developer", "engineer", "role"}
_HTML = re.compile(r"<[^>]+>")
_WD_MULTI_LOCATION = re.compile(r"^\d+\s+locations?$", re.I)


class ATSAggregatorScraper(APIBaseScraper):
    platform = Platform.company_portal
    requires_key = False
    regions = {"india", "global", "mena"}
    rate_limit_per_minute = 60   # per host (see per_host_rate_limit)
    per_host_rate_limit = True
    MAX_CONCURRENT_BOARDS = 8    # cap on simultaneously in-flight board loads

    def __init__(self):
        super().__init__()
        self._all_jobs: Optional[list[dict]] = None  # loaded once per run, then filtered
        self._rr_start = 0   # mena only: which employer the next search starts with

    async def search_jobs(self, query: str, location: str = "India", max_results: int = 50,
                          credentials=None, region: str = "india") -> list[JobListingCreate]:
        await self._ensure_loaded(region)
        tokens = [t for t in re.split(r"[^a-z0-9.+#]+", query.lower()) if len(t) >= 3 and t not in _STOPWORDS]
        loc_low = (location or "").lower()
        # On a global run an empty/greedy location must not be read as "India".
        want_any_india = region == "india" and ((not loc_low) or loc_low in ("india", ""))

        def passes(job: dict) -> bool:
            # Boards carry roles abroad too: India/MENA runs drop what is outside
            # their region, global runs keep everything.
            if region == "india" and not self._is_india(job):
                return False
            if region == "mena" and not self._is_mena(job):
                return False
            if not self._location_ok(job, loc_low, want_any_india, region=region):
                return False
            return not tokens or self._query_ok(job, tokens)

        out: list[JobListingCreate] = []
        if region == "mena":
            # Discovery calls with a small cap (~8), and board-load order would
            # let the first big board (Binance) take every slot. Interleave
            # employers instead, newest role first within each.
            groups: dict[str, list[dict]] = {}
            for job in self._all_jobs or []:
                if passes(job):
                    groups.setdefault(job.get("company") or "", []).append(job)
            queues = [sorted(g, key=self._newest_first) for g in groups.values()]
            # Rotate the starting employer between calls: discovery makes several
            # small searches per run, and each would otherwise begin with the same
            # first few boards and never reach the later ones.
            if queues:
                k = self._rr_start % len(queues)
                queues = queues[k:] + queues[:k]
            # _is_new marks URLs as seen, so it is applied only to jobs we take.
            while queues and len(out) < max_results:
                for q in list(queues):
                    while q and not self._is_new(q[0]["source_url"]):
                        q.pop(0)
                    if q:
                        out.append(self._to_listing(q.pop(0)))
                        if len(out) >= max_results:
                            break
                    if not q:
                        queues.remove(q)
            self._rr_start += len(out)
        else:
            for job in self._all_jobs or []:
                if not passes(job):
                    continue
                if not self._is_new(job["source_url"]):
                    continue
                out.append(self._to_listing(job))
                if len(out) >= max_results:
                    break

        logger.info(f"ATS: returning {len(out)} jobs for '{query}' in {location}")
        return out

    # ── Loading (once per run) ──
    async def _ensure_loaded(self, region: str = "india"):
        if self._all_jobs is not None:
            return
        boards = self._boards(region)
        sem = asyncio.Semaphore(self.MAX_CONCURRENT_BOARDS)

        async def fetch(board: dict) -> list[dict]:
            async with sem:
                return await self._fetch_board(board, region)

        results = await asyncio.gather(*[fetch(b) for b in boards], return_exceptions=True)
        jobs: list[dict] = []
        for board, res in zip(boards, results):
            if isinstance(res, Exception):
                logger.warning(f"ATS board {board['ats']}/{board['token']} failed: {res}")
                continue
            jobs.extend(res)
        # One scraper instance lives for one run, and one run has one region, so
        # caching the region-scoped load is safe (an India run never fetches
        # MENA-only boards, and vice versa).
        self._all_jobs = jobs
        logger.info(f"ATS: loaded {len(jobs)} jobs from {len(boards)} boards")

    @staticmethod
    def _boards(region: str = "india") -> list[dict]:
        """Boards that serve `region`, deduped by (ats, token).

        Seeds are filtered by their `regions` tag (untagged seeds = india+global).
        Harvested boards are untagged and could hire anywhere, so they serve
        every region.
        """
        from services.ats_harvester import load_harvested
        seen: set[tuple[str, str]] = set()
        merged: list[dict] = []
        candidates = (
            [(b, b.get("regions", _DEFAULT_SEED_REGIONS)) for b in [*SEED_BOARDS, *MENA_SEED_BOARDS]]
            + [(b, None) for b in load_harvested()]
        )
        for b, regions in candidates:
            if regions is not None and region not in regions:
                continue
            key = (b["ats"], b["token"])
            if key not in seen:
                seen.add(key)
                merged.append(b)
        return merged

    async def _fetch_board(self, board: dict, region: str = "india") -> list[dict]:
        ats, token, company = board["ats"], board["token"], board["company"]
        dl = board.get("default_location", "India")
        if ats == "greenhouse":
            data = await self._get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", params={"content": "true"})
            return [self._norm_greenhouse(j, company, dl) for j in (data or {}).get("jobs", [])]
        if ats == "lever":
            data = await self._get_json(f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"})
            return [self._norm_lever(j, company, dl) for j in (data or [])]
        if ats == "ashby":
            data = await self._get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
            return [self._norm_ashby(j, company, dl) for j in (data or {}).get("jobs", [])]
        if ats == "workable":
            data = await self._get_json(
                f"https://apply.workable.com/api/v1/widget/accounts/{token}", params={"details": "true"}
            )
            return [self._norm_workable(j, company, dl) for j in (data or {}).get("jobs", [])]
        if ats == "smartrecruiters":
            return await self._fetch_smartrecruiters(token, company, region, dl, board.get("sr_countries"))
        if ats == "recruitee":
            data = await self._get_json(f"https://{token}.recruitee.com/api/offers/")
            return [self._norm_recruitee(j, company, dl) for j in (data or {}).get("offers", [])]
        if ats == "oracle_hcm":
            return await self._fetch_oracle(board, region, dl)
        if ats == "workday":
            return await self._fetch_workday(board, region, dl)
        if ats == "bamboohr":
            return await self._fetch_bamboohr(board, region, dl)
        if ats == "teamtailor":
            return await self._fetch_teamtailor(board, dl)
        if ats == "taleo":
            return await self._fetch_taleo(board, region, dl)
        if ats == "phenom":
            return await self._fetch_phenom(board, region, dl)
        if ats == "avature":
            return await self._fetch_avature(board, region, dl)
        return []

    @staticmethod
    def _board_parts(board: dict) -> dict:
        """host/tenant/site/portal for composite-token vendors. Seeds and harvested
        boards carry them as fields; an older store may only have the composite
        token, which split_token parses (one place defines the format)."""
        parts = split_token(board["ats"], board["token"])
        parts.update({k: board[k] for k in ("host", "tenant", "site", "portal") if board.get(k)})
        return parts

    @staticmethod
    def _in_region(location: str, region: str) -> bool:
        """Is a free-text location inside the run's region? Global keeps all."""
        if region == "mena":
            return mena.is_mena(location)
        if region == "india":
            return ATSAggregatorScraper._is_india({"location": location})
        return True

    @staticmethod
    def _is_tech_title(title: str) -> bool:
        low = (title or "").lower()
        return any(w in low for w in TECH_ROLE_WORDS)

    @classmethod
    def _tech_first(cls, items: list, title_of) -> list:
        """Stable sort putting tech titles first, so a per-board detail cap
        spends its calls on the roles this platform is looking for."""
        return sorted(items, key=lambda it: 0 if cls._is_tech_title(title_of(it)) else 1)

    # ── SmartRecruiters ──
    async def _fetch_smartrecruiters(self, token: str, company: str, region: str = "india",
                                     default_loc: str = "India", sr_countries: Optional[tuple] = None) -> list[dict]:
        # country filter server-side — enterprise boards carry thousands of global
        # postings and the newest 100 would otherwise drown out in-region roles.
        # A seed may override the fan-out with `sr_countries`; (None,) means one
        # unfiltered call, right for small boards (total <= 100) that would
        # otherwise cost nine list calls against the host's rate limit.
        countries = tuple(sr_countries) if sr_countries else _SR_COUNTRIES.get(region, ("in",))
        items: list[dict] = []
        seen_ids: set = set()
        for cc in countries:
            data = await self._get_json(
                f"https://api.smartrecruiters.com/v1/companies/{token}/postings",
                params={"limit": 100, **({"country": cc} if cc else {})},
            )
            for it in (data or {}).get("content", []):
                if it.get("id") in seen_ids:
                    continue
                seen_ids.add(it.get("id"))
                items.append(it)
        if len(countries) > 1 or sr_countries:
            # Cap applies per board, not per country: tech titles go first.
            items = self._tech_first(items, lambda it: it.get("name") or "")
        # The list API has no JD text; detail calls are the expensive part, so
        # they are capped per board (rate limiting is per host, see the class).
        out: list[dict] = []
        for it in items[:_SR_DETAIL_CAP]:
            detail = await self._get_json(
                f"https://api.smartrecruiters.com/v1/companies/{token}/postings/{it.get('id')}"
            )
            out.append(self._norm_smartrecruiters(it, detail or {}, company, token, default_loc))
        return out

    # ── Oracle HCM Candidate Experience ──
    async def _fetch_oracle(self, board: dict, region: str, default_loc: str) -> list[dict]:
        parts = self._board_parts(board)
        host, site = parts.get("host"), parts.get("site")
        if not host or not site:
            logger.warning(f"ATS oracle_hcm/{board['token']}: missing host/site")
            return []
        base = f"https://{host}/hcmRestApi/resources/latest"

        reqs: list[dict] = []
        offset = 0
        while offset < _ORACLE_MAX_JOBS:
            limit = min(_ORACLE_PAGE, _ORACLE_MAX_JOBS - offset)
            data = await self._get_json(f"{base}/recruitingCEJobRequisitions", params={
                "onlyData": "true",
                "expand": "requisitionList.secondaryLocations",
                "finder": f"findReqs;siteNumber={site},limit={limit},offset={offset},sortBy=POSTING_DATES_DESC",
            })
            head = ((data or {}).get("items") or [{}])[0]
            page = head.get("requisitionList") or []
            if not page:   # also what a WAF block (W4S-101) degrades to
                break
            reqs.extend(page)
            offset += len(page)
            if len(page) < limit or offset >= (head.get("TotalJobsCount") or 0):
                break

        kept: list[tuple[dict, str]] = []
        for req in reqs:
            loc = self._oracle_location(req, region, default_loc)
            if loc is not None:
                kept.append((req, loc))

        out: list[dict] = []
        need_detail: list[tuple[dict, str, str]] = []
        for req, loc in kept:
            jd = strip_html(" ".join(
                req.get(k) or "" for k in ("ShortDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")
            ))
            if len(jd) < _ORACLE_MIN_JD:
                need_detail.append((req, loc, jd))
            else:
                out.append(self._norm_oracle(req, board["company"], host, site, loc, jd))

        for req, loc, jd in self._tech_first(need_detail, lambda t: t[0].get("Title") or "")[:_ORACLE_DETAIL_CAP]:
            detail = await self._get_json(f"{base}/recruitingCEJobRequisitionDetails", params={
                "expand": "all", "onlyData": "true",
                "finder": f'ById;Id="{req.get("Id")}",siteNumber={site}',
            })
            d = ((detail or {}).get("items") or [{}])[0]
            full = strip_html(" ".join(
                d.get(k) or "" for k in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")
            ))
            out.append(self._norm_oracle(req, board["company"], host, site, loc, full or jd))
        return out

    @classmethod
    def _oracle_location(cls, req: dict, region: str, default_loc: str) -> Optional[str]:
        """Location to publish for a requisition, or None if it is outside the
        run's region. A role whose primary site is abroad but which also lists a
        regional secondary location is kept under that secondary location."""
        primary = (req.get("PrimaryLocation") or "").strip()
        secondary = [(s.get("Name") or "").strip() for s in req.get("secondaryLocations") or [] if isinstance(s, dict)]
        if region not in ("mena", "india"):
            return primary or next((n for n in secondary if n), "") or default_loc
        if primary and cls._in_region(primary, region):
            return primary
        for name in secondary:
            if name and cls._in_region(name, region):
                return name
        if not primary and not secondary and cls._in_region(default_loc, region):
            return default_loc
        # Bare ISO-2 country code ("AE") when the location text names no known place.
        if region == "mena" and mena.is_mena(req.get("PrimaryLocationCountry")):
            return primary or mena.MENA_COUNTRIES[mena.country_of(req["PrimaryLocationCountry"])]["name"]
        return None

    @staticmethod
    def _norm_oracle(req: dict, company: str, host: str, site: str, location: str, jd_text: str) -> dict:
        # Whitelist only: the detail payload also holds ExternalContactName,
        # ExternalContactEmail and HiringManager, which must never be stored.
        url = f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{req.get('Id')}"
        workplace = (req.get("WorkplaceType") or req.get("WorkplaceTypeCode") or "").lower()
        return {
            "title": (req.get("Title") or "").strip(), "company": company,
            "location": location, "source_url": url, "apply_url": url,
            "jd_text": jd_text, "posted_at": _parse_iso(req.get("PostedDate")),
            "remote": "remote" in workplace,
        }

    # ── Workday CXS ──
    async def _fetch_workday(self, board: dict, region: str, default_loc: str) -> list[dict]:
        parts = self._board_parts(board)
        host, tenant, site = parts.get("host"), parts.get("tenant"), parts.get("site")
        if not (host and tenant and site):
            logger.warning(f"ATS workday/{board['token']}: missing host/tenant/site")
            return []
        base = f"https://{host}/wday/cxs/{tenant}/{site}"

        postings: list[dict] = []
        for offset in range(0, _WD_MAX_JOBS, _WD_PAGE):
            data = await self._post_json(f"{base}/jobs", {
                "appliedFacets": {}, "limit": _WD_PAGE, "offset": offset, "searchText": "",
            })
            page = (data or {}).get("jobPostings") or []
            postings.extend(page)
            if len(page) < _WD_PAGE or offset + _WD_PAGE >= ((data or {}).get("total") or 0):
                break

        # Pre-filter on the list's short location text. "N Locations" is
        # ambiguous, so it is resolved through the detail call below.
        kept = [
            p for p in postings
            if self._in_region(p.get("locationsText") or "", region)
            or _WD_MULTI_LOCATION.match((p.get("locationsText") or "").strip())
        ]
        out: list[dict] = []
        for p in self._tech_first(kept, lambda p: p.get("title") or "")[:_WD_DETAIL_CAP]:
            detail = await self._get_json(f"{base}{p.get('externalPath')}")
            info = (detail or {}).get("jobPostingInfo")
            if not info:
                continue
            job = self._norm_workday(p, info, board["company"], host, site, default_loc)
            if self._in_region(job["location"], region):
                out.append(job)
        return out

    @staticmethod
    def _norm_workday(posting: dict, info: dict, company: str, host: str, site: str,
                      default_loc: str = "India") -> dict:
        loc = (info.get("location") or posting.get("locationsText") or "").strip()
        country = info.get("country")
        country = (country.get("descriptor") if isinstance(country, dict) else country) or ""
        # "Beirut" alone cannot be region-checked reliably for every city;
        # appending the country makes the location self-describing.
        if country and country.lower() not in loc.lower():
            loc = f"{loc}, {country}" if loc else country
        url = info.get("externalUrl") or f"https://{host}/{site}{posting.get('externalPath') or ''}"
        return {
            "title": (info.get("title") or posting.get("title") or "").strip(), "company": company,
            "location": loc or default_loc, "source_url": url, "apply_url": url,
            "jd_text": strip_html(info.get("jobDescription")),
            "posted_at": _parse_iso(info.get("startDate"))
            or _parse_workday_posted(info.get("postedOn") or posting.get("postedOn") or ""),
            "remote": "remote" in loc.lower(),
        }

    # ── BambooHR ──
    async def _fetch_bamboohr(self, board: dict, region: str, default_loc: str) -> list[dict]:
        token, company = board["token"], board["company"]
        data = await self._get_json(f"https://{token}.bamboohr.com/careers/list")
        items = (data or {}).get("result") or []
        # A board whose own default location is in the region is treated as local
        # even when the list gives no country (Toters: every row is "Metn, Metn").
        board_local = "default_location" in board and self._in_region(default_loc, region)

        kept: list[dict] = []
        for it in items:
            loc = self._bamboo_list_location(it)
            if not loc:
                kept.append(it)   # nothing to judge by → resolve through the detail call
            elif self._in_region(loc, region) or (board_local and not (it.get("atsLocation") or {}).get("country")):
                kept.append(it)

        out: list[dict] = []
        for it in self._tech_first(kept, lambda i: i.get("jobOpeningName") or "")[:_BAMBOO_DETAIL_CAP]:
            detail = await self._get_json(f"https://{token}.bamboohr.com/careers/{it.get('id')}/detail")
            opening = (((detail or {}).get("result") or {}).get("jobOpening")) or {}
            if not opening or opening.get("jobOpeningStatus") != "Open":
                continue
            job = self._norm_bamboohr(it, opening, company, token, default_loc)
            if self._in_region(job["location"], region):
                out.append(job)
        return out

    @staticmethod
    def _bamboo_list_location(it: dict) -> str:
        loc = it.get("location") or {}
        ats_loc = it.get("atsLocation") or {}
        parts: list[str] = []
        for p in (loc.get("city"), loc.get("state"), ats_loc.get("country")):
            if p and p not in parts:   # Toters sends city == state ("Metn", "Metn")
                parts.append(p)
        return ", ".join(parts)

    @classmethod
    def _norm_bamboohr(cls, it: dict, opening: dict, company: str, token: str,
                       default_loc: str = "India") -> dict:
        loc = opening.get("location") or {}
        parts: list[str] = []
        for p in (loc.get("city"), loc.get("addressCountry")):
            if p and p not in parts:
                parts.append(p)
        location = ", ".join(parts) or cls._bamboo_list_location(it) or default_loc
        url = opening.get("jobOpeningShareUrl") or f"https://{token}.bamboohr.com/careers/{it.get('id')}"
        return {
            "title": (opening.get("jobOpeningName") or it.get("jobOpeningName") or "").strip(),
            "company": company, "location": location,
            "source_url": url, "apply_url": url,
            "jd_text": strip_html(opening.get("description")),
            "posted_at": _parse_iso(opening.get("datePosted")),
            # locationType (0/1/2) could not be decoded from live data — only
            # on-site (0) and one unknown value (2) were observed — so rely on
            # isRemote alone rather than guess.
            "remote": str(it.get("isRemote")).lower() == "true",
        }

    # ── Teamtailor ──
    async def _fetch_teamtailor(self, board: dict, default_loc: str) -> list[dict]:
        host = self._board_parts(board).get("host") or board["token"]
        out: list[dict] = []
        url: Optional[str] = f"https://{host}/jobs.json"
        for _ in range(_TT_MAX_PAGES):
            feed = await self._get_json(url)
            if not isinstance(feed, dict):
                break
            out.extend(self._norm_teamtailor(i, board["company"], default_loc) for i in feed.get("items") or [])
            url = feed.get("next_url")
            if not url:
                break
        return out

    @staticmethod
    def _norm_teamtailor(item: dict, company: str, default_loc: str = "India") -> dict:
        posting = item.get("_jobposting")
        if isinstance(posting, str):   # some feeds embed the JSON-LD as a string
            try:
                posting = json.loads(posting)
            except Exception:
                posting = None
        fields = map_job_posting(posting) if isinstance(posting, dict) else {}
        location = fields.get("location") or default_loc
        job = {
            "title": (fields.get("title") or item.get("title") or "").strip(), "company": company,
            "location": location, "source_url": item.get("url") or "",
            "apply_url": item.get("url") or "",
            "jd_text": fields.get("jd_text") or strip_html(item.get("content_html")),
            "posted_at": fields.get("posted_at") or _parse_iso(item.get("date_published")),
            "remote": bool(fields.get("is_remote_friendly")) or "remote" in location.lower(),
        }
        if fields.get("salary_min") or fields.get("salary_max"):
            # Boards quote monthly pay; the repo stores annual figures.
            unit = fields.get("salary_unit")
            job["salary_min"] = mena.annualize(fields.get("salary_min"), unit)
            job["salary_max"] = mena.annualize(fields.get("salary_max"), unit)
            job["salary_currency"] = fields.get("salary_currency")
        return job

    # ── Oracle Taleo career sections (Dubai Careers) ──
    @staticmethod
    def _taleo_search_body(page: int) -> dict:
        """Empty keyword, newest first: the board cache is region-wide (one load
        per run), not per query."""
        def empty(i: str) -> dict:
            return {"id": i, "selectedValues": []}
        return {
            "multilineEnabled": False,
            "sortingSelection": {"sortBySelectionParam": "3", "ascendingSortingOrder": "false"},
            "fieldData": {"fields": {"KEYWORD": "", "LOCATION": ""}, "valid": True},
            "filterSelectionParam": {"searchFilterSelections": [
                empty("POSTING_DATE"), empty("LOCATION"), empty("JOB_FIELD")]},
            "advancedSearchFiltersSelectionParam": {"searchFilterSelections": [
                empty(i) for i in ("ORGANIZATION", "LOCATION", "JOB_FIELD", "JOB_NUMBER", "URGENT_JOB",
                                   "EMPLOYEE_STATUS", "STUDY_LEVEL", "WILL_TRAVEL", "JOB_SHIFT")]},
            "pageNo": page,
        }

    @staticmethod
    def _taleo_decode_fields(page_html: str) -> Optional[list[str]]:
        """The jobdetail page has no JSON-LD: everything sits in the hidden
        `initialHistory` input, a `!|!`-separated list of URL-encoded fields.
        HTML-bearing fields start with `!*!`; Taleo escapes ":" as a backslash-colon."""
        tag = re.search(r'<input[^>]*name="initialHistory"[^>]*>', page_html or "", re.S)
        value = re.search(r'value="([^"]*)"', tag.group(0), re.S) if tag else None
        if not value:
            return None

        def decode(f: str) -> str:
            return strip_html(unquote(f.replace("!*!", "")).replace("\\:", ":"))

        return [decode(f) for f in value.group(1).split("!|!")]

    @staticmethod
    def _taleo_nationals_only(nationality: str) -> bool:
        low = (nationality or "").lower()
        return any(k in low for k in _TALEO_NATIONALS_ONLY)

    async def _fetch_taleo(self, board: dict, region: str, default_loc: str) -> list[dict]:
        from config import settings
        parts = self._board_parts(board)
        host, site, portal = parts.get("host"), parts.get("site"), parts.get("portal")
        if not (host and site and portal):
            logger.warning(f"ATS taleo/{board['token']}: missing host/site/portal")
            return []
        if not self._in_region(default_loc, region):
            return []
        search_url = f"https://{host}/careersection/rest/jobboard/searchjobs?lang=en&portal={portal}"

        reqs: list[dict] = []
        for page in range(1, _TALEO_MAX_PAGES + 1):
            data = await self._post_json(search_url, self._taleo_search_body(page), headers=_TALEO_HEADERS)
            rows = (data or {}).get("requisitionList") or []
            if not rows:
                break
            reqs.extend(rows)
            if len(reqs) >= (((data or {}).get("pagingData") or {}).get("totalCount") or 0):
                break

        # Citizens-only rows are unusable for expats and are two thirds of the
        # board; dropping them here saves two thirds of the detail calls.
        drop_nationals = settings.MENA_EXCLUDE_NATIONALS_ONLY
        kept: list[tuple[dict, str]] = []
        for req in reqs:
            col = req.get("column") or []
            title = (col[0] if col else "") or ""
            nationality = col[2] if len(col) > 2 else ""
            if drop_nationals and (self._taleo_nationals_only(nationality) or mena.nationals_only(title)):
                continue
            if req.get("contestNo"):
                kept.append((req, title))

        out: list[dict] = []
        for req, _title in self._tech_first(kept, lambda t: t[1])[:_TALEO_DETAIL_CAP]:
            contest = str(req["contestNo"])
            url = f"https://{host}/careersection/{site}/jobdetail.ftl?job={contest}&lang=en"
            page_html = await self._get_text(url, headers=_TALEO_PAGE_HEADERS)
            fields = self._taleo_decode_fields(page_html or "")
            if not fields:
                continue
            job = self._norm_taleo(req, fields, board["company"], url, default_loc, drop_nationals)
            if job:
                out.append(job)
        return out

    @classmethod
    def _norm_taleo(cls, req: dict, fields: list[str], company: str, url: str,
                    default_loc: str, drop_nationals: bool = True) -> Optional[dict]:
        """Map decoded `initialHistory` fields to a job dict, or None (closed,
        citizens-only, or unparseable).

        The layout is positional from the contest number (title just before it,
        description +2, qualifications +4, organization +8, nationality +20,
        posted +28, closing +30), so the posted-date slot is asserted first and
        a layout change degrades to title + longest text instead of garbage."""
        contest = str(req.get("contestNo") or "")
        col = req.get("column") or []
        list_title = (col[0] if col else "") or ""
        list_nationality = col[2] if len(col) > 2 else ""
        i = fields.index(contest) if contest in fields else -1

        def at(offset: int) -> str:
            return fields[i + offset] if 0 <= i + offset < len(fields) else ""

        title = (at(-1) if i > 0 else "") or list_title.strip()
        if i >= 0 and _TALEO_DATE.match(at(28)):
            description, qualifications = at(2), at(4)
            organization, nationality = at(8), at(20)
            posted_text, closing_text = at(28), at(30)
        else:
            logger.warning(f"ATS taleo: unexpected jobdetail layout for {contest}; using title + longest text only")
            description = next((f for f in fields[max(i, 0):] if len(f) > 200), "")
            qualifications = ""
            organization, nationality = "", list_nationality
            posted_text, closing_text = (col[1] if len(col) > 1 else ""), ""

        closing = _parse_ddmmyyyy(closing_text)
        if closing and closing.date() < datetime.utcnow().date():
            return None
        jd = scrub_contacts(f"{description} {qualifications}".strip())
        if drop_nationals and (cls._taleo_nationals_only(nationality) or cls._taleo_nationals_only(list_nationality)
                               or mena.nationals_only(title, jd)):
            return None
        return {
            "title": title, "company": organization or company,
            "location": default_loc, "source_url": url, "apply_url": url,
            "jd_text": jd, "posted_at": _parse_ddmmyyyy(posted_text),
            "remote": False, "source_job_id": contest,
        }

    # ── Phenom People career sites (G42 group) ──
    @staticmethod
    def _phenom_search_data(page_html: str) -> Optional[dict]:
        """`ddo.eagerLoadRefineSearch` from the search page's inline script, or
        None if the markup changed."""
        m = _PHENOM_DDO.search(page_html or "")
        if not m:
            return None
        try:
            data = json.loads(m.group(1)).get("eagerLoadRefineSearch")
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    async def _fetch_phenom(self, board: dict, region: str, default_loc: str) -> list[dict]:
        parts = self._board_parts(board)
        host, site = parts.get("host"), parts.get("site")
        if not host or not site:
            logger.warning(f"ATS phenom/{board['token']}: missing host/site")
            return []
        html_headers = {"Accept": "text/html,application/xhtml+xml"}

        listed: list[dict] = []
        start, total = 0, None
        while start < _PHENOM_MAX_JOBS and (total is None or start < total):
            page_html = await self._get_text(f"https://{host}/{site}/search-results?from={start}&s=1", headers=html_headers)
            data = self._phenom_search_data(page_html)
            if data is None:
                if start == 0:
                    logger.warning(f"ATS phenom/{board['token']}: phApp.ddo not found (site changed?)")
                break
            total = data.get("totalHits") or 0
            rows = ((data.get("data") or {}).get("jobs")) or []
            if not rows:
                break
            listed.extend(rows)
            start += len(rows)

        # A job with no place at all is judged by the board's own location.
        kept = [j for j in listed
                if j.get("jobId") and self._in_region(self._phenom_location(j) or default_loc, region)]
        out: list[dict] = []
        for j in self._tech_first(kept, lambda j: j.get("title") or "")[:_PHENOM_DETAIL_CAP]:
            url = f"https://{host}/{site}/job/{j['jobId']}"
            detail = await self._get_text(url, headers=html_headers)
            posting = find_job_posting(detail or "")
            out.append(self._norm_phenom(j, map_job_posting(posting) if posting else {}, board["company"], url, default_loc))
        return out

    @staticmethod
    def _phenom_location(job: dict) -> str:
        """`cityStateCountry` reads " , United States" when the city is unknown."""
        loc = job.get("cityStateCountry") or job.get("location") or ""
        return loc.strip(" ,\t")

    @classmethod
    def _norm_phenom(cls, listed: dict, fields: dict, company: str, url: str, default_loc: str) -> dict:
        jd = fields.get("jd_text") or listed.get("descriptionTeaser") or ""
        if re.search(r"</?[a-zA-Z][^>]*>", jd):
            jd = strip_html(jd)   # Phenom double-escapes: &lt;div&gt; survives one strip pass
        location = cls._phenom_location(listed) or default_loc
        return {
            "title": (fields.get("title") or listed.get("title") or "").strip(),
            "company": fields.get("company") or company,
            "location": location, "source_url": url, "apply_url": url,
            "jd_text": scrub_contacts(jd),
            "posted_at": fields.get("posted_at") or _parse_phenom_date(listed.get("postedDate")),
            "remote": "remote" in location.lower() or bool(fields.get("is_remote_friendly")),
            "source_job_id": str(listed.get("jobId") or ""),
        }

    # ── Avature (Qatar Airways) ──
    @staticmethod
    def _avature_entries(xml: str, host: str, site: str) -> list[tuple[str, str, int, str]]:
        """(url, slug, id, lastmod) for every `/JobDetail/{slug}/{id}` URL in a
        sitemap. The bare /JobDetail and /JobDetailApplied pages carry no id and
        are skipped."""
        pat = re.compile(rf"^https://{re.escape(host)}/{re.escape(site)}/JobDetail/([^/<]+)/(\d+)$")
        out = []
        for url, lastmod in re.findall(r"<url>\s*<loc>([^<]+)</loc>(?:\s*<lastmod>([^<]+)</lastmod>)?", xml or ""):
            m = pat.match(url.strip())
            if m:
                out.append((url.strip(), m.group(1), int(m.group(2)), lastmod or ""))
        return out

    @staticmethod
    def _avature_slug_title(slug: str) -> str:
        return unquote(slug).replace("-", " ").strip()

    @classmethod
    def _avature_slug_foreign(cls, slug: str) -> bool:
        """True when the slug ends in a clearly non-MENA place ("...-Ahmedabad-India").
        A slug with no recognisable place is not foreign: most Doha roles name none."""
        words = [w.lower() for w in unquote(slug).split("-") if w]
        tail = words[-3:]
        if mena.country_of(" ".join(tail)) is not None:
            return False
        return any(w in _AVATURE_FOREIGN_WORDS for w in tail)

    async def _fetch_avature(self, board: dict, region: str, default_loc: str) -> list[dict]:
        from config import settings
        parts = self._board_parts(board)
        host, site = parts.get("host"), parts.get("site")
        if not host or not site:
            logger.warning(f"ATS avature/{board['token']}: missing host/site")
            return []
        xml_headers = {"Accept": "application/xml,text/xml"}
        index = await self._get_text(f"https://{host}/{site}/sitemap_index.xml", headers=xml_headers)
        if not index:
            return []
        if "<sitemapindex" in index:
            children = [u.strip() for u in re.findall(r"<loc>([^<]+)</loc>", index)
                        if u.strip().endswith(".xml") and u.strip().startswith(f"https://{host}/")]
            sitemaps = [await self._get_text(u, headers=xml_headers) for u in children[:_AVATURE_MAX_SITEMAPS]]
        else:
            sitemaps = [index]
        entries: list[tuple[str, str, int, str]] = []
        for xml in sitemaps:
            entries.extend(self._avature_entries(xml or "", host, site))

        drop_nationals = settings.MENA_EXCLUDE_NATIONALS_ONLY
        kept = []
        for entry in entries:
            if drop_nationals and mena.nationals_only(self._avature_slug_title(entry[1])):
                continue
            if region == "mena" and self._avature_slug_foreign(entry[1]):
                continue
            kept.append(entry)
        # The live sitemap lists job pages without <lastmod>, so recency falls
        # back to the numeric id (requisitions are numbered upward over time).
        kept.sort(key=lambda e: (e[3], e[2]), reverse=True)
        picked = self._tech_first(kept, lambda e: self._avature_slug_title(e[1]))[:_AVATURE_DETAIL_CAP]

        out: list[dict] = []
        for url, slug, _jid, lastmod in picked:
            page_html = await self._get_text(url, headers={"Accept": "text/html,application/xhtml+xml"})
            if not page_html:
                continue
            job = self._norm_avature(page_html, url, slug, lastmod, board["company"], default_loc)
            if job and self._in_region(job["location"], region):
                out.append(job)
        return out

    @staticmethod
    def _avature_parse(page_html: str) -> dict:
        """Label/value fields of an Avature job page (no JSON-LD to lean on).

        Every field is `field > [label] + value`. Labelled fields ("Ref #",
        "Location", "Job family") come first and unlabelled blocks follow: a
        MultipleDataSetFields list (holds "Closing Date:"), the description
        sections, and a bare apply URL. Returns {labels, closing, body}; body is
        every unlabelled text block with tags stripped, minus bare URLs."""
        field_re = re.compile(
            r'<div class="article__content__view__field\b[^"]*"[^>]*>\s*'
            r'(?:<div class="article__content__view__field__label[^"]*"[^>]*>\s*(.*?)\s*</div>\s*)?'
            r'<div class="article__content__view__field__value[^"]*"[^>]*>(.*?)</div>', re.S)
        pairs = field_re.findall(page_html or "")
        if not pairs:
            # Markup shifted: fall back to pairing the first N values to the N labels.
            labels = re.findall(r'class="article__content__view__field__label[^"]*"[^>]*>\s*(.*?)\s*</', page_html or "", re.S)
            values = re.findall(r'class="article__content__view__field__value[^"]*"[^>]*>(.*?)</div>', page_html or "", re.S)
            pairs = [(labels[n] if n < len(labels) else "", v) for n, v in enumerate(values)]
        labels_out: dict[str, str] = {}
        body: list[str] = []
        closing = None
        for label, value in pairs:
            if label:
                labels_out[strip_html(label)] = strip_html(value)
                continue
            if "MultipleDataSetField" in value:
                m = re.search(r"Closing Date:\s*</span>\s*<span[^>]*>\s*([\d-]+)", value)
                if m:
                    closing = _parse_iso(m.group(1))
                continue
            text = strip_html(value)
            if text and not re.fullmatch(r"https?://\S+", text):
                body.append(text)
        return {"labels": labels_out, "closing": closing, "body": " ".join(body)}

    @classmethod
    def _norm_avature(cls, page_html: str, url: str, slug: str, lastmod: str,
                      company: str, default_loc: str) -> Optional[dict]:
        parsed = cls._avature_parse(page_html)
        labels = parsed["labels"]
        if parsed["closing"] and parsed["closing"].date() < datetime.utcnow().date():
            return None
        heading = re.search(r"<h1[^>]*>(.*?)</h1>", page_html, re.S) or re.search(r"<h2[^>]*>(.*?)</h2>", page_html, re.S)
        title = (strip_html(heading.group(1)) if heading else "") or cls._avature_slug_title(slug)
        # "Qatar-Doha" is Country-City.
        country, _, city = (labels.get("Location") or "").partition("-")
        location = ", ".join(p.strip() for p in (city, country) if p.strip()) or default_loc
        jd = parsed["body"]
        if not jd:
            og = re.search(r'<meta property="og:description" content="([^"]*)"', page_html)
            jd = strip_html(_htmllib.unescape(og.group(1))) if og else ""
        posting = find_job_posting(page_html)
        posted = map_job_posting(posting).get("posted_at") if posting else None
        return {
            "title": title, "company": company, "location": location,
            "source_url": url, "apply_url": url, "jd_text": scrub_contacts(jd),
            "posted_at": posted or _parse_iso(lastmod),
            "remote": "remote" in location.lower(),
            "source_job_id": labels.get("Ref #") or None,
        }

    # ── Per-ATS normalization to a common dict ──
    @staticmethod
    def _norm_greenhouse(j: dict, company: str, default_loc: str = "India") -> dict:
        loc = (j.get("location") or {}).get("name", "")
        content = _HTML.sub(" ", j.get("content") or "").replace("&amp;", "&").replace("&nbsp;", " ")
        return {
            "title": (j.get("title") or "").strip(), "company": j.get("company_name") or company,
            "location": loc or default_loc, "source_url": j.get("absolute_url") or "",
            "apply_url": j.get("absolute_url") or "", "jd_text": content,
            "posted_at": _parse_iso(j.get("updated_at")), "remote": "remote" in loc.lower(),
        }

    @staticmethod
    def _norm_lever(j: dict, company: str, default_loc: str = "India") -> dict:
        cats = j.get("categories") or {}
        loc = cats.get("location") or ""
        return {
            "title": (j.get("text") or "").strip(), "company": company,
            "location": loc or default_loc, "source_url": j.get("hostedUrl") or "",
            "apply_url": j.get("applyUrl") or j.get("hostedUrl") or "",
            "jd_text": j.get("descriptionPlain") or j.get("description") or "",
            "posted_at": _parse_epoch_ms(j.get("createdAt")),
            "remote": (j.get("workplaceType") or "").lower() == "remote",
        }

    @staticmethod
    def _norm_ashby(j: dict, company: str, default_loc: str = "India") -> dict:
        loc = j.get("location") or ""
        return {
            "title": (j.get("title") or "").strip(), "company": company,
            "location": loc or default_loc, "source_url": j.get("jobUrl") or "",
            "apply_url": j.get("applyUrl") or j.get("jobUrl") or "",
            "jd_text": j.get("descriptionPlain") or "",
            "posted_at": _parse_iso(j.get("publishedAt")), "remote": bool(j.get("isRemote")),
        }

    @staticmethod
    def _norm_workable(j: dict, company: str, default_loc: str = "India") -> dict:
        loc = ", ".join(p for p in (j.get("city"), j.get("state"), j.get("country")) if p)
        return {
            "title": (j.get("title") or "").strip(), "company": company,
            "location": loc or default_loc, "source_url": j.get("url") or "",
            "apply_url": j.get("application_url") or j.get("url") or "",
            "jd_text": strip_html(j.get("description")),
            "posted_at": _parse_iso(j.get("published_on") or j.get("created_at")),
            "remote": bool(j.get("telecommuting")),
        }

    @staticmethod
    def _sr_location(it: dict) -> str:
        loc = it.get("location") or {}
        country = (loc.get("country") or "").lower()
        if country == "in":
            country_name = "India"
        else:
            # "ae" → "United Arab Emirates" so MENA filters can resolve the city.
            country_name = mena.MENA_COUNTRIES.get(country.upper(), {}).get("name") or country.upper()
        parts = [loc.get("city") or "", country_name]
        return ", ".join(p for p in parts if p)

    def _norm_smartrecruiters(self, it: dict, detail: dict, company: str, token: str,
                              default_loc: str = "India") -> dict:
        sections = ((detail.get("jobAd") or {}).get("sections") or {})
        jd = " ".join(
            strip_html((sections.get(k) or {}).get("text"))
            for k in ("jobDescription", "qualifications", "additionalInformation")
        ).strip()
        url = f"https://jobs.smartrecruiters.com/{token}/{it.get('id')}"
        return {
            "title": (it.get("name") or "").strip(),
            "company": (it.get("company") or {}).get("name") or company,
            "location": self._sr_location(it) or default_loc,
            "source_url": url, "apply_url": url, "jd_text": jd,
            "posted_at": _parse_iso(it.get("releasedDate")),
            "remote": bool((it.get("location") or {}).get("remote")),
            "experience_level": _SR_LEVELS.get(((it.get("experienceLevel") or {}).get("id") or "")),
        }

    @staticmethod
    def _norm_recruitee(j: dict, company: str, default_loc: str = "India") -> dict:
        loc = j.get("location") or ", ".join(p for p in (j.get("city"), j.get("country")) if p)
        jd = strip_html(f"{j.get('description') or ''} {j.get('requirements') or ''}")
        return {
            "title": (j.get("title") or "").strip(), "company": company,
            "location": loc or default_loc, "source_url": j.get("careers_url") or "",
            "apply_url": j.get("careers_url") or "", "jd_text": jd,
            "posted_at": _parse_iso(j.get("created_at")),
            "remote": str(j.get("remote")).lower() in ("true", "fully"),
            "experience_level": _RECRUITEE_LEVELS.get(j.get("experience_code") or ""),
        }

    # ── Filtering ──
    @staticmethod
    def _newest_first(job: dict):
        posted = job.get("posted_at")
        return (posted is None, -posted.timestamp() if posted else 0)

    @staticmethod
    def _is_india(job: dict) -> bool:
        loc = (job.get("location") or "").lower()
        return any(tok in loc for tok in INDIA_CITY_TOKENS)

    @staticmethod
    def _is_mena(job: dict) -> bool:
        loc = job.get("location") or ""
        if mena.is_mena(loc):
            return True
        # Remote roles qualify only when explicitly open to the region.
        return bool(job.get("remote")) and mena.names_mena_region(loc)

    @staticmethod
    def _location_ok(job: dict, loc_low: str, want_any_india: bool, region: str = "india") -> bool:
        if region == "mena":
            # Match on country, not city substring: "United Arab Emirates" must
            # match a "Dubai" job and vice versa. A search location that names
            # no MENA country does not narrow further. A region-wide remote role
            # ("Remote - EMEA": remote, no single country) is open to every MENA
            # country, so it surfaces on whichever country is searched first
            # (the per-run URL dedup then keeps it from repeating).
            return (
                mena.same_country(job.get("location"), loc_low)
                or not mena.is_mena(loc_low)
                or (bool(job.get("remote")) and mena.country_of(job.get("location")) is None)
            )
        if want_any_india:
            return True
        job_loc = (job.get("location") or "").lower()
        # match the requested city, or surface remote roles on any city query
        return loc_low.split(",")[0].strip() in job_loc or job.get("remote", False)

    @staticmethod
    def _query_ok(job: dict, tokens: list[str]) -> bool:
        hay = f"{job.get('title', '')} {job.get('jd_text', '')}".lower()
        return any(tok in hay for tok in tokens)

    def _to_listing(self, job: dict) -> JobListingCreate:
        jd = re.sub(r"\s+", " ", job.get("jd_text") or "").strip()
        return JobListingCreate(
            title=job["title"] or "Role",
            company=job["company"],
            location=job["location"],
            work_mode="remote" if job.get("remote") else None,
            is_remote_friendly=job.get("remote", False),
            experience_level=job.get("experience_level"),
            salary_min=job.get("salary_min"),
            salary_max=job.get("salary_max"),
            # INR stays the default for everything that is not a MENA location.
            salary_currency=job.get("salary_currency") or mena.currency_for(job["location"]) or "INR",
            jd_text=jd or job["title"],
            source_platform=self.platform,
            source_url=job["source_url"],
            apply_url=job.get("apply_url") or job["source_url"],
            posted_at=job.get("posted_at"),
            source_job_id=job.get("source_job_id") or None,
        )


def _parse_iso(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _parse_ddmmyyyy(value) -> Optional[datetime]:
    """Taleo dates ("16/10/2026")."""
    try:
        return datetime.strptime(str(value).strip(), "%d/%m/%Y")
    except Exception:
        return None


def _parse_phenom_date(value) -> Optional[datetime]:
    """"2026-04-28T07:20:13.000+0000": Python 3.10 rejects the colon-less offset."""
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(value or ""))
    return _parse_iso(text)


def _parse_epoch_ms(value) -> Optional[datetime]:
    try:
        return datetime.utcfromtimestamp(int(value) / 1000)
    except Exception:
        return None


def _parse_workday_posted(text: str) -> Optional[datetime]:
    """Workday's relative "Posted 18 Days Ago" / "Posted 30+ Days Ago" text.

    BaseScraper.parse_relative_date does not handle the "30+" form, hence this
    helper. "30+" is a floor, so the date is approximate for old postings.
    """
    low = (text or "").lower()
    now = datetime.utcnow()
    if "today" in low:
        return now
    if "yesterday" in low:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*day", low)
    return now - timedelta(days=int(m.group(1))) if m else None
