"""
ATS token harvester — grows the ATS aggregator's company list automatically.

Greenhouse/Lever/Ashby jobs are reached by a per-company *board token*. Rather
than hand-maintain that list forever, this harvester mines the apply/source URLs
we already collect (Wellfound, YC, RemoteOK, Google-for-Jobs, etc. routinely
link straight to `boards.greenhouse.io/<token>`, `jobs.lever.co/<token>`,
`jobs.ashbyhq.com/<token>`), extracts new tokens, validates that each board
resolves to real jobs, and persists it to data/ats_boards.json.

The ATS scraper then loads SEED_BOARDS ∪ harvested boards, so coverage compounds
every discovery run with zero manual upkeep. Local-first: a JSON file, no DB
migration, no new infra.

Most vendors need one token, but Oracle HCM (host + site), Workday (host +
tenant + site), Teamtailor (custom career-site host), Taleo (host + career
section + portal id), Phenom and Avature (host + site path) need more. Those
are stored as one canonical *composite token* string: `host|site`,
`host|tenant|site`, `host`, `host|section|portal`, `host|site` and `host|site`.
Taleo, Phenom and Avature have no URL pattern here: their ids are not in apply
URLs, so scripts/detect_ats.py finds them from a careers page instead. The format is defined only here (`_canonical`
builds it, `split_token` parses it) so the scraper and harvester cannot drift
apart. Hosts are lowercased; site names keep their case because Oracle/Workday
site ids are case-sensitive.
"""
import asyncio
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

_STORE = Path(__file__).resolve().parent.parent / "data" / "ats_boards.json"
_lock = threading.Lock()

# Tokens that are ATS infrastructure, not a company board.
_TOKEN_BLOCKLIST = {"embed", "job_board", "jobs", "api", "v1", "v0", "boards",
                    "posting-api", "job-board", "www", "for", "share", "list",
                    "j", "widget", "accounts", "careers", "offers",
                    # BambooHR / Teamtailor marketing & app hosts, not company boards.
                    "resources", "app.teamtailor.com", "www.teamtailor.com",
                    "support.teamtailor.com", "docs.teamtailor.com",
                    "developer.teamtailor.com", "partner.teamtailor.com",
                    "career.teamtailor.com"}
# Workday URL path segments that are API/infra, not a careers-site name.
_WD_SITE_BLOCKLIST = {"wday", "job", "jobs"}

# URL → (ats, token). Ordered; first match wins. Tokens are the URL path segment
# right after the ATS host (Greenhouse also supports an ?for=<token> embed form).
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"(?:job-)?boards(?:-api)?\.greenhouse\.io/(?:embed/job_board\?for=|v1/boards/)?([a-z0-9][a-z0-9._-]*)", re.I)),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board\?for=([a-z0-9][a-z0-9._-]*)", re.I)),
    ("lever",      re.compile(r"(?:jobs\.lever\.co|api\.lever\.co/v0/postings)/([a-z0-9][a-z0-9._-]*)", re.I)),
    ("ashby",      re.compile(r"(?:jobs\.ashbyhq\.com|api\.ashbyhq\.com/posting-api/job-board)/([a-z0-9][a-z0-9._-]*)", re.I)),
    ("workable",   re.compile(r"apply\.workable\.com/(?:api/v1/widget/accounts/)?([a-z0-9][a-z0-9._-]*)", re.I)),
    ("smartrecruiters", re.compile(r"(?:jobs\.smartrecruiters\.com|api\.smartrecruiters\.com/v1/companies)/([a-z0-9][a-z0-9._-]*)", re.I)),
    ("recruitee",  re.compile(r"https?://([a-z0-9][a-z0-9-]*)\.recruitee\.com", re.I)),
    # Multi-group patterns: _canonical turns the groups into a composite token.
    ("oracle_hcm", re.compile(r"https?://([a-z0-9.-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z]{2}(?:-[A-Z]{2})?/sites/([A-Za-z0-9_]+)", re.I)),
    ("workday",    re.compile(r"https?://(([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com)/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)", re.I)),
    ("bamboohr",   re.compile(r"https?://([a-z0-9-]+)\.bamboohr\.com/(?:careers|jobs)", re.I)),
    ("teamtailor", re.compile(r"https?://([a-z0-9-]+\.teamtailor\.com)", re.I)),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(ats: str, groups: tuple) -> Optional[str]:
    """Regex groups -> the token stored for (ats, token). None = reject."""
    if ats == "oracle_hcm":
        host, site = groups
        return f"{host.lower()}|{site}"
    if ats == "workday":
        host, tenant, site = groups
        if site.lower() in _WD_SITE_BLOCKLIST:
            return None
        return f"{host.lower()}|{tenant.lower()}|{site}"
    if ats == "teamtailor":
        return groups[0].lower()
    return groups[0].lower().strip("._-")


