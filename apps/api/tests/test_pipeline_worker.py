"""
Tests for the queue-driven AI stages.

The failure that motivated this pipeline — a transient DNS error during scoring
that discarded 7h47m of scraping — is reproduced here as a fault injection, and
asserted to cost one retryable item instead of the run.
"""
import pytest

from services import job_pipeline as jp
from tests.fake_supabase import FakeDB
from workers import pipeline_worker as pw

USER = {"id": "u1", "skills": ["python"], "auto_apply_enabled": False}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB({
        "job_listings": [], "job_pipeline_items": [],
        "job_applications": [], "apply_queue": [],
        "users": [dict(USER)],
    })
    monkeypatch.setattr(jp, "db", fake)
    monkeypatch.setattr(pw, "db", fake)
    monkeypatch.setattr(pw, "select_in_batches", _fake_select_in_batches)
    monkeypatch.setattr(pw, "_budget_blocked", lambda: None)
    jp._reset_availability_for_tests()
    yield fake
    jp._reset_availability_for_tests()


def _fake_select_in_batches(db, table, select, column, values, batch_size=200):
    return [dict(r) for r in db.rows(table) if r.get(column) in set(values)]


def seed(db, n=3, stage=jp.STAGE_SCRAPED, offset=0, **item_overrides) -> list[dict]:
    """n listings, each with a pipeline item at `stage`."""
    items = []
    for i in range(offset, offset + n):
        listing_id = f"listing-{i}"
        db.rows("job_listings").append({
            "id": listing_id, "title": f"Engineer {i}", "company": f"Co{i}",
            "jd_text": "Python FastAPI. 5 years of experience required.",
            "source_platform": "linkedin", "source_url": f"https://x/{i}",
            "min_experience": None, "max_experience": None, "experience_level": None,
        })
        item = {
            "id": f"item-{i}", "user_id": "u1", "run_id": "r1",
            "job_listing_id": listing_id, "source_platform": "linkedin",
            "stage": stage, "stage_status": "pending",
            "attempts": 0, "max_attempts": 3, "last_error": None,
            "next_attempt_at": "2000-01-01T00:00:00+00:00", "claimed_at": None,
            "created_at": f"2000-01-01T00:00:0{i}+00:00", "parsed_jd": None,
            **item_overrides,
        }
        db.rows("job_pipeline_items").append(item)
        items.append(item)
    return items


def stub_parse(monkeypatch, results=None):
    async def _parse(texts):
        return results or [{"title": "Engineer", "min_experience": 5} for _ in texts]
    monkeypatch.setattr(pw, "batch_parse_jds", _parse)


def stub_score(monkeypatch, score=85, failed=False):
    async def _score(user, jobs, double_eval_threshold=70):
        if failed:
            return [{"overall_score": 0, "tier": "archived", "summary": "Scoring failed",
                     "_failed": True} for _ in jobs]
        return [{"overall_score": score, "tier": "recommended", "strengths": [],
                 "gaps": [], "summary": "Good fit"} for _ in jobs]
    monkeypatch.setattr(pw, "batch_score_jobs", _score)


# ══════════════════════════════════════════════════════════════
#  PARSE
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_parse_advances_and_stores_its_output(db, monkeypatch):
    seed(db, 2)
    stub_parse(monkeypatch)

    res = await pw.run_stage_parse("u1")

    assert res["advanced"] == 2
    items = db.rows("job_pipeline_items")
    assert {i["stage"] for i in items} == {jp.STAGE_PARSED}
    # Parsed output is persisted so a later score retry never re-pays for it.
    assert all(i["parsed_jd"] for i in items)
    # Experience was written back to the listing that already existed.
    assert db.rows("job_listings")[0]["min_experience"] == 5


@pytest.mark.asyncio
async def test_budget_exhaustion_leaves_items_untouched(db, monkeypatch):
    seed(db, 2)
    monkeypatch.setattr(pw, "_budget_blocked", lambda: "daily token budget exhausted")

    res = await pw.run_stage_parse("u1")

    assert res["claimed"] == 0
    assert res["blocked"]
    items = db.rows("job_pipeline_items")
    assert all(i["stage"] == jp.STAGE_SCRAPED for i in items)
    assert all(i["attempts"] == 0 for i in items), "a budget wait must not burn attempts"


@pytest.mark.asyncio
async def test_item_whose_listing_vanished_is_failed_not_retried_forever(db, monkeypatch):
    seed(db, 1)
    db.rows("job_listings").clear()
    stub_parse(monkeypatch)

    res = await pw.run_stage_parse("u1")

    assert res["failed"] == 1
    assert db.rows("job_pipeline_items")[0]["stage_status"] == "failed"


# ══════════════════════════════════════════════════════════════
#  ENRICH
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_enrichment_failure_never_blocks_a_job(db, monkeypatch):
    seed(db, 2, stage=jp.STAGE_PARSED)
    monkeypatch.setattr(pw.settings, "HR_CONTACT_ENRICHMENT_ENABLED", True)

    async def _boom(_jobs):
        raise RuntimeError("hunter.io unreachable")
    monkeypatch.setattr("services.hr_contact.enrich_jobs", _boom)

    res = await pw.run_stage_enrich("u1")

    assert res["advanced"] == 2, "HR contact is a bonus, not a gate"
    assert {i["stage"] for i in db.rows("job_pipeline_items")} == {jp.STAGE_ENRICHED}


