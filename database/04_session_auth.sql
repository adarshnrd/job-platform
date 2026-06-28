-- ============================================================
-- Migration 04 — Session-Based Authentication
-- Replaces password storage with encrypted session cookies.
-- Run once in the Supabase SQL editor. Idempotent.
-- ============================================================

-- Add session_expired to notification_type enum
ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'session_expired';

-- ============================================================
-- PLATFORM SESSIONS — encrypted browser session storage
-- ============================================================
CREATE TABLE IF NOT EXISTS public.platform_sessions (
  id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id              UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  platform             platform NOT NULL,

  -- Encrypted payload (Fernet ciphertext, base64-encoded)
  cookies_ciphertext   TEXT NOT NULL,
  metadata_ciphertext  TEXT,

  -- Plaintext metadata (safe to query without decryption)
  encryption_version   INTEGER NOT NULL DEFAULT 1,
  platform_user_id     TEXT,
  platform_username    TEXT,

  -- Lifecycle
  status               TEXT NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active', 'expired', 'invalid', 'revoked', 'pending_validation')),
  captured_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_validated_at    TIMESTAMPTZ,
  last_used_at         TIMESTAMPTZ,
  expires_at           TIMESTAMPTZ NOT NULL,
  invalidated_at       TIMESTAMPTZ,
  invalidation_reason  TEXT,

  -- Usage tracking
  use_count            INTEGER NOT NULL DEFAULT 0,
  success_count        INTEGER NOT NULL DEFAULT 0,
  failure_count        INTEGER NOT NULL DEFAULT 0,

  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE(user_id, platform)
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_platform
  ON public.platform_sessions(user_id, platform);
CREATE INDEX IF NOT EXISTS idx_sessions_status_expires
  ON public.platform_sessions(status, expires_at)
  WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_sessions_health_check
  ON public.platform_sessions(last_validated_at)
  WHERE status = 'active';

-- updated_at trigger
CREATE TRIGGER trg_platform_sessions_updated_at
  BEFORE UPDATE ON public.platform_sessions
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- SESSION AUDIT EVENTS — immutable lifecycle log
-- ============================================================
CREATE TABLE IF NOT EXISTS public.session_audit_events (
  id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id      UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  session_id   UUID REFERENCES public.platform_sessions(id) ON DELETE SET NULL,
  platform     platform NOT NULL,
  event_type   TEXT NOT NULL CHECK (event_type IN (
                 'session_created',
                 'session_renewed',
                 'session_validated',
                 'validation_failed',
                 'session_expired',
                 'session_invalidated',
                 'session_revoked',
                 'reauth_required',
                 'reauth_completed',
                 'application_attempted',
                 'application_succeeded',
                 'application_failed'
               )),
  metadata     JSONB NOT NULL DEFAULT '{}',
  ip_address   INET,
  user_agent   TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_user_created
  ON public.session_audit_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_session
  ON public.session_audit_events(session_id, created_at DESC);

-- ============================================================
-- AUTH HANDSHAKES — tracks in-progress browser login flows
-- ============================================================
CREATE TABLE IF NOT EXISTS public.auth_handshakes (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  handshake_token TEXT NOT NULL UNIQUE,
  user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  platform        platform NOT NULL,
  status          TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'browser_opened', 'completed', 'failed', 'timeout')),
  session_id      UUID REFERENCES public.platform_sessions(id),
  error_message   TEXT,
  expires_at      TIMESTAMPTZ NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_handshake_token
  ON public.auth_handshakes(handshake_token);
CREATE INDEX IF NOT EXISTS idx_handshake_user_status
  ON public.auth_handshakes(user_id, status);

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================
ALTER TABLE public.platform_sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "sessions_own_select" ON public.platform_sessions
  FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "sessions_own_insert" ON public.platform_sessions
  FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "sessions_own_update" ON public.platform_sessions
  FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "sessions_own_delete" ON public.platform_sessions
  FOR DELETE USING (auth.uid() = user_id);

ALTER TABLE public.session_audit_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "audit_own_select" ON public.session_audit_events
  FOR SELECT USING (auth.uid() = user_id);
-- INSERT only via service_role (audit logger uses admin client)

ALTER TABLE public.auth_handshakes ENABLE ROW LEVEL SECURITY;
CREATE POLICY "handshakes_own_select" ON public.auth_handshakes
  FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "handshakes_own_insert" ON public.auth_handshakes
  FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "handshakes_own_update" ON public.auth_handshakes
  FOR UPDATE USING (auth.uid() = user_id);

-- ============================================================
-- DEPRECATE old platform_credentials (soft — keep for rollback)
-- ============================================================
-- After verifying session-based auth works in production, run:
--   DROP TABLE platform_credentials;
-- For now, add a deprecation marker:
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'platform_credentials') THEN
    COMMENT ON TABLE public.platform_credentials IS
      'DEPRECATED — replaced by platform_sessions (migration 04). Do not use for new code.';
  END IF;
END $$;
