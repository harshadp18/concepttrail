"""Question bank: drafts, deterministic validation, human review and safe persistence.

Workflow (`questions.review_status`): `draft` → `validated_draft` → `in_review` → `approved`
(or `rejected`). A question is **student-eligible** only when it is `approved`, `active`, and
has an approved `question_kcs` mapping to an approved KC (the delivery API's own filter).

- Validation is deterministic: structure, answer-key consistency, numeric tolerance, SymPy
  checks of a maths expression, difficulty, curriculum and KC alignment, provenance, and
  near-duplicate detection. A quality score is advisory and never approves anything.
- Approval needs an attributable human: an active user with the `teacher` role, not the
  author, recorded in `questions.verification.reviews` (the schema has no reviewer column).
  A model has no user identity, so it can never approve, and generated drafts stay drafts.
- Persistence is idempotent: the question ID is derived from the content; re-importing the
  same content changes nothing; different content under an existing approved ID is refused.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.content_release import servable_review_statuses
from app.core.roles import RoleCode
from app.db.models import (
    CurriculumItem,
    CurriculumVersion,
    KnowledgeComponent,
    Question,
    QuestionKc,
    QuestionOption,
    SourceDocument,
    User,
    UserRole,
)
from app.services.evaluation import MULTIPLE, SINGLE

SUBJECTS = ("english", "hindi", "mathematics", "science", "social_science")
ITEM_TYPES = (
    "single_choice",
    "multiple_select",
    "true_false",
    "numeric",
    "short_answer",
    "structured_response",
)
STATUSES = ("draft", "validated_draft", "in_review", "approved", "rejected")
SYNTHETIC_MARK = "SYNTHETIC-DEV-ONLY"
NAMESPACE = uuid.UUID("a3f1c2d4-5e6f-4a7b-8c9d-0e1f2a3b4c5d")
VALIDATOR_VERSION = "question-validator-v1"
_PLACEHOLDER = re.compile(r"\b(?:TODO|TBD|FIXME|lorem ipsum)\b|\?\?\?", re.IGNORECASE)
_ALL_NONE = re.compile(r"\b(?:all|none) of the above\b", re.IGNORECASE)


class OptionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option_key: str = Field(min_length=1, max_length=8)
    option_text: str = Field(min_length=1, max_length=500)
    is_correct: bool
    explanation: str | None = Field(default=None, max_length=1000)


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    sha256: str = Field(min_length=12, max_length=64)
    pdf_page_index: int | None = Field(default=None, ge=0)


class QuestionDraft(BaseModel):
    """A question as authored or generated, before persistence."""

    model_config = ConfigDict(extra="forbid")
    item_type: Literal[
        "single_choice",
        "multiple_select",
        "true_false",
        "numeric",
        "short_answer",
        "structured_response",
    ]
    stem: str = Field(min_length=1, max_length=2000)
    options: list[OptionDraft] = Field(default_factory=list)
    expected_answer: dict[str, Any] | None = None
    rubric: dict[str, Any] | None = None
    difficulty: int = Field(ge=1, le=5)
    language: Literal["en", "hi"] = "en"
    class_level: int = Field(ge=6, le=10)
    subject_id: str
    kc_ids: list[str] = Field(default_factory=list)
    curriculum_item_id: str | None = None
    source_refs: list[SourceRef] = Field(default_factory=list)
    misconception_map: dict[str, str] | None = None
    explanation: str | None = Field(default=None, max_length=2000)
    origin: Literal["human_authored", "ai_drafted", "synthetic"]
    origin_ref: str | None = None
    author_user_id: uuid.UUID | None = None


@dataclass
class Validation:
    errors: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)
    quality_score: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "validator": VALIDATOR_VERSION,
            "ok": self.ok,
            "errors": [list(e) for e in self.errors],
            "warnings": [list(w) for w in self.warnings],
            "quality_score": self.quality_score,
            "note": "a quality score is advisory and never an approval",
        }


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def content_hash(draft: QuestionDraft) -> str:
    """Identity of the assessable content (stem, type, options, key), not of metadata."""
    payload = {
        "item_type": draft.item_type,
        "stem": _norm(draft.stem),
        "options": sorted(
            (o.option_key, _norm(o.option_text), o.is_correct) for o in draft.options
        ),
        "expected_answer": draft.expected_answer,
        "subject_id": draft.subject_id,
        "class_level": draft.class_level,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def duplicate_key(draft: QuestionDraft) -> str:
    """Near-duplicate key: same normalised stem and option texts, regardless of order."""
    payload = [_norm(draft.stem), sorted(_norm(o.option_text) for o in draft.options)]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


def question_id_for(draft: QuestionDraft) -> str:
    code = {
        "english": "ENG",
        "hindi": "HIN",
        "mathematics": "MAT",
        "science": "SCI",
        "social_science": "SOC",
    }.get(draft.subject_id, "XXX")
    prefix = "QSYN" if draft.origin == "synthetic" else "Q"
    return f"{prefix}-{code}-C{draft.class_level:02d}-{content_hash(draft)[:12]}"


def _sympy_check(expected: dict[str, Any]) -> tuple[str, str] | None:
    """If the key carries an `expression`, it must evaluate to `value` (within tolerance)."""
    if "expression" not in expected:
        return None
    try:
        import sympy

        evaluated = sympy.sympify(str(expected["expression"]), evaluate=True)
        number = Decimal(str(float(sympy.N(evaluated, 30))))
    except (sympy.SympifyError, TypeError, ValueError, ArithmeticError):
        return ("NUMERIC_EXPRESSION_INVALID", "the answer expression does not evaluate")
    tolerance = Decimal(str(expected.get("abs_tolerance", 0))) or Decimal("1e-9")
    if abs(number - Decimal(str(expected["value"]))) > tolerance:
        return ("ANSWER_INCONSISTENT", "the expression does not evaluate to the stated value")
    return None


def validate_structure(draft: QuestionDraft) -> Validation:
    """Checks that need no database."""
    v = Validation()
    err, warn = v.errors.append, v.warnings.append
    if draft.subject_id not in SUBJECTS:
        err(("INVALID_SUBJECT", draft.subject_id))
    if len(draft.stem.strip()) < 10:
        err(("STEM_TOO_SHORT", "the stem needs at least 10 characters"))
    for text in [draft.stem, *(o.option_text for o in draft.options)]:
        if _PLACEHOLDER.search(text):
            err(("PLACEHOLDER_TEXT", "placeholder text in stem or options"))
            break
    keys = [o.option_key for o in draft.options]
    texts = [_norm(o.option_text) for o in draft.options]
    correct = [o for o in draft.options if o.is_correct]
    kind = draft.item_type
    if kind in SINGLE or kind in MULTIPLE:
        if len(draft.options) < 3:
            err(("TOO_FEW_OPTIONS", "at least three options are required"))
        if len(set(keys)) != len(keys):
            err(("DUPLICATE_OPTION_KEY", "option keys repeat"))
        if len(set(texts)) != len(texts):
            err(("DUPLICATE_OPTION_TEXT", "two options have the same text"))
        if kind in SINGLE and len(correct) != 1:
            err(("ANSWER_KEY_INVALID", "a single-choice question needs exactly one correct option"))
        if kind in MULTIPLE and (not correct or len(correct) == len(draft.options)):
            err(("ANSWER_KEY_INVALID", "multiple-select needs correct and incorrect options"))
        if draft.expected_answer:
            err(("ANSWER_KEY_AMBIGUOUS", "choice questions are keyed by options only"))
        if any(_ALL_NONE.search(o.option_text) for o in draft.options):
            warn(("ALL_NONE_OF_THE_ABOVE", "avoid 'all/none of the above'"))
        if correct and any(
            _norm(c.option_text) in _norm(draft.stem) and len(_norm(c.option_text)) > 3
            for c in correct
        ):
            warn(("ANSWER_IN_STEM", "the correct option text appears in the stem"))
    elif kind == "true_false":
        value = (draft.expected_answer or {}).get("value")
        if not isinstance(value, bool):
            err(("ANSWER_KEY_INVALID", 'true/false needs expected_answer {"value": bool}'))
        elif draft.options:
            # Optional two-option form ("True"/"False") so an option-key scorer can serve it;
            # the correct option must agree with expected_answer.
            labels = sorted(o.option_text.strip().casefold() for o in draft.options)
            right = [o.option_text.strip().casefold() for o in draft.options if o.is_correct]
            if labels != ["false", "true"] or right != [str(value).casefold()]:
                err(("ANSWER_KEY_INVALID", "true/false options must be True/False and match"))
    elif kind == "numeric":
        expected = draft.expected_answer or {}
        try:
            Decimal(str(expected["value"]))
            for t in ("abs_tolerance", "rel_tolerance"):
                if Decimal(str(expected.get(t, 0))) < 0:
                    raise ValueError
        except (KeyError, ValueError, ArithmeticError):
            err(("ANSWER_KEY_INVALID", "numeric needs a value and non-negative tolerances"))
        else:
            if "abs_tolerance" not in expected and "rel_tolerance" not in expected:
                err(("TOLERANCE_MISSING", "numeric answers need an explicit tolerance"))
            if problem := _sympy_check(expected):
                err(problem)
        if draft.options:
            err(("ANSWER_KEY_AMBIGUOUS", "numeric questions have no options"))
    else:  # short_answer, structured_response: rubric review only
        criteria = (draft.rubric or {}).get("criteria")
        if not isinstance(criteria, list) or not criteria:
            err(("RUBRIC_REQUIRED", "a rubric with criteria is required; scoring is human"))
    if draft.origin == "ai_drafted" and not draft.origin_ref:
        err(("PROVENANCE_MISSING", "a model draft needs its generation record reference"))
    if draft.origin == "synthetic" and draft.source_refs:
        err(("SYNTHETIC_WITH_SOURCE", "synthetic questions may not cite real sources"))
    if draft.origin != "synthetic" and not draft.source_refs and draft.origin != "human_authored":
        err(("PROVENANCE_MISSING", "generated questions must cite their evidence"))
    soft = [
        bool(draft.explanation),
        all(o.explanation for o in draft.options) or not draft.options,
        bool(draft.misconception_map) or kind not in SINGLE,
        len(draft.stem) <= 400,
    ]
    v.quality_score = round(sum(soft) / len(soft), 3)
    return v


def validate_question(
    session: Session, draft: QuestionDraft, *, ignore_question_id: str | None = None
) -> Validation:
    """Structural checks plus curriculum, KC, source and duplicate checks against the DB."""
    v = validate_structure(draft)
    err = v.errors.append
    for kc_id in draft.kc_ids:
        kc = session.get(KnowledgeComponent, kc_id)
        if kc is None:
            err(("KC_UNKNOWN", kc_id))
        elif kc.subject_id != draft.subject_id:
            err(("KC_SUBJECT_MISMATCH", kc_id))
    if draft.curriculum_item_id is not None:
        item = session.get(CurriculumItem, draft.curriculum_item_id)
        version = (
            session.get(CurriculumVersion, item.curriculum_version_id)
            if item and item.curriculum_version_id
            else None
        )
        if item is None:
            err(("CURRICULUM_ITEM_UNKNOWN", draft.curriculum_item_id))
        elif item.subject_id != draft.subject_id:
            err(("CURRICULUM_SUBJECT_MISMATCH", draft.curriculum_item_id))
        elif version is not None and version.class_level != draft.class_level:
            err(("CURRICULUM_CLASS_MISMATCH", draft.curriculum_item_id))
    for ref in draft.source_refs:
        source = session.get(SourceDocument, ref.source_id)
        if source is None or not (source.sha256 or "").startswith(ref.sha256):
            err(("SOURCE_REF_UNVERIFIED", ref.source_id))
        elif source.subject_id != draft.subject_id:
            err(("SOURCE_SUBJECT_MISMATCH", ref.source_id))
    key = duplicate_key(draft)
    for row in session.scalars(select(Question).where(Question.verification.is_not(None))):
        if (
            row.question_id != ignore_question_id
            and (row.verification or {}).get("duplicate_key") == key
        ):
            err(("DUPLICATE_QUESTION", row.question_id))
    return v


def create_question_draft(session: Session, draft: QuestionDraft) -> tuple[str, str]:
    """Persist a draft (never approved, never active). Returns (question_id, outcome).

    Outcome is `created`, `unchanged` (same content already stored) or raises ValueError.
    Does not commit.
    """
    question_id = question_id_for(draft)
    existing = session.get(Question, question_id)
    digest = content_hash(draft)
    if existing is not None:
        if (existing.verification or {}).get("content_sha256") == digest:
            return question_id, "unchanged"
        raise ValueError("a different question already uses this ID; refusing to overwrite")
    v = validate_question(session, draft, ignore_question_id=question_id)
    status = "validated_draft" if v.ok else "draft"
    now = datetime.now(UTC).isoformat()
    session.add(
        Question(
            question_id=question_id,
            item_type=draft.item_type,
            stem=draft.stem,
            expected_answer=draft.expected_answer,
            rubric=draft.rubric,
            difficulty=draft.difficulty,
            misconception_map=draft.misconception_map,
            source_refs=[r.model_dump() for r in draft.source_refs] or None,
            verification={
                "workflow": status,
                "content_sha256": digest,
                "duplicate_key": duplicate_key(draft),
                "validation": v.as_dict(),
                "reviews": [],
                "synthetic": draft.origin == "synthetic",
                "marker": SYNTHETIC_MARK if draft.origin == "synthetic" else None,
                "provenance": {
                    "origin": draft.origin,
                    "origin_ref": draft.origin_ref,
                    "author_user_id": str(draft.author_user_id) if draft.author_user_id else None,
                    "language": draft.language,
                    "class_level": draft.class_level,
                    "subject_id": draft.subject_id,
                    "curriculum_item_id": draft.curriculum_item_id,
                    "explanation": draft.explanation,
                    "created_at": now,
                },
            },
            review_status=status,
            version=1,
            active=False,
        )
    )
    session.flush()
    for order, option in enumerate(draft.options, start=1):
        session.add(
            QuestionOption(
                option_id=uuid.uuid5(NAMESPACE, f"{question_id}:1:{option.option_key}"),
                question_id=question_id,
                option_key=option.option_key,
                option_text=option.option_text,
                is_correct=option.is_correct,
                explanation=option.explanation,
                display_order=order,
            )
        )
    for kc_id in draft.kc_ids:
        if session.get(KnowledgeComponent, kc_id) is not None:
            session.add(
                QuestionKc(
                    question_id=question_id,
                    kc_id=kc_id,
                    weight=Decimal("1"),
                    mapping_role="primary",
                    review_status="needs_review",
                )
            )
    session.flush()
    return question_id, "created"


class ReviewRefused(ValueError):
    pass


def _is_teacher(session: Session, user_id: uuid.UUID) -> bool:
    user = session.get(User, user_id)
    if user is None or user.is_active is not True:
        return False
    return session.get(UserRole, (user_id, RoleCode.TEACHER.value)) is not None


def record_question_review(
    session: Session,
    question_id: str,
    reviewer_user_id: uuid.UUID,
    decision: Literal["approved", "rejected", "revision_required"],
    rationale: str,
) -> str:
    """Record one attributable human review. Returns the new review status. Does not commit."""
    question = session.get(Question, question_id)
    if question is None:
        raise ReviewRefused("unknown question")
    verification = dict(question.verification or {})
    provenance = verification.get("provenance") or {}
    if not _is_teacher(session, reviewer_user_id):
        raise ReviewRefused("the reviewer must be an active user with the teacher role")
    if provenance.get("author_user_id") == str(reviewer_user_id):
        raise ReviewRefused("an author cannot review their own question")
    if not rationale.strip():
        raise ReviewRefused("a written rationale is required")
    if question.review_status in ("approved", "rejected"):
        raise ReviewRefused(f"the question is already {question.review_status}")
    if decision == "approved":
        if question.review_status not in ("validated_draft", "in_review"):
            raise ReviewRefused("only a validated draft can be approved")
        if not (verification.get("validation") or {}).get("ok"):
            raise ReviewRefused("validation has errors")
    new_status = {"approved": "approved", "rejected": "rejected", "revision_required": "draft"}[
        decision
    ]
    verification["reviews"] = [
        *verification.get("reviews", []),
        {
            "reviewer_user_id": str(reviewer_user_id),
            "decision": decision,
            "rationale": rationale.strip(),
            "content_sha256": verification.get("content_sha256"),
            "decided_at": datetime.now(UTC).isoformat(),
            "basis": "individual_review",
        },
    ]
    verification["workflow"] = new_status
    question.verification = verification
    question.review_status = new_status
    if decision == "approved":
        question.active = True
        for mapping in session.scalars(
            select(QuestionKc).where(QuestionKc.question_id == question_id)
        ):
            kc = session.get(KnowledgeComponent, mapping.kc_id)
            mapping.review_status = (
                "approved" if kc and kc.review_status == "approved" else "needs_review"
            )
    session.flush()
    return new_status


def import_approved_question(
    session: Session, draft: QuestionDraft, review: dict[str, Any]
) -> tuple[str, str]:
    """Import a question together with its attributable human review, idempotently.

    `review` = {"reviewer_user_id", "decision": "approved", "rationale"}. Re-importing the same
    content is a no-op; changed content under an approved ID is refused.
    """
    question_id, outcome = create_question_draft(session, draft)
    question = session.get(Question, question_id)
    assert question is not None
    if outcome == "unchanged" and question.review_status == "approved":
        return question_id, "unchanged"
    if question.review_status != "validated_draft":
        raise ReviewRefused("the question did not pass validation; not approved")
    record_question_review(
        session,
        question_id,
        uuid.UUID(str(review["reviewer_user_id"])),
        review["decision"],
        review["rationale"],
    )
    return question_id, "approved" if review["decision"] == "approved" else review["decision"]


def get_approved_questions(session: Session, kc_id: str, limit: int = 50) -> list[Question]:
    """Student-eligible questions for a KC (same filter as the delivery API, which also requires
    that the server can score the question deterministically)."""
    from app.services.attempt_service import is_deliverable

    kc = session.get(KnowledgeComponent, kc_id)
    if kc is None or kc.review_status not in servable_review_statuses():
        return []
    questions = session.scalars(
        select(Question)
        .join(QuestionKc, QuestionKc.question_id == Question.question_id)
        .where(
            QuestionKc.kc_id == kc_id,
            QuestionKc.review_status.in_(servable_review_statuses()),
            Question.review_status.in_(servable_review_statuses()),
            Question.active.is_(True),
        )
        .order_by(Question.difficulty, Question.question_id)
    ).all()
    out = []
    for question in questions:
        options = list(
            session.scalars(
                select(QuestionOption).where(QuestionOption.question_id == question.question_id)
            )
        )
        if is_deliverable(question, options):
            out.append(question)
        if len(out) >= limit:
            break
    return out


def approved_question_counts(session: Session, kc_ids: Iterable[str]) -> dict[str, int]:
    return {k: len(get_approved_questions(session, k)) for k in kc_ids}
