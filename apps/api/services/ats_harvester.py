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
                    "posting-api", "job-board", "www", "for", "share", "list"}

# URL → (ats, token). Ordered; first match wins. Tokens are the URL path segment
# right after the ATS host (Greenhouse also supports an ?for=<token> embed form).
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"(?:job-)?boards(?:-api)?\.greenhouse\.io/(?:embed/job_board\?for=|v1/boards/)?([a-z0-9][a-z0-9._-]*)", re.I)),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board\?for=([a-z0-9][a-z0-9._-]*)", re.I)),
    ("lever",      re.compile(r"(?:jobs\.lever\.co|api\.lever\.co/v0/postings)/([a-z0-9][a-z0-9._-]*)", re.I)),
    ("ashby",      re.compile(r"(?:jobs\.ashbyhq\.com|api\.ashbyhq\.com/posting-api/job-board)/([a-z0-9][a-z0-9._-]*)", re.I)),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_tokens(url: str) -> set[tuple[str, str]]:
    """All (ats, token) pairs referenced by a single URL."""
    if not url:
        return set()
    found: set[tuple[str, str]] = set()
    for ats, pat in _PATTERNS:
        for m in pat.finditer(url):
            token = m.group(1).lower().strip("._-")
            if token and token not in _TOKEN_BLOCKLIST and len(token) >= 2:
                found.add((ats, token))
    return found


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
    from scrapers.ats import SEED_BOARDS
    pairs = {(b["ats"], b["token"]) for b in SEED_BOARDS}
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
                    "ats": ats, "token": token, "company": result["company"],
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