def extract_tokens(url: str) -> set[tuple[str, str]]:
    """All (ats, token) pairs referenced by a single URL.

    The token is a plain board token, or a composite string for
    oracle_hcm / workday / teamtailor (see the module docstring).
    """
    if not url:
        return set()
    found: set[tuple[str, str]] = set()
    for ats, pat in _PATTERNS:
        for m in pat.finditer(url):
            token = _canonical(ats, m.groups())
            if token and token not in _TOKEN_BLOCKLIST and len(token) >= 2:
                found.add((ats, token))
    return found


def split_token(ats: str, token: str) -> dict:
    """Composite token -> board fields (`host`, `site`, `tenant`, `portal`); {} if the
    token is a plain single-part one (or malformed)."""
    parts = token.split("|")
    if ats == "oracle_hcm" and len(parts) == 2 and all(parts):
        return {"host": parts[0], "site": parts[1]}
    if ats == "workday" and len(parts) == 3 and all(parts):
        return {"host": parts[0], "tenant": parts[1], "site": parts[2]}
    if ats == "teamtailor" and len(parts) == 1 and token:
        return {"host": token}
    if ats == "taleo" and len(parts) == 3 and all(parts):
        return {"host": parts[0], "site": parts[1], "portal": parts[2]}
    if ats in ("phenom", "avature") and len(parts) == 2 and all(parts):
        return {"host": parts[0], "site": parts[1]}
    return {}


def board_from_pair(ats: str, token: str) -> dict:
    """(ats, token) -> a board dict shaped like a seed (host/site/tenant included)."""
    return {"ats": ats, "token": token, **split_token(ats, token)}


# ── Persistence (data/ats_boards.json) ──

def load_harvested() -> list[dict]:
    """Persisted, validated boards. Each: {ats, token, company, discovered_at, source}."""
    with _lock:
        try:
            if _STORE.exists():
                return json.loads(_STORE.read_text())
        except Exception as e:
            logger.warning(f"ATS harvester: could not read store: {e}")
        return []


def _save(boards: list[dict]):
    with _lock:
        try:
            _STORE.parent.mkdir(parents=True, exist_ok=True)
            _STORE.write_text(json.dumps(boards, indent=2))
        except Exception as e:
            logger.warning(f"ATS harvester: could not write store: {e}")


def known_pairs() -> set[tuple[str, str]]:
    """Every (ats, token) already known — seed + harvested — to skip re-validating."""
    from scrapers.ats import MENA_SEED_BOARDS, SEED_BOARDS
    pairs = {(b["ats"], b["token"]) for b in [*SEED_BOARDS, *MENA_SEED_BOARDS]}
    pairs |= {(b["ats"], b["token"]) for b in load_harvested()}
    return pairs


# ── Validation ──

