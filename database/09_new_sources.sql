-- ============================================================
-- Migration 09 — Phase 3/4 job sources
-- Adds new values to the `platform` enum. Run once. Idempotent.
-- ============================================================

ALTER TYPE platform ADD VALUE IF NOT EXISTS 'iimjobs';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'timesjobs';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'shine';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'freshersworld';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'ycombinator';
