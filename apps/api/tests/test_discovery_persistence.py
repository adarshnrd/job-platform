"""
End-to-end guarantee: scraped jobs survive a failure in any later stage.

Each test kills the pipeline at a different point and asserts the same thing —
every job a scraper returned is still in the database, and the next run does not
scrape it again.
"""
import pytest

from models.job import JobListingCreate, Platform
from services import job_pipeline as jp
from tests.fake_supabase import FakeDB
from workers import job_discovery as jd

USER = {
    "id": "u1", "skills": ["python", "fastapi"], "headline": "Backend Engineer",
    "preferred_platforms": [], "preferred_locations": ["Bangalore"],
    "auto_apply_enabled": False, "career_goals": "",
}


def make_job(i: int, title="Backend Engineer") -> JobListingCreate:
    return JobListingCreate(
        title=f"{title} {i}",
        company=f"Company{i}",
        jd_text="Python FastAPI Postgres. 5 years of experience required.",
        source_platform=Platform.linkedin,
        source_url=f"https://example.com/job/{i}",
    )


@pytest.fixture
def env(monkeypatch):
    """One source that returns 4 jobs per query, one query pair, no real AI."""
    fake = FakeDB({
        "job_listings": [], "job_pipeline_items": [], "job_applications": [],
        "apply_queue": [], "users": [dict(USER)], "company_blacklist": [],
    })
    from workers import pipeline_worker as pw
    monkeypatch.setattr(jp, "db", fake)
    monkeypatch.setattr(jd, "db", fake)
    monkeypatch.setattr(pw, "db", fake)
    monkeypatch.setattr(pw, "_budget_blocked", lambda: None)
    monkeypatch.setattr(pw, "select_in_batches",
                        lambda db, table, select, column, values, batch_size=200:
                        [dict(r) for r in db.rows(table) if r.get(column) in set(values)])
    jp._reset_availability_for_tests()

    scraped: list[JobListingCreate] = [make_job(i) for i in range(4)]

    class _Scraper:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def search_jobs(self, query, location, max_results):
            return list(scraped)

    src = jd.Source("fakesource", _Scraper, True, False, {"india"})
    monkeypatch.setattr(jd, "select_sources", lambda region, platforms: [src])
    monkeypatch.setattr(jd, "select_in_batches",
                        lambda db, table, select, column, values, batch_size=200:
                        [dict(r) for r in db.rows(table) if r.get(column) in set(values)])
    monkeypatch.setattr(jd.settings, "DISCOVERY_MAX_SEARCHES_PER_SOURCE", 1)
    monkeypatch.setattr(jd.settings, "DISCOVERY_PREFILTER_ENABLED", False)
    monkeypatch.setattr(jd.settings, "DISCOVERY_HEALTH_SCHEDULING_ENABLED", False)

    # Post-run side effects are out of scope here and would reach the network.
    monkeypatch.setattr("services.job_tracker.update_tracker", lambda uid: None)

    async def _no_harvest(db_, max_new=15):
        return []
    monkeypatch.setattr("services.ats_harvester.harvest_from_db", _no_harvest)

    yield fake, scraped
    jp._reset_availability_for_tests()


def _fail_ai(monkeypatch, where: str):
    """Blow up the pipeline the way a network drop does — at `where`."""
    async def _boom(*_a, **_kw):
        raise RuntimeError("[Errno 8] nodename nor servname provided, or not known")

    from workers import pipeline_worker as pw
    if where == "parse":
        monkeypatch.setattr(pw, "batch_parse_jds", _boom)
    elif where == "score":
        monkeypatch.setattr(pw, "batch_score_jobs", _boom)
    elif where == "drain":
        monkeypatch.setattr(pw, "drain", _boom)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["parse", "score", "drain"])
