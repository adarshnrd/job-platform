-- ============================================================
-- Migration 17 — MENA region foundations (docs/mena/PHASE_0_FOUNDATIONS.md)
--
-- 1. Widens users.discovery_region to accept 'mena'.
-- 2. Makes job_dedupe_key() Unicode-aware (Arabic, accented Latin) and adds
--    MENA/French company legal suffixes, in parity with services/dedup.py.
--
-- Idempotent — safe to re-run. Until it is applied, saving
-- discovery_region = 'mena' is rejected by the old CHECK constraint (runs that
-- pass region='mena' explicitly still work), and the SQL dedupe function stays
-- ASCII-only; that function is only a fallback because the Python pipeline
-- always sends dedupe_key itself (services/job_pipeline.py).
--
-- No platform enum values here: each phase adds its own enum migration.
-- No backfill: ASCII title normalization is unchanged, and recomputing the few
-- non-ASCII keys could collide on the unique index. The one intended change
-- for existing ASCII data is that companies ending in a new noise token
-- (PLC, PJSC, SPA, ...) now drop it, so an already-stored listing for such a
-- company can be re-inserted once under the new key (a harmless one-off
-- duplicate).
-- ============================================================

-- ── 1. Region check ─────────────────────────────────────────
ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_discovery_region_check;
ALTER TABLE public.users
  ADD CONSTRAINT users_discovery_region_check
  CHECK (discovery_region IS NULL OR discovery_region IN ('india', 'global', 'mena'));

COMMENT ON COLUMN public.users.discovery_region IS
  'Explicit discovery region: india | global | mena. NULL infers from preferred_locations.';

-- ── 2. Unicode-aware dedupe key ─────────────────────────────
-- Keep in sync with services/dedup.py. The bracket expression strips Arabic
-- diacritics (U+064B-U+065F), superscript alef (U+0670) and tatweel (U+0640)
-- but NOT the Arabic-Indic digits U+0660-0669.
-- normalize(text, NFKC) needs PostgreSQL 13+ (Supabase has it).
-- Verify: SELECT public.job_dedupe_key('مهندس برمجيات', 'شركة علم');
--         -- must return  مهندس برمجيات::علم
CREATE OR REPLACE FUNCTION public.job_dedupe_key(p_title TEXT, p_company TEXT)
RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
  WITH norm AS (
    SELECT
      trim(regexp_replace(regexp_replace(regexp_replace(lower(normalize(coalesce(p_title, ''), NFKC)),
        '[ً-ٰٟـ]', '', 'g'),
        '[^[:alnum:]]+', ' ', 'g'), '\s+', ' ', 'g')) AS t,
      trim(regexp_replace(regexp_replace(regexp_replace(lower(normalize(coalesce(p_company, ''), NFKC)),
        '[ً-ٰٟـ]', '', 'g'),
        '[^[:alnum:]]+', ' ', 'g'), '\s+', ' ', 'g')) AS c
  )
  SELECT t || '::' || coalesce(
    -- strip legal suffixes ("Accenture Solutions Pvt Ltd" → "accenture solutions"),
    -- but never collapse a company name to empty
    nullif(trim(regexp_replace(regexp_replace(c,
      '\m(private|pvt|ltd|limited|inc|incorporated|llc|llp|corp|corporation|co|fz|fze|fzco|fzc|wll|w l l|spc|saog|saoc|sae|s a e|pjsc|psc|plc|sarl|s a r l|spa|sas|est|شركة|مؤسسة|المحدودة|ذ م م)\M',
      ' ', 'g'), '\s+', ' ', 'g')), ''),
    c)
  FROM norm
$$;
-- The set_job_dedupe_key() trigger from migration 11 is unchanged.