# ══════════════════════════════════════════════════════════════
#  SCORE — the incident
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_score_writes_match_records(db, monkeypatch):
    seed(db, 3, stage=jp.STAGE_ENRICHED)
    stub_score(monkeypatch, score=85)

    res = await pw.run_stage_score("u1")

    assert res["advanced"] == 3
    assert len(db.rows("job_applications")) == 3
    assert {i["stage"] for i in db.rows("job_pipeline_items")} == {jp.STAGE_DONE}
    assert res["matched"] == 3


@pytest.mark.asyncio
async def test_transient_db_error_costs_one_item_not_the_batch(db, monkeypatch):
    """The reported incident: a DNS failure mid-save.

    Before this pipeline it aborted the loop and discarded every remaining
    evaluation. Now the failed item retries and the rest complete.
    """
    seed(db, 3, stage=jp.STAGE_ENRICHED)
    stub_score(monkeypatch, score=85)
    db.fail_on[("job_applications", "upsert")] = 1  # first save blows up

    res = await pw.run_stage_score("u1")

    assert res["failed"] == 1
    assert res["advanced"] == 2, "one bad write must not take the batch with it"
    assert len(db.rows("job_applications")) == 2

    failed_item = db.rows("job_pipeline_items")[0]
    assert failed_item["stage"] == jp.STAGE_ENRICHED, "still queued at its stage"
    assert failed_item["stage_status"] == "pending", "scheduled for another attempt"
    assert failed_item["attempts"] == 1

    # The listing itself never moved.
    assert len(db.rows("job_listings")) == 3


@pytest.mark.asyncio
async def test_retry_completes_the_failed_item(db, monkeypatch):
    seed(db, 2, stage=jp.STAGE_ENRICHED)
    stub_score(monkeypatch, score=85)
    db.fail_on[("job_applications", "upsert")] = 1
    await pw.run_stage_score("u1")

    # Backoff has elapsed (the fake compares ISO strings; reset the gate).
    for item in db.rows("job_pipeline_items"):
        if item["stage_status"] == "pending":
            item["next_attempt_at"] = "2000-01-01T00:00:00+00:00"

    res = await pw.run_stage_score("u1")

    assert res["advanced"] == 1
    assert len(db.rows("job_applications")) == 2
    assert {i["stage"] for i in db.rows("job_pipeline_items")} == {jp.STAGE_DONE}


@pytest.mark.asyncio
async def test_provider_outage_does_not_bury_jobs_at_score_zero(db, monkeypatch):
    seed(db, 2, stage=jp.STAGE_ENRICHED)
    stub_score(monkeypatch, failed=True)

    res = await pw.run_stage_score("u1")

    assert res["failed"] == 2
    assert db.rows("job_applications") == [], "no false 0/archived verdicts"
    assert all(i["stage"] == jp.STAGE_ENRICHED for i in db.rows("job_pipeline_items"))


@pytest.mark.asyncio
async def test_auto_apply_queueing_is_idempotent(db, monkeypatch):
    seed(db, 1, stage=jp.STAGE_ENRICHED)
    db.rows("users")[0]["auto_apply_enabled"] = True

    async def _score(user, jobs, double_eval_threshold=70):
        return [{"overall_score": 92, "tier": "auto_apply", "summary": "", "strengths": [], "gaps": []}]
    monkeypatch.setattr(pw, "batch_score_jobs", _score)

    await pw.run_stage_score("u1")
    assert len(db.rows("apply_queue")) == 1

    # Re-run the same item (as a crash-then-retry would).
    item = db.rows("job_pipeline_items")[0]
    item.update({"stage": jp.STAGE_ENRICHED, "stage_status": "pending"})
    await pw.run_stage_score("u1")

    assert len(db.rows("apply_queue")) == 1, "a retry must not double-queue an application"


# ══════════════════════════════════════════════════════════════
#  DRAIN
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_drain_carries_jobs_from_scraped_to_done(db, monkeypatch):
    seed(db, 3)
    stub_parse(monkeypatch)
    stub_score(monkeypatch, score=75)
    monkeypatch.setattr(pw.settings, "HR_CONTACT_ENRICHMENT_ENABLED", False)

    totals = await pw.drain("u1", run_id="")

    assert totals["scored"] == 3
    assert {i["stage"] for i in db.rows("job_pipeline_items")} == {jp.STAGE_DONE}
    assert len(db.rows("job_applications")) == 3


@pytest.mark.asyncio
async def test_drain_resumes_a_half_processed_run(db, monkeypatch):
    """What a restart leaves behind: mixed stages, one stranded 'processing' claim."""
    seed(db, 1, stage=jp.STAGE_SCRAPED)
    seed(db, 1, stage=jp.STAGE_ENRICHED, offset=1,
         stage_status="processing", claimed_at="2000-01-01T00:00:00+00:00")
    stub_parse(monkeypatch)
    stub_score(monkeypatch, score=75)
    monkeypatch.setattr(pw.settings, "HR_CONTACT_ENRICHMENT_ENABLED", False)

    totals = await pw.drain("u1", run_id="")

    assert totals["scored"] == 2, "the stranded claim is released and finished"
    assert {i["stage"] for i in db.rows("job_pipeline_items")} == {jp.STAGE_DONE}


@pytest.mark.asyncio
async def test_drain_stops_when_budget_is_exhausted(db, monkeypatch):
    seed(db, 2)
    monkeypatch.setattr(pw, "_budget_blocked", lambda: "daily cost budget exhausted")

    totals = await pw.drain("u1", run_id="")

    assert totals["blocked"]
    assert totals["scored"] == 0
    assert all(i["stage"] == jp.STAGE_SCRAPED for i in db.rows("job_pipeline_items"))
