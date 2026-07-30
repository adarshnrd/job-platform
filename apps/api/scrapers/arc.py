"""
Arc (arc.dev) — remote-first developer roles, global.

Arc renders its job board client-side, so this is a Playwright source. Unlike
the older browser scrapers here it targets `data-testid` hooks the app ships
deliberately (`result-jobs`, `job-card`) rather than guessing at hashed CSS
module class names, so it should survive styling changes.

Cards carry everything the job model needs inline — title, contract type,
seniority, pay band, skill tags and the remote/timezone rule — so a search
costs one page load with no per-job detail fetch.

Arc serves country-scoped variants of the same board at `/en-{cc}/remote-jobs`,
which is how a non-India discovery run gets locally-relevant remote roles.
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from loguru import logger
from playwright.async_api import Page

from models.job import ExperienceLevel, JobListingCreate, JobType, Platform, WorkMode
from scrapers.base import BaseScraper

BASE_URL = "https://arc.dev"

# Country-scoped board paths. Arc localises the listing set per country; the
# bare /remote-jobs path is the worldwide board.
_COUNTRY_PATHS: dict[str, str] = {
    "india": "en-in", "united kingdom": "en-gb", "uk": "en-gb",
    "united states": "en-us", "usa": "en-us", "us": "en-us",
    "canada": "en-ca", "germany": "en-de", "france": "en-fr",
    "spain": "en-es", "netherlands": "en-nl", "poland": "en-pl",
    "brazil": "en-br", "australia": "en-au", "singapore": "en-sg",
    "portugal": "en-pt", "mexico": "en-mx", "argentina": "en-ar",
}

# Arc's own skill-topic pages return far better results than free-text search.
_TOPIC_ALIASES: dict[str, str] = {
    "backend": "back-end", "back end": "back-end", "back-end": "back-end",
    "frontend": "front-end", "front end": "front-end", "front-end": "front-end",
    "fullstack": "full-stack", "full stack": "full-stack",
    "node": "nodejs", "node.js": "nodejs", "nodejs": "nodejs",
    "react": "react", "reactjs": "react", "angular": "angular", "vue": "vuejs",
    "python": "python", "django": "django", "java": "java", "golang": "golang",
    "go": "golang", "rust": "rust", "ruby": "ruby", "rails": "ruby-on-rails",
    "php": "php", "laravel": "laravel", ".net": "dotnet", "c#": "dotnet",
    "android": "android", "ios": "ios", "flutter": "flutter",
    "react native": "react-native", "devops": "devops", "aws": "aws",
    "azure": "azure", "kubernetes": "kubernetes", "docker": "docker",
    "data": "data-science", "data science": "data-science",
    "machine learning": "machine-learning", "ml": "machine-learning",
    "ai": "ai", "blockchain": "blockchain", "qa": "qa", "security": "security",
    "typescript": "typescript", "javascript": "javascript",
}

_SENIORITY: dict[str, ExperienceLevel] = {
    "junior": ExperienceLevel.entry, "entry": ExperienceLevel.entry,
    "mid-level": ExperienceLevel.mid, "mid level": ExperienceLevel.mid,
    "senior": ExperienceLevel.senior, "lead": ExperienceLevel.lead,
    "principal": ExperienceLevel.principal, "staff": ExperienceLevel.principal,
}

_JOB_TYPES: dict[str, JobType] = {
    "full-time": JobType.full_time, "full time": JobType.full_time,
    "part-time": JobType.part_time, "part time": JobType.part_time,
    "freelance": JobType.freelance, "contract": JobType.contract,
    "internship": JobType.internship,
}

# "US$35K - 40K" / "US$120,000 - 150,000" / "$90K"
_SALARY_RE = re.compile(
    r"(?:US)?\$\s*([\d,]+(?:\.\d+)?)\s*([KkMm])?\s*(?:-|–|to)?\s*(?:(?:US)?\$?\s*([\d,]+(?:\.\d+)?)\s*([KkMm])?)?"
)
# Card chrome that is never part of the job title.
_BADGES = {
    "arc exclusive", "fast apply", "actively hiring", "new", "featured",
    "verified", "hourly rate", "promoted", "urgent",
}


class ArcScraper(BaseScraper):
    platform = Platform.arc
    # Detail fetches are page loads, and discovery runs several query×location
    # pairs per source, so the per-request budget dominates run time.
    rate_limit_per_minute = 20

    MAX_SCROLLS = 4
    # Cards carry structured fields (pay, seniority, skills) but only a blurb of
    # prose. The scorer reads jd_text, so the leading listings get their real
    # description fetched; the rest keep the card summary.
    DETAIL_FETCH_LIMIT = 6

    async def search_jobs(
        self,
        query: str,
        location: str = "",
        max_results: int = 30,
        credentials: Optional[dict] = None,
        region: str = "global",
    ) -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        page = await self.new_page()
        try:
            url = self._build_url(query, location)
            await self.goto_with_retry(page, url, wait_for="domcontentloaded")

            try:
                await page.wait_for_selector('[data-testid="job-card"]', timeout=20000)
            except Exception:
                logger.info(f"Arc: no job cards rendered for '{query}' ({url})")
                return jobs

            # The board lazy-loads on scroll; stop early once we have enough.
            for _ in range(self.MAX_SCROLLS):
                cards = await page.query_selector_all('[data-testid="job-card"]')
                if len(cards) >= max_results:
                    break
                await page.mouse.wheel(0, 4000)
                await asyncio.sleep(1.5)

            cards = await page.query_selector_all('[data-testid="job-card"]')
            logger.info(f"Arc: {len(cards)} cards for '{query}' ({url})")

            for card in cards:
                try:
                    job = await self._extract_card(card)
                except Exception as e:
                    logger.debug(f"Arc card parse failed: {e}")
                    continue
                if job:
                    jobs.append(job)
                    if len(jobs) >= max_results:
                        break

            await self._enrich_descriptions(page, jobs)
        except Exception as e:
            logger.error(f"Arc search failed for '{query}': {e}")
        finally:
            await page.close()

        logger.info(f"Arc: returning {len(jobs)} jobs for '{query}'")
        return jobs

    async def _enrich_descriptions(self, page: Page, jobs: list[JobListingCreate]) -> None:
        """Fetch real JDs (and the employer name) for the leading listings."""
        enriched = 0
        for job in jobs[: self.DETAIL_FETCH_LIMIT]:
            try:
                details = await self.get_job_details(page, job.source_url)
            except Exception as e:
                logger.debug(f"Arc detail fetch failed for {job.source_url}: {e}")
                continue
            if len(details.get("jd_text") or "") > len(job.jd_text):
                job.jd_text = details["jd_text"]
                enriched += 1
            if details.get("company"):
                job.company = details["company"]
        if enriched:
            logger.debug(f"Arc: enriched {enriched}/{min(len(jobs), self.DETAIL_FETCH_LIMIT)} JDs")

    def _build_url(self, query: str, location: str) -> str:
        prefix = _COUNTRY_PATHS.get((location or "").strip().lower(), "")
        base = f"{BASE_URL}/{prefix}/remote-jobs" if prefix else f"{BASE_URL}/remote-jobs"
        topic = _TOPIC_ALIASES.get((query or "").strip().lower())
        if not topic:
            # Try the most specific token the query offers before falling back
            # to the unfiltered board (Arc has no free-text search endpoint).
            for token in re.split(r"[^a-z0-9.#+]+", (query or "").lower()):
                if token in _TOPIC_ALIASES:
                    topic = _TOPIC_ALIASES[token]
                    break
        return f"{base}/{topic}" if topic else base

    async def _extract_card(self, card) -> Optional[JobListingCreate]:
        link = await card.query_selector('a[href*="/remote-jobs/details/"]')
        href = await link.get_attribute("href") if link else None
        if not href:
            return None
        url = href if href.startswith("http") else f"{BASE_URL}{href}"
        url = url.split("?")[0]
        if self.is_seen(url):
            return None

        raw = await card.inner_text()
        lines = [line.strip() for line in raw.split("\n") if line.strip()]
        meaningful = [ln for ln in lines if ln.lower() not in _BADGES]
        if not meaningful:
            return None

        title = meaningful[0]
        blob = raw.lower()

        job_type = self.match_terms(blob, _JOB_TYPES, JobType.full_time)
        level = self.match_terms(blob, _SENIORITY)
        salary_min, salary_max = self._parse_salary(raw)
        remote = "remote" in blob or "worldwide" in blob or "anywhere" in blob

        # Arc lists the hiring company on the detail page only; the card shows
        # the role plus its requirements. Company is backfilled by
        # get_job_details when a caller needs it.
        return JobListingCreate(
            title=self._clean_text(title),
            company=self._company_from_slug(url),
            location=self._location_from(meaningful[1:]) or "Remote",
            work_mode=WorkMode.remote if remote else None,
            is_remote_friendly=remote,
            job_type=job_type,
            experience_level=level,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="USD",
            required_skills=self._skills_from(meaningful),
            jd_text=self._clean_text(" ".join(meaningful)),
            source_platform=self.platform,
            source_url=url,
            apply_url=url,
            source_job_id=url.rstrip("/").split("-")[-1] or None,
            is_easy_apply="fast apply" in blob,
        )

    @staticmethod
    def _company_from_slug(url: str) -> str:
        """Arc anonymises the employer on the board — cards never name it.

        Rather than invent one, label the source so downstream dedup
        (title+company fingerprint) stays stable and the UI is honest.
        """
        return "Company (via Arc)"

    @staticmethod
    def _location_from(lines: list[str]) -> str:
        """The remote/timezone rule. Callers pass the card lines *after* the
        title, since titles routinely end in "- Worldwide" and would otherwise
        match as the location."""
        for line in lines:
            low = line.lower()
            if low.startswith("remote") or "worldwide" in low or "anywhere" in low:
                return line
            if "overlap" in low or "timezone" in low or "time zone" in low:
                return line
        return ""

    @staticmethod
    def _skills_from(lines: list[str]) -> list[str]:
        """Skill tags are the short, comma-free lines between pay and location."""
        skills = [
            ln for ln in lines
            if 1 < len(ln) <= 30
            and ln.lower() not in _BADGES
            and not any(c in ln for c in "$—")
            and not re.search(r"\b(remote|overlap|hiring|apply|level|time)\b", ln, re.I)
            and ln.lower() not in _JOB_TYPES
        ]
        return skills[1:11]  # drop the title, keep up to 10 tags

    @classmethod
    def _parse_salary(cls, text: str) -> tuple[Optional[int], Optional[int]]:
        m = _SALARY_RE.search(text or "")
        if not m:
            return None, None

        def scale(num: Optional[str], suffix: Optional[str]) -> Optional[int]:
            if not num:
                return None
            try:
                value = float(num.replace(",", ""))
            except ValueError:
                return None
            if suffix and suffix.lower() == "k":
                value *= 1_000
            elif suffix and suffix.lower() == "m":
                value *= 1_000_000
            return int(value) if value > 0 else None

        lo = scale(m.group(1), m.group(2))
        hi = scale(m.group(3), m.group(4) or m.group(2))
        if hi is None:
            # A single figure ("$90K") is an exact rate, not an open-ended
            # floor — mirror it so salary range filters still match the job.
            hi = lo
        if lo and hi and hi < lo:
            lo, hi = hi, lo
        return lo, hi

    # Site chrome that wraps the description on every detail page.
    _NAV_PREFIX = "For companies For talent Log In Find jobs Hire talent"
    _FOOTER_MARKERS = ("Copyright ©", "All rights reserved", "About us Cookies")

    async def get_job_details(self, page: Page, job_url: str) -> dict:
        """Full JD from a listing's detail page.

        Arc's detail view has no `main`/`article`/description wrapper to anchor
        on — the copy sits directly in `body` — so the page text is taken whole
        and the surrounding nav/footer chrome trimmed off.
        """
        try:
            await self.goto_with_retry(page, job_url, wait_for="domcontentloaded")
            await asyncio.sleep(2)
            body = await page.query_selector("body")
            if not body:
                return {"jd_text": ""}
            return {"jd_text": self._strip_chrome(await body.inner_text())[:8000]}
        except Exception as e:
            logger.debug(f"Arc detail fetch failed for {job_url}: {e}")
            return {"jd_text": ""}

    @classmethod
    def _strip_chrome(cls, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        if cleaned.startswith(cls._NAV_PREFIX):
            cleaned = cleaned[len(cls._NAV_PREFIX):].strip()
        for marker in cls._FOOTER_MARKERS:
            index = cleaned.find(marker)
            if index > 0:
                cleaned = cleaned[:index].strip()
        return cleaned
