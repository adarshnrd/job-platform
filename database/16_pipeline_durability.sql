-- ============================================================
-- Migration 16 — discovery pipeline durability
--
-- WHY: scraped jobs used to live only in a Python list until every AI stage
-- (JD parse → experience merge → HR enrichment → scoring) had finished. A
-- transient fault anywhere in that window discarded the entire run — one DNS
-- blip cost 7h47m of scraping and 108 completed evaluations.
--
-- WHAT: job_listings is now written the moment a scraper returns, and this
-- table carries the per-(user, listing) processing state so each AI stage can
-- fail, retry and resume on its own without ever touching the scrape output.
--
-- Design: docs/PIPELINE_DURABILITY_DESIGN.md
--
-- Idempotent — safe to re-run. Until it is applied, the API detects the
-- missing table once (services/job_pipeline.pipeline_available) and falls back
-- to the previous in-memory pipeline, so deferring this migration breaks
-- nothing — it just leaves the old failure mode in place.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.job_pipeline_items (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id           UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  run_id            TEXT,
  job_listing_id    UUID NOT NULL REFERENCES public.job_listings(id) ON DELETE CASCADE,
  source_platform   TEXT,

  -- scraped → parsed → enriched → scored → done
  -- terminal: done (fully processed) | prefiltered (rule-based reject, revivable)
  stage             TEXT NOT NULL DEFAULT 'scraped',
  -- pending (claimable) | processing (leased) | failed (attempts exhausted)
  stage_status      TEXT NOT NULL DEFAULT 'pending',

  attempts          INTEGER NOT NULL DEFAULT 0,
  max_attempts      INTEGER NOT NULL DEFAULT 3,
  last_error        TEXT,
  next_attempt_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  claimed_at        TIMESTAMPTZ,

  -- Output of the parse stage. Persisted so the score stage never re-pays for
  -- an LLM parse after a crash, a restart, or a scoring retry.
  parsed_jd         JSONB,

  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT job_pipeline_items_stage_check
    CHECK (stage IN ('scraped','parsed','enriched','scored','done','prefiltered')),
  CONSTRAINT job_pipeline_items_status_check
    CHECK (stage_status IN ('pending','processing','failed'))
);

-- Idempotency: one work item per user per listing. Re-discovering the same job
-- is an upsert, never a duplicate — and never a second LLM bill.
CREATE UNIQUE INDEX IF NOT EXISTS idx_pipeline_items_user_listing
  ON public.job_pipeline_items(user_id, job_listing_id);

-- The drain query: "next N claimable items in stage X".
CREATE INDEX IF NOT EXISTS idx_pipeline_items_claimable
  ON public.job_pipeline_items(stage, stage_status, next_attempt_at);

CREATE INDEX IF NOT EXISTS idx_pipeline_items_run  ON public.job_pipeline_items(run_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_items_user ON public.job_pipeline_items(user_id, stage);

-- Reuse the updated_at trigger function defined in schema.sql.
DROP TRIGGER IF EXISTS trg_pipeline_items_updated ON public.job_pipeline_items;
CREATE TRIGGER trg_pipeline_items_updated
  BEFORE UPDATE ON public.job_pipeline_items
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ── Atomic batch claim ──────────────────────────────────────
-- FOR UPDATE SKIP LOCKED makes concurrent drains safe (an inline discovery run
-- and the scheduled drain can overlap): each caller gets a disjoint set instead
-- of both processing — and both billing — the same jobs.
-- PostgREST exposes this as POST /rpc/claim_pipeline_items.
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
-- Releases items whose worker died mid-stage (crash, restart, SIGKILL) back to
-- the pending pool. Without this, a killed process would strand its in-flight
-- batch in 'processing' forever.
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

-- ── Row level security ──────────────────────────────────────
-- Workers use the service-role key (which bypasses RLS); this policy only
-- covers direct client reads.
ALTER TABLE public.job_pipeline_items ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "pipeline_items_own" ON public.job_pipeline_items
    FOR SELECT USING (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
