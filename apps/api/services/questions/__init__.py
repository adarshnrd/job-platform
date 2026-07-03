"""
Answer Bank — detect application questions, resolve them from the user's profile
and saved answers, pause the application when a question is genuinely unknown, and
persist every user reply for reuse across all portals.

Public entry points:
    from services.questions import build_question_resolver, QuestionService
"""
from services.questions.schema import FormQuestion, Resolution, NEEDS_INPUT
from services.questions.resolver import build_question_resolver, resolve_question
from services.questions.service import QuestionService

__all__ = [
    "FormQuestion",
    "Resolution",
    "NEEDS_INPUT",
    "build_question_resolver",
    "resolve_question",
    "QuestionService",
]