async def test_scraped_jobs_survive_any_downstream_failure(env, monkeypatch, failure_point):
    db, scraped = env
    _fail_ai(monkeypatch, failure_point)

    with pytest.raises(Exception):
        await jd._discover_for_user_async("u1", "india", run_id="")

    # The whole point: the scrape is banked before any AI stage runs.
    assert len(db.rows("job_listings")) == len(scraped)
    assert len(db.rows("job_pipeline_items")) == len(scraped)
    assert {r["source_url"] for r in db.rows("job_listings")} == {j.source_url for j in scraped}


@pytest.mark.asyncio
async def test_a_failed_run_does_not_rescrape_on_the_next_attempt(env, monkeypatch):
    db, scraped = env
    _fail_ai(monkeypatch, "drain")

    with pytest.raises(Exception):
        await jd._discover_for_user_async("u1", "india", run_id="")
    first_pass = len(db.rows("job_listings"))
    assert first_pass == len(scraped)

    # Second run: the same source returns the same jobs. They are recognised as
    # already staged, so the run finds nothing new — no re-scrape, no re-bill.
    await jd._discover_for_user_async("u1", "india", run_id="")

    assert len(db.rows("job_listings")) == first_pass, "already-staged jobs are not re-stored"
    assert len(db.rows("job_pipeline_items")) == first_pass, "and not re-queued"


@pytest.mark.asyncio
async def test_jobs_are_persisted_before_the_source_finishes(env, monkeypatch):
    """Durability is per query result, not per run — a crash mid-source still banks
    everything scraped up to that point."""
    db, scraped = env
    calls = {"n": 0}

    real_checkpoint = jd._checkpoint

    async def counting_checkpoint(jobs, **kw):
        calls["n"] += 1
        await real_checkpoint(jobs, **kw)
        # Jobs are in the database before this returns to the scrape loop.
        assert len(db.rows("job_listings")) == len(scraped)
        raise RuntimeError("simulated crash immediately after the checkpoint")

    monkeypatch.setattr(jd, "_checkpoint", counting_checkpoint)

    # The crash is inside the per-query try/except, so the run continues and
    # simply finds nothing new to process.
    await jd._discover_for_user_async("u1", "india", run_id="")

    assert calls["n"] == 1
    assert len(db.rows("job_listings")) == len(scraped)


@pytest.mark.asyncio
async def test_prefiltered_jobs_are_still_stored(env, monkeypatch):
    db, scraped = env
    monkeypatch.setattr(jd.settings, "DISCOVERY_PREFILTER_ENABLED", True)
    monkeypatch.setattr(jd.settings, "PIPELINE_PERSIST_PREFILTERED", True)
    # Nothing in these JDs matches the user's keywords → all rejected.
    monkeypatch.setattr("services.prefilter.rejected_indices",
                        lambda jobs, user: set(range(len(jobs))))

    await jd._discover_for_user_async("u1", "india", run_id="")

    assert len(db.rows("job_listings")) == len(scraped), "off-profile jobs are recorded, not vanished"
    assert {i["stage"] for i in db.rows("job_pipeline_items")} == {jp.STAGE_PREFILTERED}


@pytest.mark.asyncio
async def test_legacy_path_still_persists_when_migration_16_is_missing(env, monkeypatch):
    db, scraped = env
    db.missing_tables.add("job_pipeline_items")
    jp._reset_availability_for_tests()

    async def _parse(texts):
        return [{"title": "Engineer"} for _ in texts]

    async def _score(user, jobs, double_eval_threshold=70):
        return [{"overall_score": 70, "tier": "recommended", "strengths": [], "gaps": [],
                 "summary": ""} for _ in jobs]

    monkeypatch.setattr(jd, "batch_parse_jds", _parse)
    monkeypatch.setattr(jd, "batch_score_jobs", _score)
    monkeypatch.setattr(jd.settings, "HR_CONTACT_ENRICHMENT_ENABLED", False)

    await jd._discover_for_user_async("u1", "india", run_id="")

    # No queue table, but the listings are stored at scrape time regardless and
    # the in-memory stages still produce match records.
    assert len(db.rows("job_listings")) == len(scraped)
    assert len(db.rows("job_applications")) == len(scraped)
