"""
RemoteOK — public JSON feed of remote roles, global.
https://remoteok.com/api

The whole board comes back in one response, so this filters client-side rather
than paginating. Tags are the useful signal: RemoteOK's `tags` array is a
curated skill list, so it maps straight onto required_skills and also carries
seniority and job-type hints the title often omits.
"""
from __future__ import annotations

import re
from typing import Optional

from loguru import logger

from models.job import ExperienceLevel, JobListingCreate, JobType, Platform, WorkMode
from scrapers.api_base import APIBaseScraper

_HTML = re.compile(r"<[^>]+>")
_STOPWORDS = {"the", "and", "for", "with", "job", "jobs", "role", "roles"}

_LEVELS: dict[str, ExperienceLevel] = {
    "junior": ExperienceLevel.entry, "entry": ExperienceLevel.entry,
    "senior": ExperienceLevel.senior, "lead": ExperienceLevel.lead,
    "principal": ExperienceLevel.principal, "staff": ExperienceLevel.principal,
    "director": ExperienceLevel.executive, "vp": ExperienceLevel.executive,
}
_JOB_TYPES: dict[str, JobType] = {
    "contract": JobType.contract, "freelance": JobType.freelance,
    "part-time": JobType.part_time, "internship": JobType.internship,
}


class RemoteOKScraper(APIBaseScraper):
    platform = Platform.remoteok
    requires_key = False
    regions = {"global", "india"}
    rate_limit_per_minute = 6
    API_URL = "https://remoteok.com/api"

    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (compatible; JobPlatformBot/1.0)",
        "Accept": "application/json",
    }

    async def search_jobs(
        self,
        query: str,
        location: str = "Remote",
        max_results: int = 50,
        credentials: Optional[dict] = None,
        region: str = "global",
    ) -> list[JobListingCreate]:
        data = await self._get_json(self.API_URL)
        if not isinstance(data, list):
            return []

        # The first element is RemoteOK's legal notice, not a job.
        items = [i for i in data if isinstance(i, dict) and i.get("slug")]
        tokens = [
            t for t in re.split(r"[^a-z0-9.+#]+", (query or "").lower())
            if len(t) >= 2 and t not in _STOPWORDS
        ]

        jobs: list[JobListingCreate] = []
        for item in items:
            tags = [str(t) for t in (item.get("tags") or [])]
            title = str(item.get("position") or "")
            haystack = f"{title} {' '.join(tags)}".lower()
            if tokens and not any(t in haystack for t in tokens):
                continue

            url = item.get("url") or f"https://remoteok.com/remote-jobs/{item.get('slug')}"
            if not self._is_new(url):
                continue

            jd = self._clean_text(_HTML.sub(" ", str(item.get("description") or "")))
            blob = f"{title} {' '.join(tags)}".lower()

            jobs.append(JobListingCreate(
                title=self._fix_mojibake(title) or "Remote Role",
                company=self._fix_mojibake(str(item.get("company") or "")) or "Company (via RemoteOK)",
                company_logo_url=item.get("company_logo") or item.get("logo") or None,
                location=self._fix_mojibake(self._clean_text(str(item.get("location") or ""))) or "Remote",
                work_mode=WorkMode.remote,
                is_remote_friendly=True,
                job_type=self.match_terms(blob, _JOB_TYPES, JobType.full_time),
                experience_level=self.match_terms(blob, _LEVELS),
                salary_min=self._salary(item.get("salary_min")),
                salary_max=self._salary(item.get("salary_max")),
                salary_currency="USD",
                required_skills=tags[:12],
                jd_text=jd or f"{title} at {item.get('company', 'a remote company')}.",
                source_platform=self.platform,
                source_url=url,
                apply_url=item.get("apply_url") or url,
                source_job_id=str(item.get("id") or "") or None,
                posted_at=self.parse_posted_at(item.get("epoch") or item.get("date")),
            ))
            if len(jobs) >= max_results:
                break

        logger.info(f"RemoteOK: returning {len(jobs)} jobs for '{query}'")
        return jobs

    @staticmethod
    def _fix_mojibake(text: str) -> str:
        """Repair double-encoded UTF-8 in RemoteOK's own data.

        Some listings arrive as "JÃºnior"/"SoluÃ§Ãµes" — UTF-8 bytes that were
        stored after being read as latin-1. The response itself is valid UTF-8,
        so this is upstream corruption, not a decoding bug here. Re-encoding
        latin-1 and decoding UTF-8 reverses it; text that does not round-trip is
        returned untouched.
        """
        if not text or not any(marker in text for marker in ("Ã", "Â", "â€")):
            return text
        try:
            return text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return text

    @staticmethod
    def _salary(value) -> Optional[int]:
        """RemoteOK sends 0 for "not disclosed" — treat that as absent."""
        try:
            n = int(value)
            return n if n > 0 else None
        except (TypeError, ValueError):
            return None