async def _validate(client: httpx.AsyncClient, ats: str, token: str) -> Optional[dict]:
    """Confirm a board resolves to real jobs; return {company, jobs} or None."""
    try:
        if ats == "greenhouse":
            r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
            if r.status_code != 200:
                return None
            data = r.json()
            jobs = data.get("jobs", [])
            if not jobs:
                return None
            company = _company_from_jobs(jobs, "company_name") or _titlecase(token)
            return {"company": company, "jobs": len(jobs)}
        if ats == "lever":
            r = await client.get(f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"})
            if r.status_code != 200:
                return None
            jobs = r.json()
            if not isinstance(jobs, list) or not jobs:
                return None
            return {"company": _titlecase(token), "jobs": len(jobs)}
        if ats == "ashby":
            r = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
            if r.status_code != 200:
                return None
            jobs = r.json().get("jobs", [])
            if not jobs:
                return None
            return {"company": _titlecase(token), "jobs": len(jobs)}
        if ats == "workable":
            r = await client.get(f"https://apply.workable.com/api/v1/widget/accounts/{token}")
            if r.status_code != 200:
                return None
            data = r.json()
            jobs = data.get("jobs", [])
            if not jobs:
                return None
            return {"company": (data.get("name") or "").strip() or _titlecase(token), "jobs": len(jobs)}
        if ats == "smartrecruiters":
            r = await client.get(f"https://api.smartrecruiters.com/v1/companies/{token}/postings", params={"limit": 1})
            if r.status_code != 200:
                return None
            data = r.json()
            total = data.get("totalFound") or len(data.get("content") or [])
            if not total:
                return None
            company = _company_from_jobs([(c.get("company") or {}) for c in data.get("content") or []], "name")
            return {"company": company or _titlecase(token), "jobs": total}
        if ats == "recruitee":
            r = await client.get(f"https://{token}.recruitee.com/api/offers/")
            if r.status_code != 200:
                return None
            jobs = r.json().get("offers", [])
            if not jobs:
                return None
            return {"company": _titlecase(token), "jobs": len(jobs)}
        if ats == "oracle_hcm":
            parts = split_token(ats, token)
            if not parts:
                return None
            r = await client.get(
                f"https://{parts['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
                params={"onlyData": "true",
                        "finder": f"findReqs;siteNumber={parts['site']},limit=1,sortBy=POSTING_DATES_DESC"},
            )
            if r.status_code != 200:   # includes Oracle's WAF block (W4S-101)
                return None
            items = r.json().get("items") or []
            total = (items[0].get("TotalJobsCount") if items else 0) or 0
            if not total:
                return None
            # The host is an opaque pod name ("ehpv.fa.em2..."), so this name is
            # a guess; log it so a human can rename the board.
            company = _titlecase(parts["host"].split(".")[0])
            logger.info(f"ATS harvester: oracle_hcm {token} company name is a guess ({company}); rename by hand")
            return {"company": company, "jobs": total}
        if ats == "workday":
            parts = split_token(ats, token)
            if not parts:
                return None
            r = await client.post(
                f"https://{parts['host']}/wday/cxs/{parts['tenant']}/{parts['site']}/jobs",
                json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
            )
            if r.status_code != 200:
                return None
            total = r.json().get("total") or 0
            if not total:
                return None
            return {"company": _titlecase(parts["tenant"]), "jobs": total}
        if ats == "bamboohr":
            r = await client.get(f"https://{token}.bamboohr.com/careers/list", headers={"Accept": "application/json"})
            if r.status_code != 200:
                return None
            total = (r.json().get("meta") or {}).get("totalCount") or 0
            if not total:
                return None
            return {"company": _titlecase(token), "jobs": total}
        if ats == "teamtailor":
            r = await client.get(f"https://{token}/jobs.json")
            if r.status_code != 200:
                return None
            data = r.json()
            items = data.get("items") or []
            if not items:
                return None
            title = re.sub(r"\s*[-|]?\s*(jobs|careers?|career site)\s*$", "", (data.get("title") or "").strip(), flags=re.I)
            return {"company": title.strip() or _titlecase(token.split(".")[0]), "jobs": len(items)}
        if ats == "taleo":
            parts = split_token(ats, token)
            if not parts:
                return None
            from scrapers.ats import ATSAggregatorScraper
            r = await client.post(
                f"https://{parts['host']}/careersection/rest/jobboard/searchjobs",
                params={"lang": "en", "portal": parts["portal"]},
                json=ATSAggregatorScraper._taleo_search_body(1),
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest",
                         "tz": "GMT+04:00", "Accept-Encoding": "identity"},
            )
            if r.status_code != 200:
                return None
            total = (r.json().get("pagingData") or {}).get("totalCount") or 0
            if not total:
                return None
            # Host labels are opaque ("jobs.dubaicareers.ae"); the section is the better guess.
            return {"company": _titlecase(parts["site"]), "jobs": total}
        if ats == "phenom":
            parts = split_token(ats, token)
            if not parts:
                return None
            from scrapers.ats import ATSAggregatorScraper
            r = await client.get(f"https://{parts['host']}/{parts['site']}/search-results",
                                 params={"from": 0, "s": 1}, headers={"Accept": "text/html,application/xhtml+xml"})
            if r.status_code != 200:
                return None
            data = ATSAggregatorScraper._phenom_search_data(r.text)
            total = (data or {}).get("totalHits") or 0
            if not total:
                return None
            return {"company": _titlecase(parts["host"].split(".")[1] if parts["host"].count(".") > 1 else parts["host"]),
                    "jobs": total}
        if ats == "avature":
            parts = split_token(ats, token)
            if not parts:
                return None
            from scrapers.ats import ATSAggregatorScraper
            r = await client.get(f"https://{parts['host']}/{parts['site']}/sitemap_index.xml",
                                 headers={"Accept": "application/xml,text/xml"})
            if r.status_code != 200:
                return None
            # Only the sitemap the site itself declares; no sitemap means the job
            # list is not meant to be crawled (Emirates), so the board is invalid.
            if "<sitemapindex" in r.text:
                children = [u.strip() for u in re.findall(r"<loc>([^<]+)</loc>", r.text)
                            if u.strip().startswith(f"https://{parts['host']}/")][:3]
            else:
                children = []
            sitemaps = [r.text]
            for child in children:
                cr = await client.get(child, headers={"Accept": "application/xml,text/xml"})
                if cr.status_code == 200:
                    sitemaps.append(cr.text)
            total = sum(len(ATSAggregatorScraper._avature_entries(x, parts["host"], parts["site"])) for x in sitemaps)
            if not total:
                return None
            return {"company": _titlecase(parts["host"].split(".")[1] if parts["host"].count(".") > 1 else parts["host"]),
                    "jobs": total}
    except Exception:
        return None
    return None


