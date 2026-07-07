-- ============================================================
-- Migration 11 — Content-level job dedup
-- Run once in the Supabase SQL editor. Idempotent.
--
-- Problem: job_listings dedups on source_url alone, but portals mint a fresh
-- URL for every repost of the same role (observed: one Naukri posting stored
-- 15x), so the same title+company piles up as separate listings and shows up
-- as duplicate rows on the Applications page.
--
-- This migration:
--   1. adds job_listings.dedupe_key (normalized title+company) + trigger
--   2. merges existing duplicates: keeps one application per (user, role) —
--      preferring rows with applied history — and the oldest listing
--   3. enforces uniqueness with a unique index
--
-- Keep job_dedupe_key() in sync with services/dedup.py.
-- ============================================================

-- ── 1. Column + normalization function + trigger ──

ALTER TABLE public.job_listings ADD COLUMN IF NOT EXISTS dedupe_key TEXT;

CREATE OR REPLACE FUNCTION public.job_dedupe_key(p_title TEXT, p_company TEXT)
RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
  WITH norm AS (
    SELECT
      trim(regexp_replace(regexp_replace(lower(coalesce(p_title, '')),
        '[^a-z0-9]+', ' ', 'g'), '\s+', ' ', 'g')) AS t,
      trim(regexp_replace(regexp_replace(lower(coalesce(p_company, '')),
        '[^a-z0-9]+', ' ', 'g'), '\s+', ' ', 'g')) AS c
  )
  SELECT t || '::' || coalesce(
    -- strip legal suffixes ("Accenture Solutions Pvt Ltd" → "accenture solutions"),
    -- but never collapse a company name to empty
    nullif(trim(regexp_replace(regexp_replace(c,
      '\m(private|pvt|ltd|limited|inc|incorporated|llc|llp|corp|corporation|co)\M',
      ' ', 'g'), '\s+', ' ', 'g')), ''),
    c)
  FROM norm
$$;

CREATE OR REPLACE FUNCTION public.set_job_dedupe_key()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.dedupe_key IS NULL OR NEW.dedupe_key = '' THEN
    NEW.dedupe_key := public.job_dedupe_key(NEW.title, NEW.company);
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_job_listings_dedupe_key ON public.job_listings;
CREATE TRIGGER trg_job_listings_dedupe_key
  BEFORE INSERT ON public.job_listings
  FOR EACH ROW EXECUTE FUNCTION public.set_job_dedupe_key();

UPDATE public.job_listings
SET dedupe_key = public.job_dedupe_key(title, company)
WHERE dedupe_key IS NULL OR dedupe_key = '';

-- ── 2. Merge existing duplicates ──

-- 2a. One application per (user, role): prefer rows already in applied
--     history, then the oldest. Dependents (status history, interview prep,
--     apply_queue, application events) go with them via ON DELETE CASCADE.
WITH keyed AS (
  SELECT a.id, a.user_id, a.status, a.created_at, l.dedupe_key
  FROM public.job_applications a
  JOIN public.job_listings l ON l.id = a.job_listing_id
),
ranked AS (
  SELECT id, row_number() OVER (
    PARTITION BY user_id, dedupe_key
    ORDER BY
      (status IN ('applied','under_review','assessment','interview_scheduled',
                  'technical_round','hr_round','offer_received','accepted','rejected')) DESC,
      created_at ASC, id
  ) AS rn
  FROM keyed
)
DELETE FROM public.job_applications
WHERE id IN (SELECT id FROM ranked WHERE rn > 1);

-- 2b. Repoint surviving applications onto the keeper listing (oldest per key).
WITH keepers AS (
  SELECT dedupe_key, (array_agg(id ORDER BY created_at ASC, id))[1] AS keeper_id
  FROM public.job_listings
  GROUP BY dedupe_key
)
UPDATE public.job_applications a
SET job_listing_id = k.keeper_id
FROM public.job_listings l
JOIN keepers k ON k.dedupe_key = l.dedupe_key
WHERE l.id = a.job_listing_id
  AND a.job_listing_id <> k.keeper_id;

-- 2c. Drop the now-orphaned duplicate listings (job_embeddings cascades).
WITH keepers AS (
  SELECT dedupe_key, (array_agg(id ORDER BY created_at ASC, id))[1] AS keeper_id
  FROM public.job_listings
  GROUP BY dedupe_key
)
DELETE FROM public.job_listings l
USING keepers k
WHERE l.dedupe_key = k.dedupe_key
  AND l.id <> k.keeper_id;

-- ── 3. Enforce uniqueness going forward ──
CREATE UNIQUE INDEX IF NOT EXISTS idx_job_listings_dedupe_key
  ON public.job_listings(dedupe_key);
