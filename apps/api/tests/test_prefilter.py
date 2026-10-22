"""Tests for the rule-based relevance prefilter (pre-LLM cost gate)."""
from types import SimpleNamespace

from services.prefilter import build_user_keywords, is_relevant, rejected_indices

USER = {
    "skills": ["Node.js", "TypeScript", "Express.js", "NestJS", "PostgreSQL"],
    "headline": "Senior Backend Engineer",
    "career_goals": "Staff backend engineer at a product company",
}


def _job(title, jd="", skills=None):
    return SimpleNamespace(title=title, jd_text=jd, required_skills=skills or [])


def test_keeps_matching_skill():
    kw = build_user_keywords(USER)
    assert is_relevant(_job("Node.js Developer", "Build APIs with Express and Postgres"), kw)


def test_keeps_generic_tech_title_without_skill_match():
    # Title has a tech-role word even though the JD doesn't name the user's stack.
    kw = build_user_keywords(USER)
    assert is_relevant(_job("Software Engineer", "Join our growing team to build great things"), kw)


def test_drops_clearly_offprofile_role():
    kw = build_user_keywords(USER)
    assert not is_relevant(
        _job("Corporate Sales Manager", "Drive revenue through enterprise sales and account management targets"),
        kw,
    )
    assert not is_relevant(
        _job("Registered Nurse", "Provide patient care in the ICU ward with compassion and clinical excellence"),
        kw,
    )


def test_keeps_when_jd_too_short_to_judge():
    kw = build_user_keywords(USER)
    assert is_relevant(_job("Analyst", "TBD"), kw)  # not enough text to reject


def test_keeps_skill_in_required_skills_field():
    kw = build_user_keywords(USER)
    # Title/JD are generic but the structured skills carry the match.
    job = _job("Member of Technical Staff", "We are hiring across the board for our expanding org", ["NestJS", "Redis"])
    assert is_relevant(job, kw)


def test_dotted_skill_phrase_match():
    kw = build_user_keywords(USER)
    # "node.js" must match as a phrase, not require a bare "node" token.
    assert is_relevant(_job("Platform team hire", "Our stack is node.js and kubernetes on the backend platform"), kw)


def test_empty_profile_keeps_everything():
    kw = build_user_keywords({"skills": [], "headline": "", "career_goals": ""})
    assert kw == set()
    jobs = [_job("Sales Manager", "sell things to enterprise clients across the region and beyond")]
    assert rejected_indices(jobs, {"skills": [], "headline": ""}) == set()


def test_rejected_indices_flags_offprofile_positions():
    jobs = [
        _job("Backend Engineer", "Node.js microservices at scale for our platform team"),
        _job("Regional Sales Head", "Own the P&L and lead the field sales team to hit quarterly quota targets"),
        _job("Full Stack Developer", "React and Express across the whole product surface area"),
        _job("Chartered Accountant", "Manage statutory audit, taxation and financial compliance filings end to end"),
    ]
    rejected = rejected_indices(jobs, USER)
    assert rejected == {1, 3}
    kept_titles = [j.title for i, j in enumerate(jobs) if i not in rejected]
    assert kept_titles == ["Backend Engineer", "Full Stack Developer"]


def test_build_user_keywords_is_skills_only():
    kw = build_user_keywords({"skills": ["Machine Learning", "Node.js"], "headline": "AI Engineer"})
    assert "machine learning" in kw   # multiword skill kept as phrase
    assert "node.js" in kw
    # Generic headline prose is deliberately NOT a haystack keyword (it would
    # match sales roles at tech companies). Role coverage is title-only.
    assert "engineer" not in kw
    assert "ai" not in kw


# ── MENA: French/Arabic vocabulary and nationals-only (PHASE_0 §0.5) ──

def test_french_developer_title_passes_without_skill_match():
    kw = build_user_keywords({"skills": ["react"]})
    job = _job("Développeur Full Stack", "Rejoignez notre équipe pour construire des produits de qualité")
    assert is_relevant(job, kw)


def test_arabic_developer_title_passes():
    kw = build_user_keywords({"skills": ["react"]})
    assert is_relevant(_job("مطور برمجيات", "نبحث عن مطور للانضمام إلى فريقنا في الرياض لبناء منتجات"), kw)


def test_french_civil_engineer_is_rejected():
    kw = build_user_keywords({"skills": ["react"]})
    job = _job("Ingénieur génie civil", "Supervision de chantier, béton armé et suivi des travaux de construction")
    assert not is_relevant(job, kw)


def test_nationals_only_rejected_even_when_skills_match(monkeypatch):
    from config import settings
    user = {"skills": ["react"]}
    jobs = [_job("Software Engineer (UAE National)", "React and TypeScript product work in Dubai office")]
    monkeypatch.setattr(settings, "MENA_EXCLUDE_NATIONALS_ONLY", True)
    assert rejected_indices(jobs, user) == {0}

    monkeypatch.setattr(settings, "MENA_EXCLUDE_NATIONALS_ONLY", False)
    assert rejected_indices(jobs, user) == set()


def test_nationals_only_rejected_for_user_without_keywords(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "MENA_EXCLUDE_NATIONALS_ONLY", True)
    jobs = [
        _job("Associate Director - Emiratized Role", "Lead the education sector team"),
        _job("Backend Engineer", "Node.js microservices at scale"),
    ]
    assert rejected_indices(jobs, {"skills": []}) == {0}
