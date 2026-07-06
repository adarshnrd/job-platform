-- ============================================================
-- Migration 10 — Manual Apply lane
-- When the bot cannot submit an application (no automation adapter,
-- exhausted retries), the application moves to 'manual_apply' instead
-- of silently reappearing in the approval queue. The user completes
-- it from the Approve Jobs → Manual Apply section. Idempotent.
-- ============================================================

ALTER TYPE application_status ADD VALUE IF NOT EXISTS 'manual_apply';
