"""Types + normalization shared across the Answer Bank."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum


# The sentinel adapters already recognize (they skip filling a field when the
# answer contains this). Resolver returns it whenever a question can't be answered.
NEEDS_INFO_TOKEN = "[NEEDS_INFO]"


class ResolutionStatus(str, Enum):
    ANSWERED = "answered"     # we have a value to fill
    NEEDS_INPUT = "needs_input"  # unknown — pause and ask the user


# Convenience singleton-ish marker for "no answer".
NEEDS_INPUT = ResolutionStatus.NEEDS_INPUT


# Question types we model. Kept aligned with the DB CHECK-free `question_type` text.
TEXT = "text"
TEXTAREA = "textarea"
NUMERIC = "numeric"
BOOLEAN = "boolean"
SINGLE_SELECT = "single_select"
MULTI_SELECT = "multi_select"
DATE = "date"


@dataclass
class FormQuestion:
    """A question detected on an application form."""
    text: str
    qtype: str = TEXT
    options: list[str] = field(default_factory=list)
    required: bool = True
    selector: str = ""          # DOM selector, when detected from a page
    platform: str = ""

    @property
    def norm(self) -> str:
        return normalize_question(self.text)

    @property
    def hash(self) -> str:
        return hash_question(self.text)


@dataclass
class Resolution:
    """Outcome of resolving a FormQuestion against profile + bank."""
    status: ResolutionStatus
    value: str = ""             # the fill value when ANSWERED
    source: str = ""            # profile | bank | ai_draft
    category: str = "custom"
    profile_field: str | None = None
    question_id: str | None = None  # question_bank row, when persisted

    @property
    def answered(self) -> bool:
        return self.status == ResolutionStatus.ANSWERED


# ── Normalization ────────────────────────────────────────────────────────────

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")
_NUM_RE = re.compile(r"\b\d[\d,.]*\b")


def normalize_question(text: str) -> str:
    """Canonicalize a question for hashing/similarity.

    Lowercase, strip punctuation, collapse whitespace, and blank out standalone
    numbers (so "5+ years" and "3+ years" of the *same* question still collide on
    trigram similarity rather than being treated as different questions).
    """
    if not text:
        return ""
    t = text.lower().strip()
    t = _NUM_RE.sub(" ", t)
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def hash_question(text: str) -> str:
    return hashlib.sha256(normalize_question(text).encode("utf-8")).hexdigest()


# ── Lightweight type inference (used when only the question text is known) ────

_NUMERIC_HINTS = ("how many years", "years of experience", "how many", "number of",
                  "current ctc", "expected ctc", "current salary", "expected salary",
                  "notice period")
_BOOLEAN_HINTS = ("do you ", "are you ", "have you ", "can you ", "will you ",
                  "willing to", "authorized to", "authorised to", "do you have")


def infer_type(text: str) -> str:
    """Best-effort question type from text alone (no DOM available)."""
    t = (text or "").lower()
    if any(h in t for h in _NUMERIC_HINTS):
        return NUMERIC
    # Essay/open-ended cues take precedence over the boolean "do you" prefix
    # (e.g. "Why do you want to work here…" is a textarea, not a yes/no).
    if len(t) > 120 or "why" in t or "describe" in t or "tell us" in t:
        return TEXTAREA
    if any(h in t for h in _BOOLEAN_HINTS):
        return BOOLEAN
    return TEXT
