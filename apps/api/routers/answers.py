"""Answer Bank router — manage saved application answers and resolve pending ones."""
from auth import get_user_id
from fastapi import APIRouter, Depends, Body, HTTPException
from loguru import logger

from services.questions import QuestionService

router = APIRouter(prefix="/answers", tags=["answers"])

_service = QuestionService()

MIGRATION_HINT = (
    "Answer Bank tables are missing. Run database/08_answer_bank.sql in the "
    "Supabase SQL Editor, then try again."
)


def _guard(e: Exception):
    msg = str(e).lower()
    if "does not exist" in msg or "could not find" in msg or "relation" in msg:
        logger.error(f"Answer Bank read failed — migration not applied. ({e})")
        raise HTTPException(status_code=503, detail=MIGRATION_HINT)
    raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_answers(search: str = "", category: str = "", user_id: str = Depends(get_user_id)):
    """List the user's banked questions joined with their active answers."""
    try:
        return {"answers": _service.list_bank(user_id, search=search, category=category)}
    except Exception as e:
        _guard(e)


@router.post("")
async def create_answer(body: dict = Body(...), user_id: str = Depends(get_user_id)):
    """Manually add a question/answer pair."""
    question = (body.get("question_text") or "").strip()
    value = body.get("value")
    if not question or value in (None, ""):
        raise HTTPException(status_code=400, detail="question_text and value are required")
    try:
        row = _service.create_manual(
            user_id, question, value,
            qtype=body.get("question_type", "text"),
            category=body.get("category", "custom"),
        )
        return {"success": True, "answer": row}
    except Exception as e:
        _guard(e)


@router.patch("/{answer_id}")
async def update_answer(answer_id: str, body: dict = Body(...), user_id: str = Depends(get_user_id)):
    """Edit a saved answer's value."""
    if "value" not in body:
        raise HTTPException(status_code=400, detail="value is required")
    try:
        return {"success": True, "answer": _service.update_answer(user_id, answer_id, body["value"])}
    except Exception as e:
        _guard(e)


@router.delete("/{answer_id}")
async def delete_answer(answer_id: str, user_id: str = Depends(get_user_id)):
    """Soft-delete a saved answer (stops auto-fill; keeps the question known)."""
    try:
        _service.delete_answer(user_id, answer_id)
        return {"success": True}
    except Exception as e:
        _guard(e)


@router.get("/pending")
async def list_pending(user_id: str = Depends(get_user_id)):
    """Questions currently blocking one or more applications."""
    try:
        return {"pending": _service.list_pending(user_id)}
    except Exception as e:
        _guard(e)


@router.post("/pending/{pending_id}")
async def answer_pending(pending_id: str, body: dict = Body(...), user_id: str = Depends(get_user_id)):
    """Answer a pending question → persist it and re-queue unblocked applications."""
    if "value" not in body or body["value"] in (None, ""):
        raise HTTPException(status_code=400, detail="value is required")
    try:
        return _service.answer_pending(user_id, pending_id, body["value"])
    except Exception as e:
        _guard(e)


@router.post("/pending/{pending_id}/skip")
async def skip_pending(pending_id: str, user_id: str = Depends(get_user_id)):
    """Skip a pending question — its application stays paused/assisted-only."""
    try:
        return _service.skip_pending(user_id, pending_id)
    except Exception as e:
        _guard(e)
