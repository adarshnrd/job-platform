"""
WeWorkRemotely scraper — uses their RSS feeds (no Playwright needed).
"""
from datetime import datetime
from loguru import logger
import httpx
import xml.etree.ElementTree as ET
import html
import re
from scrapers.base import BaseScraper
from models.job import JobListingCreate, Platform


RSS_FEEDS = [
    "https://weworkremotely.com/remote-jobs.rss",
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "https://weworkremotely.com/categories/remote-design-jobs.rss",
    "https://weworkremotely.com/categories/remote-product-jobs.rss",
]


class WeWorkRemotelyScraper(BaseScraper):
    platform = Platform.weworkremotely
    rate_limit_per_minute = 6

    async def search_jobs(self, query: str, location: str = "Remote", max_results: int = 50) -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        query_lower = query.lower()
        keywords = query_lower.split()

        try:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; JobPlatformBot/1.0)"}
            async with httpx.AsyncClient(timeout=30, headers=headers) as client:
                for feed_url in RSS_FEEDS:
                    try:
                        resp = await client.get(feed_url)
                        resp.raise_for_status()
                        root = ET.fromstring(resp.text)

                        for item in root.findall(".//item"):
                            title_el = item.find("title")
                            link_el = item.find("link")
                            desc_el = item.find("description")
                            region_el = item.find("region")

                            if title_el is None or link_el is None:
                                continue

                            title_text = title_el.text or ""
                            combined = title_text.lower()
                            if desc_el is not None and desc_el.text:
                                combined += " " + html.unescape(desc_el.text).lower()

                            if not any(kw in combined for kw in keywords):
                                continue

                            url = link_el.text or ""
                            if url in self._seen_urls:
                                continue
                            self._seen_urls.add(url)

                            # Title format: "CompanyName | Role Title"
                            parts = title_text.split("|", 1)
                            company = parts[0].strip() if len(parts) > 1 else "Unknown"
                            role = parts[1].strip() if len(parts) > 1 else title_text.strip()

                            raw_desc = html.unescape(desc_el.text or "") if desc_el is not None else ""
                            clean_desc = re.sub(r"<[^>]+>", " ", raw_desc).strip()

                            jobs.append(JobListingCreate(
                                title=role,
                                company=company,
                                location=region_el.text or "Worldwide",
                                work_mode="remote",
                                is_remote_friendly=True,
                                source_platform=self.platform,
                                source_url=url,
                                apply_url=url,
                                jd_text=clean_desc or f"{role} at {company}",
                                discovered_at=datetime.utcnow(),
                            ))

                            if len(jobs) >= max_results:
                                return jobs

                        await self.rate_limiter.acquire()
                    except Exception as feed_err:
                        logger.debug(f"WWR feed error {feed_url}: {feed_err}")
                        continue

        except Exception as e:
            logger.error(f"WeWorkRemotely search failed for '{query}': {e}")
        return jobs

    async def get_job_details(self, job: JobListingCreate) -> JobListingCreate:
        return job

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass
