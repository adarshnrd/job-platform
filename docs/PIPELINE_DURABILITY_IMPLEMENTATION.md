# Discovery Pipeline Durability — Implementation Plan

> **Status:** IMPLEMENTED (2026-08-02) — all seven increments shipped, 329 tests passing.
> **Design rationale:** [`PIPELINE_DURABILITY_DESIGN.md`](PIPELINE_DURABILITY_DESIGN.md).
> **Principle:** ship in increments that are each independently safe, testable and revertable. Increment 0 alone would have saved the failed run.
>
> **Remaining manual step:** run `database/16_pipeline_durability.sql` in the Supabase
> SQL editor. The code degrades gracefully without it (see §5).

---

## 1. Increment overview

| # | Title | Blast-radius fixed | Files touched | Status |
|---|---|---|---|---|
| **0** | Per-item write isolation (hotfix) | F2, F5 | `workers/job_discovery.py` | ✅ done |
| **1** | Migration 16 + `services/job_pipeline.py` | infrastructure | new SQL + new module + `config.py` | ✅ done |
| **2** | Persist scraped jobs per query batch | **F1, F4, F6** | `workers/job_discovery.py`, `services/prefilter.py` | ✅ done |
| **3** | Queue-driven stage workers (parse → enrich → score) | F7, F8, F11 | new `workers/pipeline_worker.py`, `job_discovery.py`, `services/ai/job_analysis.py`, `services/portals.py` | ✅ done |
| **4** | Scheduled drain + stale-claim reaper + startup recovery | **F3**, F10 | `scheduler.py`, `services/discovery_progress.py`, `main.py` | ✅ done |
| **5** | Observability — queue endpoint, true failed phase, UI panel | F9 | `routers/discovery.py`, `discovery_progress.py`, `activity-client.tsx`, new `processing-queue.tsx` | ✅ done |
| **6** | Tests + one-off backfill of the failed run's orphans | D5 | 4 new test modules, `tests/fake_supabase.py`, `scripts/backfill_orphan_listings.py` | ✅ done |

---

## 2. Database changes

### 2.1 New file: `database/16_pipeline_durability.sql`

Follows the conventions of migrations 13/15: idempotent, safe to re-run, self-sufficient, documented at the top.

```sql
-- ============================================================
-- Migration 16 — discovery pipeline durability
--
-- Makes scraped jobs durable the moment they leave a scraper, and gives every
-- (user, listing) pair its own resumable stage state so a failure in JD
-- parsing / HR enrichment / scoring can never discard a scraping run.
--
-- Idempotent — safe to re-run. Until it is applied, the API degrades to the
-- previous in-memory pipeline (services/job_pipeline.py detects the missing
-- table once and logs a warning), so deferring it breaks nothing.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.job_pipeline_items (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id           UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  run_id            TEXT,
  job_listing_id    UUID NOT NULL REFERENCES public.job_listings(id) ON DELETE CASCADE,
  source_platform   TEXT,

  -- scraped → parsed → enriched → scored → done   (terminal: done | prefiltered)
  stage             TEXT NOT NULL DEFAULT 'scraped',
  -- pending | processing | failed
  stage_status      TEXT NOT NULL DEFAULT 'pending',

  attempts          INTEGER NOT NULL DEFAULT 0,
  max_attempts      INTEGER NOT NULL DEFAULT 3,
  last_error        TEXT,
  next_attempt_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  claimed_at        TIMESTAMPTZ,

  -- Output of the parse stage. Persisted so the score stage never re-pays for
  -- an LLM parse after a crash or retry.
  parsed_jd         JSONB,

  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT job_pipeline_items_stage_check
    CHECK (stage IN ('scraped','parsed','enriched','scored','done','prefiltered')),
  CONSTRAINT job_pipeline_items_status_check
    CHECK (stage_status IN ('pending','processing','failed'))
);

-- Idempotency: one work item per user per listing. Re-discovering the same job
-- is an upsert, never a duplicate.
CREATE UNIQUE INDEX IF NOT EXISTS idx_pipeline_items_user_listing
  ON public.job_pipeline_items(user_id, job_listing_id);

-- The drain query: "next N claimable items in stage X".
CREATE INDEX IF NOT EXISTS idx_pipeline_items_claimable
  ON public.job_pipeline_items(stage, stage_status, next_attempt_at);

CREATE INDEX IF NOT EXISTS idx_pipeline_items_run  ON public.job_pipeline_items(run_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_items_user ON public.job_pipeline_items(user_id, stage);

-- Reuse the existing updated_at trigger function from schema.sql.
DROP TRIGGER IF EXISTS trg_pipeline_items_updated ON public.job_pipeline_items;
CREATE TRIGGER trg_pipeline_items_updated
  BEFORE UPDATE ON public.job_pipeline_items
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ── Atomic batch claim ──────────────────────────────────────
-- FOR UPDATE SKIP LOCKED makes concurrent drains (inline run + cron, or two
-- processes) safe: each caller gets a disjoint set. PostgREST exposes this as
-- POST /rpc/claim_pipeline_items.
CREATE OR REPLACE FUNCTION public.claim_pipeline_items(
  p_stage TEXT,
  p_limit INTEGER DEFAULT 25,
  p_user_id UUID DEFAULT NULL
)
RETURNS SETOF public.job_pipeline_items AS $$
  UPDATE public.job_pipeline_items t
     SET stage_status = 'processing',
         claimed_at   = NOW(),
         updated_at   = NOW()
   WHERE t.id IN (
     SELECT i.id FROM public.job_pipeline_items i
      WHERE i.stage = p_stage
        AND i.stage_status = 'pending'
        AND i.next_attempt_at <= NOW()
        AND (p_user_id IS NULL OR i.user_id = p_user_id)
      ORDER BY i.created_at
      LIMIT p_limit
      FOR UPDATE SKIP LOCKED
   )
  RETURNING t.*;
$$ LANGUAGE sql;

-- ── Stale-claim reaper ──────────────────────────────────────
-- Releases items whose worker died mid-stage (crash, restart, SIGKILL).
CREATE OR REPLACE FUNCTION public.release_stale_pipeline_claims(p_minutes INTEGER DEFAULT 15)
RETURNS INTEGER AS $$
DECLARE n INTEGER;
BEGIN
  UPDATE public.job_pipeline_items
     SET stage_status = 'pending', claimed_at = NULL, updated_at = NOW()
   WHERE stage_status = 'processing'
     AND claimed_at < NOW() - (p_minutes || ' minutes')::INTERVAL;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END; $$ LANGUAGE plpgsql;

COMMENT ON TABLE public.job_pipeline_items IS
  'Durable per-(user,listing) work queue for post-scrape AI stages. A row exists
   from the moment a job is scraped, so no stage failure can discard scrape work.';
```

### 2.2 RLS

Service-role workers bypass RLS, and the table is never queried with the anon key today (the new `/discovery/queue` endpoint uses the admin client like the rest of `routers/discovery.py`). A policy is added to `database/rls_policies.sql` for symmetry:

```sql
ALTER TABLE public.job_pipeline_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own pipeline items" ON public.job_pipeline_items
  FOR SELECT USING (auth.uid() = user_id);
```

### 2.3 README

Add `database/16_pipeline_durability.sql` to the ordered migration list in the Supabase setup section, and to `PENDING_MIGRATIONS_BUNDLE.sql`.

---

## 3. New module: `apps/api/services/job_pipeline.py`

The only place that touches `job_pipeline_items`. Every function is non-fatal by contract — it logs and returns a falsy value rather than raising, matching the defensive style of `_upsert_job_listing`.

```python
# ── availability ──────────────────────────────────────────────
def pipeline_available() -> bool
    """False when migration 16 hasn't been applied (checked once, cached).
    Callers fall back to the legacy in-memory flow so a stale DB still works."""

# ── writing (scrape checkpoint) ───────────────────────────────
async def persist_scraped_batch(
    jobs: list[JobListingCreate],
    *, user_id: str, run_id: str, prefiltered: set[int] = frozenset(),
) -> list[str]
    """Upsert each job into job_listings and create/refresh its pipeline item.
    Returns the listing ids. Per-job try/except: one bad job never aborts the
    batch. Indices in `prefiltered` are stored with stage='prefiltered'.
    This is the durability checkpoint — called after every query result."""

# ── reading (stage workers) ───────────────────────────────────
def claim_batch(stage: str, limit: int, user_id: str | None = None) -> list[dict]
    """RPC claim_pipeline_items; falls back to select-then-conditional-update
    if the function is missing."""

def pending_counts(user_id: str) -> dict   # {stage: {pending, processing, failed}}

# ── state transitions ─────────────────────────────────────────
def advance(item_id: str, next_stage: str, **fields) -> bool
    """Atomically move to next_stage, status=pending, attempts=0, clear error.
    `fields` may carry parsed_jd."""

def fail(item_id: str, error: str, *, attempts: int, max_attempts: int,
         retry_after_seconds: int | None = None) -> bool
    """attempts+1; below max → pending with exponential backoff
    (2/4/8 min, or an explicit retry_after for budget waits);
    at max → stage_status='failed' (listing stays intact)."""

def requeue_failed(user_id: str, stage: str | None = None) -> int
    """Operator/UI action: reset failed items to pending, attempts=0."""

def release_stale_claims(minutes: int) -> int
```

---

## 4. Increment-by-increment changes

### Increment 0 — write isolation hotfix (no migration, no new files)

Purely defensive; ship immediately.

In [`workers/job_discovery.py`](../apps/api/workers/job_discovery.py):

- Wrap the Phase-5 body (lines 491–541) in a per-item `try/except`: on error, `logger.error`, `progress.log(run_id, ..., "error")`, `continue`. **This is the single fix that would have preserved the failed run's 108 evaluations.**
- Guard the `apply_queue` insert/update separately — a queueing failure must not lose the match record that was just written.
- Guard the `db.table("job_applications").upsert` result access (`app_res.data[0]`) against an empty response.
- Add `progress.update_counts(run_id, saved=n)` as the loop advances so partial progress is visible live.

Acceptance: monkeypatched DB that raises on the 3rd upsert → the other jobs still save, run completes with a warning instead of dying.

### Increment 1 — infrastructure

- Add `database/16_pipeline_durability.sql` (§2.1) and the RLS policy.
- Add `apps/api/services/job_pipeline.py` (§3).
- Config additions in [`config.py`](../apps/api/config.py):

  ```python
  # Durable discovery pipeline (migration 16). Scraped jobs are persisted
  # immediately; AI stages run off the queue and are independently retryable.
  PIPELINE_DURABLE_ENABLED: bool = True        # kill switch → legacy in-memory flow
  PIPELINE_BATCH_SIZE: int = 25                # items claimed per stage batch
  PIPELINE_MAX_ATTEMPTS: int = 3
  PIPELINE_CLAIM_TIMEOUT_MINUTES: int = 15     # stale-claim reaper threshold
  PIPELINE_DRAIN_INTERVAL_MINUTES: int = 5     # scheduled drain cadence
  PIPELINE_PERSIST_PREFILTERED: bool = True    # decision D1
  ```

- No call sites change yet. Behaviour identical.

### Increment 2 — persist at the scrape checkpoint

Rewrite the scrape loop in `_discover_for_user_async` so persistence happens per query result instead of per run:

```python
# ── Phase 1: scrape and PERSIST INCREMENTALLY ──
for src in sources:
    async with src.cls() as scraper:
        for query, loc in search_pairs:
            jobs = await _call_search(...)
            fresh = [j for j in jobs if _is_new(j)]          # dedup, unchanged
            if fresh:
                kept, dropped_idx = prefilter_partition(fresh, user)   # was Phase 1.5
                # ↓ DURABILITY CHECKPOINT — jobs are safe from here on
                await job_pipeline.persist_scraped_batch(
                    fresh, user_id=user_id, run_id=run_id, prefiltered=dropped_idx,
                )
            progress.query_result(run_id, src.name, query, len(jobs), len(fresh))
```

- `raw_jobs` as a run-lifetime accumulator is **deleted**. Nothing large stays in memory.
- The prefilter moves inside the loop and becomes a *partition* rather than a filter (D1): rejected jobs are persisted at `stage='prefiltered'`.
- Dedup sets additionally seeded from this user's existing `job_pipeline_items` (fixes F6).
- `_upsert_job_listing` keeps its column-stripping self-healing logic and moves into `job_pipeline.persist_scraped_batch` unchanged.

Acceptance: `kill -9` after source 3 → those jobs are queryable in `job_listings` and have `job_pipeline_items` rows at `stage='scraped'`.

### Increment 3 — stage workers

New `apps/api/workers/pipeline_worker.py`:

```python
async def run_stage_parse(user_id=None, limit=None)   -> StageResult
async def run_stage_enrich(user_id=None, limit=None)  -> StageResult
async def run_stage_score(user_id=None, limit=None)   -> StageResult
async def drain(user_id=None, run_id=None, progress_run=None) -> dict
    """Run parse → enrich → score repeatedly until no claimable items remain
    (or a safety cap on iterations). Used inline by discovery and by the cron."""
```

Each stage: `claim_batch` → do the work with the **existing** batch helpers (`batch_parse_jds`, `enrich_jobs`, `batch_score_jobs` — unchanged) → write results **per item** → `advance()` or `fail()`.

`_discover_for_user_async` after Phase 1 becomes:

```python
progress.set_phase(run_id, "analyzing", ...)
await pipeline_worker.drain(user_id=user_id, run_id=run_id, progress_run=run_id)
```

Phases 2 / 2.2 / 2.5 / 3 / 4 / 5 of the old function are deleted — their logic now lives in the stage workers, with these behaviour deltas:

