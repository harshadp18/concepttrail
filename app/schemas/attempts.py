"""Assessment request and response contracts."""

from __future__ import annotations

import math
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AttemptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1, max_length=200)
    question_version: int = Field(ge=1)
    submitted_answer: dict[str, Any]
    hint_tier: int = Field(default=0, ge=0, le=3)
    idempotency_key: str = Field(min_length=16, max_length=128)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_idempotency_key(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 16:
            raise ValueError("idempotency_key must contain at least 16 non-whitespace characters")
        return value

    @field_validator("submitted_answer")
    @classmethod
    def answer_shape(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Structural check only; the question type decides which shape is valid.

        `{option_key}` (single choice, true/false), `{option_keys}` (multiple select) or
        `{value}` (true/false boolean, numeric). Correctness, KC IDs and scores are never
        accepted from the client.
        """
        keys = set(value)
        if keys == {"option_key"}:
            key = value["option_key"]
            if not isinstance(key, str) or not key.strip() or len(key.strip()) > 80:
                raise ValueError("option_key must be a non-empty string")
            return {"option_key": key.strip()}
        if keys == {"option_keys"}:
            items = value["option_keys"]
            if (
                not isinstance(items, list)
                or not 1 <= len(items) <= 10
                or not all(isinstance(k, str) and k.strip() and len(k) <= 80 for k in items)
            ):
                raise ValueError("option_keys must be a list of 1-10 non-empty strings")
            cleaned = [k.strip() for k in items]
            if len(set(cleaned)) != len(cleaned):
                raise ValueError("option_keys must not repeat")
            return {"option_keys": cleaned}
        if keys == {"value"}:
            raw = value["value"]
            if isinstance(raw, (bool, int)) or (isinstance(raw, float) and math.isfinite(raw)):
                return {"value": raw}
            if isinstance(raw, str) and raw.strip() and len(raw) <= 40:
                return {"value": raw.strip()}
            raise ValueError("value must be a boolean, a number or a short numeric string")
        raise ValueError(
            "submitted_answer must be exactly one of {option_key}, {option_keys} or {value}"
        )


class BKTUpdateResult(BaseModel):
    updated: bool
    reason: str | None = None
    kc_id: str | None = None
    mastery_probability: float | None = None
    config_version: str | None = None


class AttemptResponse(BaseModel):
    attempt_id: UUID
    question_id: str
    question_version: int
    scored_correct: bool
    score: float
    score_method: str
    bkt: BKTUpdateResult
    duplicate_replay: bool = False
