"""Contracts for chapter topics, recommendations and grounded doubt answers."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TopicSummary(BaseModel):
    kc_id: str
    name: str | None
    description: str | None
    kc_type: str | None
    difficulty_tier: int | None
    question_count: int
    mastery_probability: float | None = None
    evidence_count: int = 0


class ChapterTopics(BaseModel):
    item_id: str
    title: str | None
    subject_id: str | None
    grade_level: int | None
    content_release: Literal["production", "demo"]
    topics: list[TopicSummary]


class Recommendation(BaseModel):
    status: Literal["ok", "insufficient_data"]
    reason: str | None = None
    detail: list[str] = Field(default_factory=list)
    kc_id: str | None = None
    question_id: str | None = None
    category: str | None = None
    rationale: list[str] = Field(default_factory=list)
    mastery_probability: float | None = None
    policy_version: str
    graph_version: str | None = None
    thresholds: dict[str, float | bool] | None = None
    content_release: Literal["production", "demo"]


class DoubtRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=5, max_length=1000)
    mode: Literal["explanation", "hint"] = "explanation"
    subject_id: str | None = Field(default=None, min_length=1, max_length=100)
    kc_id: str | None = Field(default=None, min_length=1, max_length=200)
    # Follow-up in an existing stored conversation. Needs DOUBT_HISTORY_ENABLED (503 otherwise).
    conversation_id: uuid.UUID | None = None

    @field_validator("question")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 5:
            raise ValueError("question is too short")
        return value


class Citation(BaseModel):
    label: str
    source_id: str
    pdf_page_index: int | None
    printed_page_label: str | None
    item_title: str | None


class DoubtResponse(BaseModel):
    status: Literal[
        "ok",
        "insufficient_evidence",
        "not_authorized",
        "model_unavailable",
        "model_timeout",
        "invalid_model_output",
    ]
    grounding: Literal["grounded", "abstained"]
    message: str
    concept: str = ""
    explanation: str = ""
    steps: list[str] = Field(default_factory=list)
    hint: str = ""
    citations: list[Citation] = Field(default_factory=list)
    model_id: str | None = None
    prompt_version: str
    content_release: Literal["production", "demo"]
    # Set only when conversation history is enabled; null means the request was stateless.
    conversation_id: str | None = None
