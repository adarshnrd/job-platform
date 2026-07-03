-- ============================================================
-- Migration 07 — Per-user scheduled-discovery preference
-- Lets a user opt out of the background discovery cron without
-- disabling auto-apply. Defaults TRUE so existing behavior is kept.
-- Idempotent.
-- ============================================================

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS auto_discovery_enabled BOOLEAN DEFAULT TRUE;
