"""
Tests for the durable pipeline's persistence and stage state.

The property under test throughout: a scraped job reaches the database before
any AI runs, and nothing that happens afterwards can remove it.
"""
import pytest

from models.job import JobListingCreate, Platform
from services import job_pipeline as jp
from tests.fake_supabase import FakeDB


def make_job(title="Senior Backend Engineer", company="Acme", url=None) -> JobListingCreate:
    return JobListingCreate(
        title=title,
        company=company,
        jd_text=f"{title} at {company}. Python, FastAPI, Postgres. 5 years experience.",
        source_platform=Platform.linkedin,
        source_url=url or f"https://example.com/{title}-{company}".replace(" ", "-"),
    )


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB({"job_listings": [], "job_pipeline_items": []})
    monkeypatch.setattr(jp, "db", fake)
    jp._reset_availability_for_tests()
    yield fake
    jp._reset_availability_for_tests()


# ══════════════════════════════════════════════════════════════
#  PERSISTENCE
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_scraped_batch_is_stored_and_enqueued(db):
    jobs = [make_job(title=f"Engineer {i}") for i in range(3)]

    ids = await jp.persist_scraped_batch(jobs, user_id="u1", run_id="r1")

    assert all(ids), "every scraped job must get a listing row"
    assert len(db.rows("job_listings")) == 3
    items = db.rows("job_pipeline_items")
    assert len(items) == 3
    assert {i["stage"] for i in items} == {jp.STAGE_SCRAPED}
    assert {i["run_id"] for i in items} == {"r1"}


@pytest.mark.asyncio
async def test_prefiltered_jobs_are_persisted_not_discarded(db):
    jobs = [make_job(title=f"Role {i}") for i in range(3)]

    await jp.persist_scraped_batch(jobs, user_id="u1", run_id="r1", prefiltered={1})

    # The off-profile job is stored like any other — only its stage differs, so
    # a prefilter mistake is replayable instead of costing another scrape.
    assert len(db.rows("job_listings")) == 3
    stages = sorted(i["stage"] for i in db.rows("job_pipeline_items"))
    assert stages == [jp.STAGE_PREFILTERED, jp.STAGE_SCRAPED, jp.STAGE_SCRAPED]


@pytest.mark.asyncio
async def test_one_failing_listing_does_not_abort_the_batch(db):
    jobs = [make_job(title=f"Role {i}") for i in range(3)]
    # The first job's upsert hits a transient network error; the rest are fine.
    db.fail_on[("job_listings", "upsert")] = 1

    ids = await jp.persist_scraped_batch(jobs, user_id="u1", run_id="r1")

    assert ids[0] is None
    assert ids[1] and ids[2]
    assert len(db.rows("job_pipeline_items")) == 2


@pytest.mark.asyncio
async def test_rediscovering_a_job_does_not_rewind_its_stage(db):
    job = make_job()
    await jp.persist_scraped_batch([job], user_id="u1", run_id="r1")
    item = db.rows("job_pipeline_items")[0]
    jp.advance(item["id"], jp.STAGE_DONE)

    # A later run scrapes the same job again.
    await jp.persist_scraped_batch([job], user_id="u1", run_id="r2")

    items = db.rows("job_pipeline_items")
    assert len(items) == 1, "one work item per (user, listing)"
    assert items[0]["stage"] == jp.STAGE_DONE, "a finished job must not be re-billed to the LLM"


@pytest.mark.asyncio
async def test_persistence_still_works_without_migration_16(db):
    # The queue table is missing, but listings must still be saved at scrape time.
    db.missing_tables.add("job_pipeline_items")
    jp._reset_availability_for_tests()

    ids = await jp.persist_scraped_batch([make_job()], user_id="u1", run_id="r1")

    assert ids[0], "scrape output must survive even on an unmigrated database"
    assert len(db.rows("job_listings")) == 1
    assert jp.pipeline_available() is False


# ══════════════════════════════════════════════════════════════
#  STAGE TRANSITIONS
# ══════════════════════════════════════════════════════════════

def _item(db, **overrides) -> dict:
    row = {
        "id": "item-1", "user_id": "u1", "job_listing_id": "listing-1",
        "stage": jp.STAGE_SCRAPED, "stage_status": "pending",
        "attempts": 0, "max_attempts": 3, "last_error": None,
        "next_attempt_at": "2000-01-01T00:00:00+00:00", "claimed_at": None,
        "created_at": "2000-01-01T00:00:00+00:00",
        **overrides,
    }
    db.rows("job_pipeline_items").append(row)
    return row


