"""
RemoteOK scraper — uses the public JSON API (no Playwright needed).
https://remoteok.com/api
"""
from datetime import datetime
from loguru import logger
import httpx
from scrapers.base import BaseScraper
from models.job import JobListingCreate, Platform


class RemoteOKScraper(BaseScraper):
    platform = Platform.remoteok
    rate_limit_per_minute = 6
    API_URL = "https://remoteok.com/api"

    async def search_jobs(self, query: str, location: str = "Remote", max_results: int = 50) -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; JobPlatformBot/1.0)",
                "Accept": "application/json",
            }
            async with httpx.AsyncClient(timeout=30, headers=headers) as client:
                resp = await client.get(self.API_URL)
                resp.raise_for_status()
                data = resp.json()

            # First item is the legal notice object
            listings = [item for item in data if isinstance(item, dict) and "slug" in item]

            query_lower = query.lower()
            keywords = query_lower.split()

            for item in listings:
                tags = [t.lower() for t in (item.get("tags") or [])]
                title = (item.get("position") or "").lower()
                combined = title + " " + " ".join(tags)

                # Filter by relevance to query
                if not any(kw in combined for kw in keywords):
                    continue

                url = f"https://remoteok.com/remote-jobs/{item.get('slug', '')}"
                if url in self._seen_urls:
                    continue
                self._seen_urls.add(url)

                job = JobListingCreate(
                    title=item.get("position", "Remote Role"),
                    company=item.get("company", "Unknown"),
                    location="Remote",
                    work_mode="remote",
                    is_remote_friendly=True,
                    source_platform=self.platform,
                    source_url=url,
                    apply_url=item.get("apply_url") or url,
                    jd_text=item.get("description") or f"{item.get('position')} at {item.get('company')}",
                    required_skills=list(item.get("tags") or [])[:10],
                    company_logo_url=item.get("company_logo"),
                    posted_at=datetime.utcfromtimestamp(int(item.get("epoch", 0))) if item.get("epoch") else None,
                )
                jobs.append(job)
                if len(jobs) >= max_results:
                    break

            await self.rate_limiter.acquire()
        except Exception as e:
            logger.error(f"RemoteOK search failed for '{query}': {e}")
        return jobs

    async def get_job_details(self, job: JobListingCreate) -> JobListingCreate:
        # Detail is already included in the API response
        return job

    # RemoteOK uses HTTP (not Playwright) — override browser lifecycle
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass
