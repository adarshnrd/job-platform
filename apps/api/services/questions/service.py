"""
QuestionService — bank CRUD, pending-question lifecycle, and application resume.

All persistence for the Answer Bank lives here so routers and the resolver share
one implementation. Uses the admin client; RLS still protects the API surface
because routers scope every call by the authenticated user_id.
"""
from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger

from database import get_db
from services.questions.schema import (
    FormQuestion, normalize_question, hash_question, infer_type,
)
from services.questions.matcher import classify_profile_field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class QuestionService:
    def __init__(self):
        self.db = get_db()

    # ── Question bank ────────────────────────────────────────────────────
    def upsert_question(self, user_id: str, q: FormQuestion,
                        application_id: str | None = None) -> str | None:
        """Insert the question if new (by hash); return its id.

        Idempotent on (user_id, question_hash). Records the detected type,
        options, and the profile category so the UI can group/label it.
        """
        category, profile_field = classify_profile_field(q.text)
        qtype = q.qtype or infer_type(q.text)
        row = {
            "user_id": user_id,
            "question_text": q.text.strip(),
            "question_norm": normalize_question(q.text),
            "question_hash": hash_question(q.text),
            "question_type": qtype,
            "options": q.options or [],
            "category": category,
            "profile_field": profile_field,
            "source_platform": q.platform or None,
            "first_seen_app": application_id,
        }
        try:
            res = self.db.table("question_bank").upsert(
                row, on_conflict="user_id,question_hash"
            ).execute()
            if res.data:
                return res.data[0]["id"]
        except Exception as e:
            logger.warning(f"question_bank upsert failed: {e}")
        # Fall back to a read if upsert returned nothing.
        try:
            existing = (
                self.db.table("question_bank").select("id")
                .eq("user_id", user_id).eq("question_hash", row["question_hash"])
                .limit(1).execute()
            )
            if existing.data:
                return existing.data[0]["id"]
        except Exception:
            pass
        return None

    def list_bank(self, user_id: str, search: str = "", category: str = "") -> list[dict]:
        """Return the user's questions joined with their active answer."""
        q = self.db.table("question_bank").select("*").eq("user_id", user_id)
        if category:
            q = q.eq("category", category)
        questions = (q.order("created_at", desc=True).execute().data) or []
        if search:
            s = search.lower()
            questions = [x for x in questions if s in (x.get("question_text") or "").lower()]

        answers = (
            self.db.table("user_answers").select("*")
            .eq("user_id", user_id).eq("is_active", True).execute().data
        ) or []
        ans_by_q = {a["question_id"]: a for a in answers}

        out = []
        for qb in questions:
            a = ans_by_q.get(qb["id"])
            out.append({
                **qb,
                "answer": (a or {}).get("answer", {}).get("value") if a else None,
                "answer_source": (a or {}).get("source") if a else None,
                "times_used": (a or {}).get("times_used", 0) if a else 0,
                "last_used_at": (a or {}).get("last_used_at") if a else None,
                "is_answered": a is not None,
                "is_profile_mapped": bool(qb.get("profile_field")),
            })
        return out

    def find_banked(self, user_id: str, question_text: str) -> dict | None:
        """Look up a saved answer for a question (exact hash then trigram)."""
        from services.questions.matcher import find_banked_answer
        return find_banked_answer(self.db, user_id, question_text)

    # ── Answers ──────────────────────────────────────────────────────────
    def save_answer(self, user_id: str, question_id: str, value,
                    source: str = "user") -> dict:
        """Create or update the answer for a question."""
        row = {
            "user_id": user_id,
            "question_id": question_id,
            "answer": {"value": value},
            "source": source,
            "is_active": True,
        }
        res = self.db.table("user_answers").upsert(
            row, on_conflict="user_id,question_id"
        ).execute()
        return res.data[0] if res.data else row

    def create_manual(self, user_id: str, question_text: str, value,
                      qtype: str = "text", category: str = "custom") -> dict:
        """Let the user add a Q/A directly (not triggered by an application)."""
        qid = self.upsert_question(user_id, FormQuestion(text=question_text, qtype=qtype))
        if not qid:
            raise RuntimeError("Could not create question")
        # Honor an explicit non-default category (upsert derives 'custom' otherwise).
        if category and category != "custom":
            try:
                self.db.table("question_bank").update({"category": category})\
                    .eq("id", qid).eq("user_id", user_id).execute()
            except Exception:
                pass
        return self.save_answer(user_id, qid, value, source="user")

    def update_answer(self, user_id: str, answer_id: str, value) -> dict:
        res = (
            self.db.table("user_answers")
            .update({"answer": {"value": value}, "source": "user", "is_active": True})
            .eq("id", answer_id).eq("user_id", user_id).execute()
        )
        return res.data[0] if res.data else {}

    def delete_answer(self, user_id: str, answer_id: str) -> None:
        """Soft-delete so the question stays known but stops auto-filling."""
        self.db.table("user_answers").update({"is_active": False})\
            .eq("id", answer_id).eq("user_id", user_id).execute()

    def record_usage(self, user_id: str, question_id: str) -> None:
        """Bump usage stats when a banked answer auto-fills a form."""
        try:
            cur = (
                self.db.table("user_answers").select("id, times_used")
                .eq("user_id", user_id).eq("question_id", question_id)
                .maybe_single().execute()
            )
            if cur and cur.data:
                self.db.table("user_answers").update({
                    "times_used": (cur.data.get("times_used") or 0) + 1,
                    "last_used_at": _now(),
                }).eq("id", cur.data["id"]).execute()
        except Exception:
            pass

    # ── Pending questions ────────────────────────────────────────────────
    def add_pending(self, user_id: str, application_id: str, question_id: str,
                    raw_context: dict | None = None) -> None:
        try:
            self.db.table("pending_questions").upsert({
                "user_id": user_id,
                "application_id": application_id,
                "question_id": question_id,
                "status": "pending",
                "raw_context": raw_context or {},
            }, on_conflict="application_id,question_id").execute()
        except Exception as e:
            logger.warning(f"pending_questions insert failed: {e}")

    def list_pending(self, user_id: str) -> list[dict]:
        """Pending questions grouped with their question + job context."""
        pend = (
            self.db.table("pending_questions").select("*")
            .eq("user_id", user_id).eq("status", "pending")
            .order("created_at", desc=True).execute().data
        ) or []
        if not pend:
            return []

        q_ids = list({p["question_id"] for p in pend})
        app_ids = list({p["application_id"] for p in pend})
        questions = {
            q["id"]: q for q in (
                self.db.table("question_bank").select("*").in_("id", q_ids).execute().data or []
            )
        }
        apps = {
            a["id"]: a for a in (
                self.db.table("application_details")
                .select("id, job_title, job_company, source_platform")
                .in_("id", app_ids).execute().data or []
            )
        }
        out = []
        for p in pend:
            q = questions.get(p["question_id"], {})
            a = apps.get(p["application_id"], {})
            out.append({
                "pending_id": p["id"],
                "application_id": p["application_id"],
                "question_id": p["question_id"],
                "question_text": q.get("question_text"),
                "question_type": q.get("question_type", "text"),
                "options": q.get("options", []),
                "category": q.get("category", "custom"),
                "job_title": a.get("job_title"),
                "job_company": a.get("job_company"),
                "source_platform": a.get("source_platform"),
                "created_at": p["created_at"],
            })
        return out

    def answer_pending(self, user_id: str, pending_id: str, value) -> dict:
        """Persist the user's answer and re-queue every application it unblocks."""
        pend = (
            self.db.table("pending_questions").select("*")
            .eq("id", pending_id).eq("user_id", user_id).maybe_single().execute()
        )
        if not (pend and pend.data):
            raise RuntimeError("Pending question not found")
        question_id = pend.data["question_id"]

        self.save_answer(user_id, question_id, value, source="user")

        # Mark every pending row for this question answered (one answer unblocks all).
        self.db.table("pending_questions").update(
            {"status": "answered", "resolved_at": _now()}
        ).eq("user_id", user_id).eq("question_id", question_id).eq("status", "pending").execute()

        requeued = self._requeue_unblocked(user_id, question_id)
        return {"success": True, "requeued_applications": requeued}

    def skip_pending(self, user_id: str, pending_id: str) -> dict:
        self.db.table("pending_questions").update(
            {"status": "skipped", "resolved_at": _now()}
        ).eq("id", pending_id).eq("user_id", user_id).execute()
        return {"success": True}

    def _requeue_unblocked(self, user_id: str, question_id: str) -> int:
        """Re-queue applications that were paused on this question and now have
        no other pending questions left."""
        rows = (
            self.db.table("pending_questions").select("application_id")
            .eq("user_id", user_id).eq("question_id", question_id).execute().data
        ) or []
        app_ids = list({r["application_id"] for r in rows})
        requeued = 0
        for app_id in app_ids:
            still = (
                self.db.table("pending_questions").select("id")
                .eq("application_id", app_id).eq("status", "pending").execute().data
            ) or []
            if still:
                continue  # other questions still block this application
            app = (
                self.db.table("job_applications").select("id, status")
                .eq("id", app_id).eq("user_id", user_id).maybe_single().execute()
            )
            if app and app.data and app.data.get("status") == "needs_input":
                self.db.table("job_applications").update({"status": "queued"})\
                    .eq("id", app_id).execute()
                self.db.table("apply_queue").update(
                    {"status": "pending", "error_msg": None}
                ).eq("application_id", app_id).eq("status", "awaiting_input").execute()
                requeued += 1
        return requeued