def test_advance_moves_stage_and_clears_retry_state(db):
    _item(db, attempts=2, last_error="boom", stage_status="processing")

    assert jp.advance("item-1", jp.STAGE_PARSED, parsed_jd={"title": "X"}) is True

    row = db.rows("job_pipeline_items")[0]
    assert row["stage"] == jp.STAGE_PARSED
    assert row["stage_status"] == "pending"
    assert row["attempts"] == 0
    assert row["last_error"] is None
    assert row["parsed_jd"] == {"title": "X"}


def test_failure_backs_off_then_gives_up_without_touching_the_listing(db):
    _item(db)

    jp.fail("item-1", "DNS blip", attempts=0, max_attempts=3)
    row = db.rows("job_pipeline_items")[0]
    assert row["stage_status"] == "pending", "first failure retries"
    assert row["attempts"] == 1
    first_backoff = row["next_attempt_at"]

    jp.fail("item-1", "DNS blip", attempts=1, max_attempts=3)
    row = db.rows("job_pipeline_items")[0]
    assert row["attempts"] == 2
    assert row["next_attempt_at"] > first_backoff, "backoff grows"

    jp.fail("item-1", "DNS blip", attempts=2, max_attempts=3)
    row = db.rows("job_pipeline_items")[0]
    assert row["stage_status"] == "failed"
    assert row["stage"] == jp.STAGE_SCRAPED, "the job stays where it is — nothing is deleted"
    assert row["last_error"] == "DNS blip"


def test_budget_wait_does_not_consume_an_attempt(db):
    _item(db, attempts=1)

    jp.fail("item-1", "daily budget exhausted", attempts=1, max_attempts=3,
            retry_after_seconds=3600)

    row = db.rows("job_pipeline_items")[0]
    assert row["stage_status"] == "pending"
    assert row["attempts"] == 1, "waiting for budget is not a defect"


def test_requeue_failed_resets_items(db):
    _item(db, stage_status="failed", attempts=3, last_error="boom")

    assert jp.requeue_failed("u1") == 1

    row = db.rows("job_pipeline_items")[0]
    assert row["stage_status"] == "pending"
    assert row["attempts"] == 0
    assert row["last_error"] is None


def test_revive_prefiltered_sends_jobs_back_for_scoring(db):
    _item(db, stage=jp.STAGE_PREFILTERED)

    assert jp.revive_prefiltered("u1") == 1
    assert db.rows("job_pipeline_items")[0]["stage"] == jp.STAGE_SCRAPED


# ══════════════════════════════════════════════════════════════
#  CLAIMING
# ══════════════════════════════════════════════════════════════

def test_claim_uses_rpc_when_available(db):
    _item(db)
    db.rpc_handlers["claim_pipeline_items"] = lambda p: [{"id": "item-1", "stage": p["p_stage"]}]

    claimed = jp.claim_batch(jp.STAGE_SCRAPED, limit=10, user_id="u1")

    assert [c["id"] for c in claimed] == ["item-1"]


def test_claim_falls_back_to_conditional_update(db):
    _item(db)  # no RPC registered → fallback path

    claimed = jp.claim_batch(jp.STAGE_SCRAPED, limit=10, user_id="u1")

    assert len(claimed) == 1
    assert db.rows("job_pipeline_items")[0]["stage_status"] == "processing"

    # A second claimer finds nothing — the lease is exclusive.
    assert jp.claim_batch(jp.STAGE_SCRAPED, limit=10, user_id="u1") == []


def test_claim_respects_backoff_window(db):
    _item(db, next_attempt_at="2999-01-01T00:00:00+00:00")

    assert jp.claim_batch(jp.STAGE_SCRAPED, limit=10, user_id="u1") == []


def test_pending_counts_group_by_stage_and_status(db):
    _item(db, id="a", stage=jp.STAGE_SCRAPED)
    _item(db, id="b", stage=jp.STAGE_SCRAPED, stage_status="failed")
    _item(db, id="c", stage=jp.STAGE_DONE)

    counts = jp.pending_counts("u1")

    assert counts[jp.STAGE_SCRAPED] == {"pending": 1, "processing": 0, "failed": 1}
    assert counts[jp.STAGE_DONE]["pending"] == 1
