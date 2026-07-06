-- ============================================================
-- One-off cleanup — NOT a migration, run manually and review first.
-- Deletes job_applications + job_listings for jobs scoring <50%,
-- except listings whose JD mentions Node.js (node.js / node js / nodejs).
--
-- Safety notes:
--   - A listing is only deleted if it has NO application scoring >=50
--     (protects listings with mixed/re-scored results).
--   - Listings with match_score IS NULL (never scored) are left alone —
--     NULL is "unscored", not "below 50%".
--   - job_applications deletion cascades to application_status_history,
--     interview_prep, apply_queue, pending_questions (ON DELETE CASCADE);
--     question_bank.first_seen_app is set NULL (ON DELETE SET NULL).
--   - job_listings deletion cascades to job_embeddings.
--   - This is a hard, permanent delete. There is no undo short of a
--     Supabase point-in-time-recovery restore.
-- ============================================================

-- ── STEP 1 — PREVIEW: run this first and read the numbers before deleting ──
WITH targets AS (
  SELECT jl.id
  FROM job_listings jl
  WHERE EXISTS (
      SELECT 1 FROM job_applications ja
      WHERE ja.job_listing_id = jl.id AND ja.match_score < 50
    )
    AND NOT EXISTS (
      SELECT 1 FROM job_applications ja2
      WHERE ja2.job_listing_id = jl.id AND ja2.match_score >= 50
    )
    AND NOT (
      jl.jd_text ILIKE '%node.js%'
      OR jl.jd_text ILIKE '%node js%'
      OR jl.jd_text ILIKE '%nodejs%'
    )
)
SELECT
  (SELECT count(*) FROM targets) AS listings_to_delete,
  (SELECT count(*) FROM job_applications WHERE job_listing_id IN (SELECT id FROM targets)) AS applications_to_delete;

-- ── STEP 2 — Look at a sample of what will be removed ──
WITH targets AS (
  SELECT jl.id
  FROM job_listings jl
  WHERE EXISTS (
      SELECT 1 FROM job_applications ja
      WHERE ja.job_listing_id = jl.id AND ja.match_score < 50
    )
    AND NOT EXISTS (
      SELECT 1 FROM job_applications ja2
      WHERE ja2.job_listing_id = jl.id AND ja2.match_score >= 50
    )
    AND NOT (
      jl.jd_text ILIKE '%node.js%'
      OR jl.jd_text ILIKE '%node js%'
      OR jl.jd_text ILIKE '%nodejs%'
    )
)
SELECT jl.title, jl.company, jl.source_platform, ja.match_score
FROM job_listings jl
JOIN job_applications ja ON ja.job_listing_id = jl.id
WHERE jl.id IN (SELECT id FROM targets)
ORDER BY ja.match_score DESC
LIMIT 50;

-- ── STEP 3 — THE ACTUAL DELETE. Only run after checking the counts above. ──
-- Uncomment both statements below and run together (order matters — the
-- job_applications -> job_listings FK has no cascade, so applications must
-- go first or the job_listings delete will fail with a foreign-key error).

-- WITH targets AS (
--   SELECT jl.id
--   FROM job_listings jl
--   WHERE EXISTS (
--       SELECT 1 FROM job_applications ja
--       WHERE ja.job_listing_id = jl.id AND ja.match_score < 50
--     )
--     AND NOT EXISTS (
--       SELECT 1 FROM job_applications ja2
--       WHERE ja2.job_listing_id = jl.id AND ja2.match_score >= 50
--     )
--     AND NOT (
--       jl.jd_text ILIKE '%node.js%'
--       OR jl.jd_text ILIKE '%node js%'
--       OR jl.jd_text ILIKE '%nodejs%'
--     )
-- )
-- DELETE FROM job_applications WHERE job_listing_id IN (SELECT id FROM targets);
--
-- WITH targets AS (
--   SELECT jl.id
--   FROM job_listings jl
--   WHERE EXISTS (
--       SELECT 1 FROM job_applications ja
--       WHERE ja.job_listing_id = jl.id AND ja.match_score < 50
--     )
--     AND NOT EXISTS (
--       SELECT 1 FROM job_applications ja2
--       WHERE ja2.job_listing_id = jl.id AND ja2.match_score >= 50
--     )
--     AND NOT (
--       jl.jd_text ILIKE '%node.js%'
--       OR jl.jd_text ILIKE '%node js%'
--       OR jl.jd_text ILIKE '%nodejs%'
--     )
-- )
-- DELETE FROM job_listings WHERE id IN (SELECT id FROM targets);
