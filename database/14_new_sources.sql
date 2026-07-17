-- ============================================================
-- Migration 14 — new discovery sources (phase: portal expansion)
-- Registers the Jobicy and Himalayas remote boards in the platform enum.
-- (Workable / SmartRecruiters / Recruitee ride the existing ATS aggregator
-- under 'company_portal' — no enum change needed for them.)
-- Idempotent. Until applied, listings from these sources are stored with
-- source_platform='other' (the upsert self-heals), so nothing breaks.
-- ============================================================

ALTER TYPE platform ADD VALUE IF NOT EXISTS 'jobicy';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'himalayas';
