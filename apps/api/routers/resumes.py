"""Resume management router."""
from auth import get_user_id
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from loguru import logger
import os
import tempfile
from database import get_db
from config import settings
from services.resume_storage import create_signed_resume_url, new_resume_storage_path

router = APIRouter(prefix="/resumes", tags=["resumes"])

db = get_db()

_MAX_RESUME_BYTES = 10 * 1024 * 1024
_ALLOWED_RESUME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _with_signed_url(resume: dict) -> dict:
    safe_resume = dict(resume)
    safe_resume["file_url"] = create_signed_resume_url(safe_resume.get("file_url")) or ""
    return safe_resume


@router.get("/")
async def list_resumes(user_id: str = Depends(get_user_id)):
    result = db.table("resumes").select("*").eq("user_id", user_id).eq("is_active", True).order("created_at", desc=True).execute()
    return [_with_signed_url(resume) for resume in (result.data or [])]


@router.post("/upload")
async def upload_resume(
    file: UploadFile = File(...),
    name: str = Form(...),
    is_primary: bool = Form(False),
    user_id: str = Depends(get_user_id),
):
    """Upload a resume file, parse it with AI, and store in Supabase Storage."""
    filename = file.filename or ""
    suffix = os.path.splitext(filename)[1].lower()
    content_type = _ALLOWED_RESUME_TYPES.get(suffix)
    if not content_type:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX documents are supported")
    if file.size and file.size > _MAX_RESUME_BYTES:
        raise HTTPException(status_code=400, detail="File size must be under 10MB")
    if not name.strip() or len(name) > 200:
        raise HTTPException(status_code=400, detail="Resume name must be between 1 and 200 characters")

    try:
        content = await file.read()
        if len(content) > _MAX_RESUME_BYTES:
            raise HTTPException(status_code=400, detail="File size must be under 10MB")
        storage_path = new_resume_storage_path(user_id, filename)

        # The resumes bucket must be private. Store only the object key; URLs are
        # signed when returned to the authenticated owner.
        db.storage.from_(settings.STORAGE_BUCKET_RESUMES).upload(
            path=storage_path, file=content,
            file_options={"content-type": content_type, "upsert": "false"},
        )

        # Parse resume text
        parsed_data = {}
        parsed_text = ""
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            parsed_text = _extract_text(tmp_path, content_type)
            if parsed_text:
                from services.ai import call_llm, _parse_json_response
                parse_prompt = f"""Parse this resume and return structured JSON with keys:
full_name, email, phone, location, summary, skills (array), tech_stack (object with years),
experience (array of objects), education (array), projects (array), certifications (array),
total_experience_years (number).
Resume:\n{parsed_text[:6000]}"""
                raw = call_llm("You are a resume parser. Return JSON only.", parse_prompt, max_tokens=2000)
                parsed_data = _parse_json_response(raw)
        except Exception as e:
            logger.warning(f"Resume parse failed: {e}")
        finally:
            os.unlink(tmp_path)

        # Insert record
        record = {
            "user_id": user_id, "name": name.strip(), "file_url": storage_path,
            "file_size": len(content), "file_type": content_type,
            "is_primary": is_primary, "parsed_data": parsed_data,
            "word_count": len(parsed_text.split()) if parsed_data else 0,
        }
        result = db.table("resumes").insert(record).execute()

        # Sync skills to user profile
        if parsed_data.get("skills"):
            db.table("users").update({
                "skills": parsed_data["skills"][:50],
                "tech_stack": parsed_data.get("tech_stack", {}),
            }).eq("id", user_id).execute()

        return _with_signed_url(result.data[0] if result.data else record)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Resume upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _extract_text(path: str, content_type: str) -> str:
    try:
        if "pdf" in (content_type or ""):
            import PyPDF2
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                return " ".join(page.extract_text() or "" for page in reader.pages)
        else:
            from docx import Document
            doc = Document(path)
            return " ".join(p.text for p in doc.paragraphs)
    except Exception as e:
        logger.warning(f"Text extraction failed: {e}")
        return ""


@router.post("/{resume_id}/set-primary")
async def set_primary(resume_id: str, user_id: str = Depends(get_user_id)):
    db.table("resumes").update({"is_primary": False}).eq("user_id", user_id).execute()
    db.table("resumes").update({"is_primary": True}).eq("id", resume_id).eq("user_id", user_id).execute()
    return {"success": True}


@router.delete("/{resume_id}")
async def delete_resume(resume_id: str, user_id: str = Depends(get_user_id)):
    db.table("resumes").update({"is_active": False}).eq("id", resume_id).eq("user_id", user_id).execute()
    return {"success": True}


@router.post("/{resume_id}/tailor")
async def tailor_resume(resume_id: str, job_listing_id: str, user_id: str = Depends(get_user_id)):
    """Generate a tailored version of a resume for a specific job."""
    resume_res = db.table("resumes").select("*").eq("id", resume_id).eq("user_id", user_id).single().execute()
    job_res = db.table("job_listings").select("*").eq("id", job_listing_id).single().execute()
    if not resume_res.data or not job_res.data:
        raise HTTPException(status_code=404)

    from services.ai import parse_job_description, tailor_resume_content
    jd_parsed = parse_job_description(job_res.data["jd_text"])
    tailoring = tailor_resume_content(resume_res.data.get("parsed_data", {}), jd_parsed)
    return {"tailoring": tailoring, "resume_id": resume_id, "job_listing_id": job_listing_id}
