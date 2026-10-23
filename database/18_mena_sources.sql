-- ============================================================
-- Migration 18 — MENA regional board sources (docs/mena/PHASE_2_REGIONAL_BOARDS.md)
--
-- Registers the new MENA discovery sources in the `platform` enum:
--   sabbar (KSA), emploitic (Algeria), keejob (Tunisia), rekrute (Morocco).
-- foundit already exists in the enum (Gulf is the same scraper).
--
-- Idempotent — safe to re-run. Until it is applied, listings from the new
-- sources are stored with source_platform='other' (the upsert in
-- workers/job_discovery._upsert_job_listing self-heals), so nothing breaks by
-- deferring it.
--
-- NOTE: ALTER TYPE ... ADD VALUE cannot run inside a transaction block on
-- PostgreSQL < 12, and a newly added enum value cannot be used in the same
-- transaction that added it. Run this file on its own (the Supabase SQL
-- editor does exactly that), not bundled into a larger transaction.
-- ============================================================

ALTER TYPE platform ADD VALUE IF NOT EXISTS 'sabbar';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'emploitic';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'keejob';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'rekrute';
