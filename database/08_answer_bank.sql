-- ============================================================
-- Migration 08 — Answer Bank
-- Persistent, user-managed store of application-question answers:
-- detect a question → fill from profile/bank → pause (needs_input) when
-- unknown → user answers once → reused across all portals forever.
-- Idempotent. Requires the pg_trgm extension for fuzzy question matching.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- New lifecycle states
ALTER TYPE application_status  ADD VALUE IF NOT EXISTS 'needs_input';
ALTER TYPE notification_type   ADD VALUE IF NOT EXISTS 'input_needed';

-- ── Canonical questions seen across portals ──────────────────────────
CREATE TABLE IF NOT EXISTS public.question_bank (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  question_text   TEXT NOT NULL,             -- as seen on the portal
  question_norm   TEXT NOT NULL,             -- normalized form (lowercased, stripped)
  question_hash   TEXT NOT NULL,             -- sha256(question_norm)
  question_type   TEXT NOT NULL DEFAULT 'text',
    -- text | textarea | numeric | boolean | single_select | multi_select | date
  options         JSONB DEFAULT '[]',        -- choices for selects/radios
  category        TEXT DEFAULT 'custom',
    -- salary | notice_period | work_auth | relocation | experience
    -- | skill_experience | education | certification | availability | custom
  profile_field   TEXT,                      -- non-null ⇒ resolve live from users.<col>
  source_platform TEXT,
  first_seen_app  UUID REFERENCES public.job_applications(id) ON DELETE SET NULL,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, question_hash)
);
CREATE INDEX IF NOT EXISTS idx_qbank_user ON public.question_bank(user_id);
CREATE INDEX IF NOT EXISTS idx_qbank_trgm
  ON public.question_bank USING GIN (question_norm gin_trgm_ops);

-- ── The user's saved answers ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.user_answers (
  id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id       UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  question_id   UUID NOT NULL REFERENCES public.question_bank(id) ON DELETE CASCADE,
  answer        JSONB NOT NULL,              -- {"value": ...} typed by question_type
  source        TEXT NOT NULL DEFAULT 'user',-- user | ai_draft_user_approved
  is_active     BOOLEAN DEFAULT TRUE,        -- soft delete
  times_used    INTEGER DEFAULT 0,
  last_used_at  TIMESTAMPTZ,
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  updated_at    TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_user_answers_user ON public.user_answers(user_id);

-- ── Questions currently blocking an application ──────────────────────
CREATE TABLE IF NOT EXISTS public.pending_questions (
  id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id        UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  application_id UUID NOT NULL REFERENCES public.job_applications(id) ON DELETE CASCADE,
  question_id    UUID NOT NULL REFERENCES public.question_bank(id) ON DELETE CASCADE,
  status         TEXT DEFAULT 'pending',     -- pending | answered | skipped
  raw_context    JSONB DEFAULT '{}',         -- selector, page URL, options snapshot
  created_at     TIMESTAMPTZ DEFAULT NOW(),
  resolved_at    TIMESTAMPTZ,
  UNIQUE(application_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_pending_q_user_status
  ON public.pending_questions(user_id, status);

-- ── updated_at trigger on user_answers ──
DROP TRIGGER IF EXISTS trg_user_answers_updated_at ON public.user_answers;
CREATE TRIGGER trg_user_answers_updated_at
  BEFORE UPDATE ON public.user_answers
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ── Row-level security (owner-only) ──
ALTER TABLE public.question_bank     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_answers      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pending_questions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "question_bank_own" ON public.question_bank;
CREATE POLICY "question_bank_own" ON public.question_bank
  FOR ALL USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "user_answers_own" ON public.user_answers;
CREATE POLICY "user_answers_own" ON public.user_answers
  FOR ALL USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "pending_questions_own" ON public.pending_questions;
CREATE POLICY "pending_questions_own" ON public.pending_questions
  FOR ALL USING (auth.uid() = user_id);

-- ── Fuzzy question matcher (trigram similarity) ──
-- Returns the user's banked questions most similar to a normalized query,
-- above a threshold, best match first. Called from services/questions/matcher.py.
CREATE OR REPLACE FUNCTION public.find_similar_question(
  p_user_id UUID,
  p_norm TEXT,
  p_threshold FLOAT DEFAULT 0.55,
  p_limit INTEGER DEFAULT 3
)
RETURNS TABLE(
  id UUID,
  question_text TEXT,
  question_type TEXT,
  category TEXT,
  profile_field TEXT,
  similarity REAL
) AS $$
  SELECT qb.id, qb.question_text, qb.question_type, qb.category, qb.profile_field,
         similarity(qb.question_norm, p_norm) AS similarity
  FROM public.question_bank qb
  WHERE qb.user_id = p_user_id
    AND similarity(qb.question_norm, p_norm) >= p_threshold
  ORDER BY similarity DESC
  LIMIT p_limit;
$$ LANGUAGE sql STABLE SECURITY DEFINER;
