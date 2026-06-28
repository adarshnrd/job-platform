-- ============================================================
-- Migration 02 — API-first job sources
-- Adds new values to the `platform` enum for the API-based sources.
-- Run once in the Supabase SQL editor. Idempotent.
-- ============================================================

ALTER TYPE platform ADD VALUE IF NOT EXISTS 'remotive';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'arbeitnow';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'themuse';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'adzuna';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'jooble';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'jsearch';
