"""APIBaseScraper._get_text — rate-limited HTML/XML GET that treats a bot-wall
challenge as failure (docs/mena/README.md §5)."""
import asyncio

import httpx

from models.job import Platform
from scrapers.api_base import APIBaseScraper


class _Dummy(APIBaseScraper):
    platform = Platform.other
    rate_limit_per_minute = 6000

    async def search_jobs(self, *a, **k):
        return []


def _run(handler, url="https://example.test/page"):
    async def go():
        scraper = _Dummy()
        scraper._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await scraper._get_text(url)
        finally:
            await scraper._client.aclose()
    return asyncio.run(go())


def test_returns_body_text():
    assert _run(lambda req: httpx.Response(200, text="<html>ok</html>")) == "<html>ok</html>"


def test_http_error_returns_none():
    assert _run(lambda req: httpx.Response(500, text="boom")) is None


def test_normal_page_with_cloudflare_beacon_is_not_a_challenge():
    # Cloudflare injects this script into many ordinary pages.
    page = (
        "<html><title>Jobs</title><body>hello"
        "<script src='/cdn-cgi/challenge-platform/scripts/jsd/main.js'></script></body></html>"
    )
    assert _run(lambda req: httpx.Response(200, text=page)) == page


def test_403_just_a_moment_returns_none():
    page = "<html><title>Just a moment...</title></html>"
    assert _run(lambda req: httpx.Response(403, text=page)) is None


def test_503_challenge_platform_returns_none():
    page = "<html><script src='/cdn-cgi/challenge-platform/h/b/orchestrate'></script></html>"
    assert _run(lambda req: httpx.Response(503, text=page)) is None


def test_200_with_challenge_form_token_returns_none():
    page = "<html><form id='challenge-form'><input name='cf-chl-bypass'></form></html>"
    assert _run(lambda req: httpx.Response(200, text=page)) is None


def test_200_just_a_moment_title_returns_none():
    page = "<html><head><title>Just a moment...</title></head></html>"
    assert _run(lambda req: httpx.Response(200, text=page)) is None
