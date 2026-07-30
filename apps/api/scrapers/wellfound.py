"""
Wellfound (formerly AngelList Talent) — startup roles, India + global.

**Discovery does not work and this scraper returns nothing.** That is a
deliberate, documented state, not an outage.

Wellfound sits behind bot protection that rejects automation at the network
layer, before any page renders. Measured 2026-07-27 against
`/role/r/software-engineer`:

    plain HTTP (httpx)              → 403
    headless Chromium (bundled)     → 403
    headless real Chrome (channel)  → 403, 2.6 KB body, empty <body>
    headed real Chrome (visible)    → 403, identical response

The headed window is the strongest tool this codebase has — it is what gets
Peerlist and FlexJobs through — and Wellfound refuses it too, so there is no
selector work that would help. The block is on the request, not the markup.

The scraper is kept registered (and `discoverable=False`) so Wellfound stays in
the portal matrix for display and assisted apply: jobs already in the database
from other sources still link out correctly, and `normalize_job_url` still
collapses angel.co URLs onto wellfound.com for dedup.

Routes worth re-testing if this is revisited: an official partner/API
agreement, or an authenticated session captured through the existing
SessionService handshake (a logged-in browser profile may be treated
differently from an anonymous one).
"""
from __future__ import annotations

from typing import Optional

from loguru import logger
from playwright.async_api import Page

from models.job import JobListingCreate, Platform
from scrapers.base import BaseScraper


class WellfoundScraper(BaseScraper):
    platform = Platform.wellfound
    rate_limit_per_minute = 6
    # Headed does not defeat this wall either — see the module docstring. The
    # flag stays False so runs never pop a window that cannot succeed.
    requires_headed = False

    async def search_jobs(
        self,
        query: str,
        location: str = "Remote",
        max_results: int = 30,
        credentials: Optional[dict] = None,
        region: str = "global",
    ) -> list[JobListingCreate]:
        logger.info(
            "Wellfound: discovery unavailable (bot wall rejects headless and headed "
            "browsers alike) — skipping. Listings remain display/assisted-apply only."
        )
        return []

    async def get_job_details(self, page: Page, job_url: str) -> dict:
        return {"jd_text": ""}
