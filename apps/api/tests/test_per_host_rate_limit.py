"""Per-host rate limiting in APIBaseScraper (opt-in) and its use by the ATS aggregator.

Time is mocked: scrapers.base.time.time / asyncio.sleep are patched so no test
waits on a real clock.
"""
import asyncio

import httpx

from models.job import Platform
from scrapers import base as scrapers_base
from scrapers.api_base import APIBaseScraper
from scrapers.ats import ATSAggregatorScraper


class _Clock:
    """Virtual clock: sleep() advances time instead of waiting."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps: list[float] = []

    def time(self):
        return self.now

    async def sleep(self, secs):
        self.sleeps.append(secs)
        self.now += secs


def _patch_clock(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(scrapers_base.time, "time", clock.time)
    monkeypatch.setattr(scrapers_base.asyncio, "sleep", clock.sleep)
    # Deterministic jitter.
    monkeypatch.setattr(scrapers_base.random, "uniform", lambda a, b: 0.0)
    return clock


class _PerHost(APIBaseScraper):
    platform = Platform.other
    rate_limit_per_minute = 2
    per_host_rate_limit = True

    async def search_jobs(self, *a, **k):
        return []


class _Shared(_PerHost):
    per_host_rate_limit = False


def _scraper(cls):
    s = cls()
    s._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True}, headers={"content-type": "application/json"}))
    )
    return s


def test_default_is_shared_limiter():
    assert APIBaseScraper.per_host_rate_limit is False
    assert ATSAggregatorScraper.per_host_rate_limit is True
    assert ATSAggregatorScraper.rate_limit_per_minute == 60


def test_shared_mode_unchanged_hosts_block_each_other(monkeypatch):
    clock = _patch_clock(monkeypatch)

    async def go():
        s = _scraper(_Shared)
        await s._get_json("https://a.test/x")
        await s._get_json("https://b.test/x")
        await s._get_json("https://c.test/x")  # 3rd request on a 2/min shared limiter
        await s._client.aclose()
        return s

    s = asyncio.run(go())
    assert len(clock.sleeps) == 1
    assert s.rate_limiter.requests  # shared limiter used
    assert getattr(s, "_host_limiters", {}) == {}


def test_different_hosts_do_not_block_each_other(monkeypatch):
    clock = _patch_clock(monkeypatch)

    async def go():
        s = _scraper(_PerHost)
        for host in ("a.test", "b.test", "c.test"):
            await s._get_json(f"https://{host}/x")
            await s._get_json(f"https://{host}/y")
        await s._client.aclose()
        return s

    s = asyncio.run(go())
    assert clock.sleeps == []  # 2 requests per host, 2/min per host: never throttled
    assert set(s._host_limiters) == {"a.test", "b.test", "c.test"}
    assert s.rate_limiter.requests == []  # shared limiter untouched


def test_same_host_still_limited(monkeypatch):
    clock = _patch_clock(monkeypatch)

    async def go():
        s = _scraper(_PerHost)
        await s._get_json("https://a.test/1")
        await s._get_json("https://a.test/2")
        await s._get_json("https://a.test/3")  # exceeds 2/min on a.test
        await s._client.aclose()

    asyncio.run(go())
    assert len(clock.sleeps) == 1
    assert 0 < clock.sleeps[0] <= 60


def test_all_three_helpers_use_the_host_limiter(monkeypatch):
    _patch_clock(monkeypatch)

    async def go():
        s = _scraper(_PerHost)
        await s._get_json("https://j.test/a")
        await s._get_text("https://t.test/a")
        await s._post_json("https://p.test/a", {"q": 1})
        await s._client.aclose()
        return s

    s = asyncio.run(go())
    assert set(s._host_limiters) == {"j.test", "t.test", "p.test"}
    assert all(lim.max_per_minute == 2 for lim in s._host_limiters.values())
    assert s.rate_limiter.requests == []


def test_same_host_concurrent_requests_never_exceed_limit(monkeypatch):
    """Concurrent callers on one host must be serialised through its limiter,
    not all wake up together and burst past the per-minute cap."""
    clock = _patch_clock(monkeypatch)
    stamps: list[float] = []

    async def go():
        s = _scraper(_PerHost)
        orig = s._client.get

        async def spy(*a, **k):
            stamps.append(clock.now)
            return await orig(*a, **k)

        s._client.get = spy
        await asyncio.gather(*[s._get_json(f"https://a.test/{i}") for i in range(6)])
        await s._client.aclose()

    asyncio.run(go())
    assert len(stamps) == 6
    for t in stamps:
        assert sum(1 for u in stamps if t <= u < t + 60) <= 2


def test_ats_load_runs_boards_concurrently_but_bounded(monkeypatch):
    boards = [{"ats": "greenhouse", "token": f"t{i}", "company": f"C{i}"} for i in range(20)]
    monkeypatch.setattr(ATSAggregatorScraper, "_boards", staticmethod(lambda region="india": boards))

    state = {"active": 0, "peak": 0}

    async def fake_fetch(self, board, region="india"):
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        await asyncio.sleep(0.01)
        state["active"] -= 1
        return []

    monkeypatch.setattr(ATSAggregatorScraper, "_fetch_board", fake_fetch)

    async def go():
        s = ATSAggregatorScraper()
        await s._ensure_loaded("mena")
        return s

    s = asyncio.run(go())
    assert s._all_jobs == []
    assert 1 < state["peak"] <= ATSAggregatorScraper.MAX_CONCURRENT_BOARDS