- **Experience merge** (was Phase 2.2) runs in the parse stage and `UPDATE`s the already-stored listing.
- **HR enrichment** (was Phase 2.5) runs in the enrich stage, still non-fatal, and always advances.
- **Scoring** writes `job_applications` per item, immediately, each guarded (Increment 0's fix, now structural).
- **`BudgetExceededError`** → `fail(..., retry_after_seconds=<seconds to next UTC midnight>)` without consuming an attempt, instead of silently writing `score 0 / archived` (F11).

Acceptance: with the DB patched to fail on the 3rd `job_applications` upsert, items 1,2,4…N reach `done`, item 3 shows `attempts=1, next_attempt_at≈+2min`, and a second `drain()` completes it.

### Increment 4 — resumability

In [`scheduler.py`](../apps/api/scheduler.py):

```python
def _drain_pipeline_queue():
    """Finish post-scrape AI stages for any items a run left behind."""
    from workers.pipeline_worker import drain_all_users
    try:
        drain_all_users()
    except Exception as e:
        logger.error(f"Pipeline drain failed: {e}")

scheduler.add_job(_drain_pipeline_queue,
                  IntervalTrigger(minutes=settings.PIPELINE_DRAIN_INTERVAL_MINUTES),
                  id="pipeline_drain", name="Drain discovery processing queue",
                  replace_existing=True)
```

- The drain job runs **regardless of `DISCOVERY_SCHEDULER_ENABLED`** — that flag gates *starting new scrapes*, not finishing work already scraped. Documented in the flag's comment.
- The drain releases stale claims first (`release_stale_pipeline_claims`), same pattern as `recover_stuck_applications`.
- FastAPI lifespan startup: mark history runs still `running` as `interrupted`, and flush `discovery_runs.json` on every phase transition (`discovery_progress.set_phase`).

Acceptance: kill the server mid-scoring, restart → within one drain interval every item reaches `done` with **no re-scraping**.

### Increment 5 — observability

- `GET /discovery/queue` → `{stages: {...counts...}, failed: [{job_title, company, stage, last_error, attempts}], oldest_pending_at}`.
- `POST /discovery/queue/retry` → `job_pipeline.requeue_failed(user_id, stage=None)`.
- `discovery_progress`: stop overwriting `phase` on failure; add `failed_phase`; include `queue` counts in the snapshot.
- `activity-client.tsx`: stepper uses `failed_phase ?? phase` so the ✗ lands on the real stage; new "Processing queue" card under the source chips with a **Retry failed** button.

### Increment 6 — tests and backfill

41 new tests across four modules, on an in-memory PostgREST stand-in
(`tests/fake_supabase.py`) with a fault-injection hook that reproduces the exact
error from the incident.

| File | Tests | Covers |
|---|---|---|
| `test_job_pipeline.py` | 14 | `persist_scraped_batch` idempotency and per-job isolation; prefiltered jobs persisted; re-discovery never rewinds a finished item; `advance`/`fail` transitions; backoff growth; `max_attempts` → `failed`; budget wait does not consume an attempt; claim via RPC and via fallback; claim exclusivity; `pipeline_available()` false-path |
| `test_pipeline_worker.py` | 12 | each stage's happy path; parse output persisted for reuse; enrichment failure never blocks a job; **transient DB error costs one item, not the batch**; a retry completes the failed item; provider outage does not write false 0/archived verdicts; auto-apply queueing is idempotent; `drain` carries jobs end to end and resumes a half-processed run |
| `test_discovery_persistence.py` | 7 | **fault injection at parse / score / drain** → every scraped job still has a listing row and a queue item; no re-scrape on the follow-up run; persistence happens per query, not per run; prefiltered jobs stored; legacy path still persists without migration 16 |
| `test_discovery_progress.py` | 7 | `failed_phase` records where a run actually died; run written to disk before it finishes; phase checkpoints don't duplicate the record; interrupted-run recovery is correct and idempotent; `saved` tracked separately from `evaluated` |

Plus one addition to `test_discovery_scheduler_gate.py`: the pipeline drain must be
registered even when `DISCOVERY_SCHEDULER_ENABLED=false`.

One-off `scripts/backfill_orphan_listings.py` (decision D5): finds `job_listings` rows with no `job_applications` row for the user and enqueues them at `stage='scraped'` — recovers the incident's ~108 jobs without any scraping. Dry-run by default:

```bash
python scripts/backfill_orphan_listings.py --user <uuid> --since 2026-07-31 --apply
```

---

## 5. Rollback

| Increment | Rollback |
|---|---|
| 0 | `git revert` — pure try/except additions |
| 1 | Table is unused; drop it or leave it (inert) |
| 2–4 | `PIPELINE_DURABLE_ENABLED=false` in `.env` → the legacy in-memory path runs unchanged; already-queued items are drained by the cron and then idle |
| 5 | Frontend-only; revert the component |

The kill switch is the reason `_discover_for_user_async` keeps the legacy path until Increment 4 is proven in a real run.

---

## 6. Verification status

| Claim | How it was verified | Result |
|---|---|---|
| One transient DB error no longer aborts the save loop | `test_transient_db_error_costs_one_item_not_the_batch` injects the incident's exact `[Errno 8]` | ✅ 2 of 3 items complete, 1 retries |
| Scraped jobs survive a failure at any AI stage | `test_scraped_jobs_survive_any_downstream_failure[parse|score|drain]` | ✅ all listings + queue items intact |
| Persistence is per query, not per run | `test_jobs_are_persisted_before_the_source_finishes` | ✅ |
| A failed run does not re-scrape on the next attempt | `test_a_failed_run_does_not_rescrape_on_the_next_attempt` | ✅ zero new rows |
| An interrupted run self-completes | `test_drain_resumes_a_half_processed_run` (stranded claim released and finished) | ✅ |
| A provider outage doesn't bury jobs at score 0 | `test_provider_outage_does_not_bury_jobs_at_score_zero` | ✅ no application rows written |
| The drain runs even with discovery disabled | `test_pipeline_drain_runs_even_with_discovery_disabled` | ✅ |
| No regression | full suite | ✅ 329 passed |
| Frontend compiles and types check | `npx tsc --noEmit`, `/activity` route builds | ✅ |
| Authenticated Search Activity UI | **not verified** — the in-app browser has no logged-in session | ⚠️ needs a look after the migration |

### Still to do (manual)

1. Run `database/16_pipeline_durability.sql` in the Supabase SQL editor.
2. Restart the API (or let `--reload` pick it up) and confirm the log line
   `Drain discovery processing queue`.
3. Optionally recover the failed run's orphans with `scripts/backfill_orphan_listings.py`.
