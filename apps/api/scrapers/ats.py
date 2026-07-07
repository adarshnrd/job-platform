"""
ATS-direct aggregator — pulls jobs straight from company career boards.

Greenhouse, Lever, and Ashby all expose public, keyless JSON APIs (they power
companies' own careers pages). No bot-walls, no selectors, no login. One
"source" here fans out across many company boards, so it is the highest-yield /
lowest-fragility way to add coverage — especially product/startup roles that
never hit the big aggregators.

Seed boards below are verified India-hiring companies. This is intended to grow
via a token harvester (parse apply_urls we already collect) — see
docs/SOURCE_EXPANSION_PLAN.md Phase 2 — but the seed list delivers value now.
"""
import asyncio
import re
from datetime import datetime
from typing import Optional

from loguru import logger

from scrapers.api_base import APIBaseScraper
from models.job import JobListingCreate, Platform

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
    {"ats": "greenhouse", "token": "elastic",    "company": "Elastic"},
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
]

INDIA_CITY_TOKENS = (
    "india", "bangalore", "bengaluru", "pune", "gurgaon", "gurugram",
    "noida", "delhi", "ncr", "hyderabad", "chennai", "mumbai", "kolkata",
    "ahmedabad", "jaipur", "indore", "kochi", "trivandrum", "chandigarh",
    "remote - india", "remote, india",
)
_STOPWORDS = {"the", "and", "for", "with", "job", "jobs", "developer", "engineer", "role"}
_HTML = re.compile(r"<[^>]+>")


class ATSAggregatorScraper(APIBaseScraper):
    platform = Platform.company_portal
    requires_key = False
    regions = {"india"}
    rate_limit_per_minute = 60

    def __init__(self):
        super().__init__()
        self._all_jobs: Optional[list[dict]] = None  # loaded once per run, then filtered

    async def search_jobs(self, query: str, location: str = "India", max_results: int = 50, credentials=None) -> list[JobListingCreate]:
        await self._ensure_loaded()
        tokens = [t for t in re.split(r"[^a-z0-9.+#]+", query.lower()) if len(t) >= 3 and t not in _STOPWORDS]
        loc_low = (location or "").lower()
        want_any_india = (not loc_low) or loc_low in ("india", "")

        out: list[JobListingCreate] = []
        for job in self._all_jobs or []:
            if not self._location_ok(job, loc_low, want_any_india):
                continue
            if tokens and not self._query_ok(job, tokens):
                continue
            if not self._is_new(job["source_url"]):
                continue
            out.append(self._to_listing(job))
            if len(out) >= max_results:
                break

        logger.info(f"ATS: returning {len(out)} jobs for '{query}' in {location}")
        return out

    # ── Loading (once per run) ──
    async def _ensure_loaded(self):
        if self._all_jobs is not None:
            return
        boards = self._boards()
        results = await asyncio.gather(*[self._fetch_board(b) for b in boards], return_exceptions=True)
        jobs: list[dict] = []
        for board, res in zip(boards, results):
            if isinstance(res, Exception):
                logger.warning(f"ATS board {board['ats']}/{board['token']} failed: {res}")
                continue
            jobs.extend(res)
        # Keep only India-relevant jobs — the seed is India companies but boards
        # also carry their global roles.
        self._all_jobs = [j for j in jobs if self._is_india(j)]
        logger.info(f"ATS: loaded {len(self._all_jobs)} India jobs from {len(boards)} boards")

    @staticmethod
    def _boards() -> list[dict]:
        """Seed boards plus harvester-discovered ones, deduped by (ats, token)."""
        from services.ats_harvester import load_harvested
        seen: set[tuple[str, str]] = set()
        merged: list[dict] = []
        for b in [*SEED_BOARDS, *load_harvested()]:
            key = (b["ats"], b["token"])
            if key not in seen:
                seen.add(key)
                merged.append(b)
        return merged

    async def _fetch_board(self, board: dict) -> list[dict]:
        ats, token, company = board["ats"], board["token"], board["company"]
        if ats == "greenhouse":
            data = await self._get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", params={"content": "true"})
            return [self._norm_greenhouse(j, company) for j in (data or {}).get("jobs", [])]
        if ats == "lever":
            data = await self._get_json(f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"})
            return [self._norm_lever(j, company) for j in (data or [])]
        if ats == "ashby":
            data = await self._get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
            return [self._norm_ashby(j, company) for j in (data or {}).get("jobs", [])]
        return []

    # ── Per-ATS normalization to a common dict ──
    @staticmethod
    def _norm_greenhouse(j: dict, company: str) -> dict:
        loc = (j.get("location") or {}).get("name", "")
        content = _HTML.sub(" ", j.get("content") or "").replace("&amp;", "&").replace("&nbsp;", " ")
        return {
            "title": (j.get("title") or "").strip(), "company": j.get("company_name") or company,
            "location": loc or "India", "source_url": j.get("absolute_url") or "",
            "apply_url": j.get("absolute_url") or "", "jd_text": content,
            "posted_at": _parse_iso(j.get("updated_at")), "remote": "remote" in loc.lower(),
        }

    @staticmethod
    def _norm_lever(j: dict, company: str) -> dict:
        cats = j.get("categories") or {}
        loc = cats.get("location") or ""
        return {
            "title": (j.get("text") or "").strip(), "company": company,
            "location": loc or "India", "source_url": j.get("hostedUrl") or "",
            "apply_url": j.get("applyUrl") or j.get("hostedUrl") or "",
            "jd_text": j.get("descriptionPlain") or j.get("description") or "",
            "posted_at": _parse_epoch_ms(j.get("createdAt")),
            "remote": (j.get("workplaceType") or "").lower() == "remote",
        }

    @staticmethod
    def _norm_ashby(j: dict, company: str) -> dict:
        loc = j.get("location") or ""
        return {
            "title": (j.get("title") or "").strip(), "company": company,
            "location": loc or "India", "source_url": j.get("jobUrl") or "",
            "apply_url": j.get("applyUrl") or j.get("jobUrl") or "",
            "jd_text": j.get("descriptionPlain") or "",
            "posted_at": _parse_iso(j.get("publishedAt")), "remote": bool(j.get("isRemote")),
        }

    # ── Filtering ──
    @staticmethod
    def _is_india(job: dict) -> bool:
        loc = (job.get("location") or "").lower()
        return any(tok in loc for tok in INDIA_CITY_TOKENS)

    @staticmethod
    def _location_ok(job: dict, loc_low: str, want_any_india: bool) -> bool:
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
            jd_text=jd or job["title"],
            source_platform=self.platform,
            source_url=job["source_url"],
            apply_url=job.get("apply_url") or job["source_url"],
            posted_at=job.get("posted_at"),
        )


def _parse_iso(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _parse_epoch_ms(value) -> Optional[datetime]:
    try:
        return datetime.utcfromtimestamp(int(value) / 1000)
    except Exception:
        return None