def _company_from_jobs(jobs: list, field: str) -> Optional[str]:
    for j in jobs:
        v = j.get(field)
        if v and v.strip():
            return v.strip()
    return None


def _titlecase(token: str) -> str:
    return re.sub(r"[._-]+", " ", token).strip().title() or token


# ── Harvest entry points ──

async def harvest_urls(urls: list[str], max_new: int = 25) -> list[dict]:
    """Extract, validate, and persist new boards from a batch of URLs.

    Returns the boards newly added this call. Bounded by `max_new` validation
    calls so a discovery run never blocks on a flood of candidates.
    """
    candidates: set[tuple[str, str]] = set()
    for u in urls:
        candidates |= extract_tokens(u)
    new_pairs = sorted(candidates - known_pairs())
    if not new_pairs:
        return []

    new_pairs = new_pairs[:max_new]
    added: list[dict] = []
    async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (compatible; JobPlatformBot/1.0)"}) as client:
        sem = asyncio.Semaphore(6)

        async def check(pair):
            ats, token = pair
            async with sem:
                return pair, await _validate(client, ats, token)

        for pair, result in await asyncio.gather(*[check(p) for p in new_pairs]):
            if result:
                ats, token = pair
                added.append({
                    **board_from_pair(ats, token), "company": result["company"],
                    "discovered_at": _now(), "source": "harvest",
                })
                logger.info(f"ATS harvester: + {ats}/{token} ({result['company']}, {result['jobs']} jobs)")

    if added:
        _save(load_harvested() + added)
    return added


async def harvest_from_db(db, limit: int = 2000, max_new: int = 25) -> list[dict]:
    """Scan stored listings' apply/source URLs for new ATS boards."""
    try:
        rows = (db.table("job_listings")
                .select("apply_url, source_url")
                .order("discovered_at", desc=True)
                .limit(limit).execute().data or [])
    except Exception as e:
        logger.warning(f"ATS harvester: DB scan skipped: {e}")
        return []
    urls = [u for r in rows for u in (r.get("apply_url"), r.get("source_url")) if u]
    return await harvest_urls(urls, max_new=max_new)
