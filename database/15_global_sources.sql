-- ============================================================
-- Migration 15 — global source expansion
--
-- 1. Registers the new discovery sources in the `platform` enum.
-- 2. Adds users.discovery_region so a user can target a region explicitly
--    instead of having it inferred from preferred_locations.
--
-- Idempotent — safe to re-run. Until it is applied, listings from the new
-- sources are stored with source_platform='other' (the upsert in
-- workers/job_discovery._upsert_job_listing self-heals), and discovery_region
-- is simply absent so region inference behaves exactly as before. Nothing
-- breaks by deferring it.
--
-- NOTE: ALTER TYPE ... ADD VALUE cannot run inside a transaction block on
-- PostgreSQL < 12, and a newly added enum value cannot be used in the same
-- transaction that added it. Run this file on its own (the Supabase SQL
-- editor does exactly that), not bundled into a larger transaction.
-- ============================================================

-- ── 1. New platform enum values ─────────────────────────────
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'arc';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'welcometothejungle';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'peerlist';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'flexjobs';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'google_jobs';

-- ── 2. Explicit discovery region ────────────────────────────
-- NULL means "infer from preferred_locations" (the previous behaviour), so
-- existing rows keep working untouched.
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS discovery_region TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'users_discovery_region_check'
  ) THEN
    ALTER TABLE public.users
      ADD CONSTRAINT users_discovery_region_check
      CHECK (discovery_region IS NULL OR discovery_region IN ('india', 'global'));
  END IF;
END $$;

COMMENT ON COLUMN public.users.discovery_region IS
  'Explicit discovery region: india | global. NULL infers from preferred_locations.';
