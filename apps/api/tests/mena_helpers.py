"""Shared helpers for the MENA regional-board tests: fixture loading and a
scraper wired to an httpx MockTransport so search_jobs runs end to end offline."""
import asyncio
from pathlib import Path

import httpx

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def run_search(scraper_cls, handler, *args, **kwargs):
    """Run scraper.search_jobs(*args, **kwargs) against `handler(request)->Response`.
    Returns (jobs, requested_urls)."""
    seen: list[str] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return handler(request)

    async def go():
        scraper = scraper_cls()
        scraper.rate_limiter.max_per_minute = 10**9
        scraper._client = httpx.AsyncClient(
            transport=httpx.MockTransport(recording), follow_redirects=True
        )
        try:
            return await scraper.search_jobs(*args, **kwargs)
        finally:
            await scraper._client.aclose()

    return asyncio.run(go()), seen


def html(text: str) -> httpx.Response:
    return httpx.Response(200, text=text)
