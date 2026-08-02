"""
AI Service package — re-exports all public functions for backward compatibility.

Import from here (e.g. `from services.ai import call_llm`) or from submodules
directly (e.g. `from services.ai.provider import call_llm`).
"""
from services.ai.provider import (  # noqa: F401
    BudgetExceededError,
    call_llm,
    get_usage_stats,
    llm_feature,
    llm_feature_scope,
    parse_json_response,
    parse_json_response as _parse_json_response,
)
from services.ai.job_analysis import (  # noqa: F401
    parse_job_description,
    compute_match_score,
    batch_parse_jds,
    batch_score_jobs,
    failed_result,
)
from services.ai.content_gen import (  # noqa: F401
    generate_cover_letter,
    answer_screening_question,
    draft_answer_for_user,
    rephrase_answer,
    tailor_resume_content,
    NEEDS_INFO_TOKEN,
)
from services.ai.interview import (  # noqa: F401
    generate_interview_prep,
    analyze_skill_gaps,
    generate_follow_up_email,
)
