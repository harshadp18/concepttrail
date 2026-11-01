"""The synthetic provider smoke-test spec (design only) and the Groq rights boundary (D-055)."""

from __future__ import annotations

import json
import re
from fractions import Fraction
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from data_pipeline import authorization as auth

SPEC = Path(__file__).resolve().parents[2] / "evaluation/provider_smoke_cases.json"


class Answer(BaseModel):
    """Pydantic mirror of the spec's `answer_schema`."""

    model_config = ConfigDict(extra="forbid")
    language: Literal["en", "hi"]
    final_answer: str = Field(min_length=1)
    steps: list[str] = Field(min_length=1)


@pytest.fixture(scope="module")
def spec() -> dict:
    return json.loads(SPEC.read_text(encoding="utf-8"))


def cases(spec: dict) -> dict[str, dict]:
    return {c["case_id"]: c for c in spec["cases"]}


def test_spec_is_design_only_synthetic_and_makes_no_calls(spec: dict) -> None:
    assert spec["status"] == "design_only_not_run"
    assert spec["data_policy"] == {
        "textbook_content": False,
        "student_personal_data": False,
        "external_calls_made_by_this_file": 0,
    }
    assert "No LLM scores" in spec["scoring_policy"]
    roles = {p["provider"]: p["role"] for p in spec["providers"]}
    assert roles == {"ollama": "primary", "groq": "fallback_candidate_manual_only"}
    ids = [c["case_id"] for c in spec["cases"]]
    assert len(ids) == len(set(ids)) == 5
    text = SPEC.read_text(encoding="utf-8")
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+|\b\d{10}\b|roll|password|token=", text, re.I)
    assert "deepseek" not in text.lower() and "gemini" not in text.lower()


def test_expected_arithmetic_facts_in_the_spec_are_correct(spec: dict) -> None:
    arithmetic = cases(spec)["SMOKE-ARITH-01"]
    assert arithmetic["deterministic_checks"] == [
        {"type": "integer_answer_equals", "value": 27 * 14}
    ]
    total = Fraction(3, 4) + Fraction(2, 3)
    assert total == Fraction(17, 12)
    assert (total.numerator // total.denominator, total - 1) == (1, Fraction(5, 12))
    values = [
        v for c in cases(spec)["SMOKE-FRAC-01"]["deterministic_checks"] for v in c.get("values", [])
    ]
    assert "17/12" in values and any("5/12" in v for v in values)


def test_class_levels_and_human_review_flags(spec: dict) -> None:
    by = cases(spec)
    assert by["SMOKE-FRAC-01"]["class_level"] == 7
    assert by["SMOKE-SCI-01"]["class_level"] == by["SMOKE-HI-01"]["class_level"] == 8
    assert by["SMOKE-ARITH-01"]["human_review"] is False
    assert all(by[c]["human_review"] for c in ("SMOKE-FRAC-01", "SMOKE-SCI-01", "SMOKE-HI-01"))
    hindi = by["SMOKE-HI-01"]["prompt"]
    assert sum("ऀ" <= ch <= "ॿ" for ch in hindi) > 20  # real Devanagari, preserved


def test_structured_output_cases_behave_as_specified(spec: dict) -> None:
    for payload in cases(spec)["SMOKE-SCHEMA-01"]["payloads"]:
        if "raw" in payload:
            with pytest.raises(json.JSONDecodeError):
                json.loads(payload["raw"])
            continue
        if payload["expect_valid"]:
            Answer.model_validate(payload["payload"])
        else:
            with pytest.raises(ValidationError):
                Answer.model_validate(payload["payload"])
    schema = spec["answer_schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(Answer.model_fields)


def test_groq_content_processing_is_not_authorised_by_any_existing_record() -> None:
    doc = {"source_id": "SRC-C06-MAT-FEGP1-01", "sha256": "a" * 64}
    records = [
        auth.owner_local_processing_record([doc]),
        auth.owner_project_use_record([doc]),
    ]
    for use in (
        "external_groq_processing",
        "external_gemini_processing",
        "deepseek_processing",
        "cloud_ai_processing",
        "external_embedding",
        "model_training_or_fine_tuning",
        "redistribution",
    ):
        assert not auth.check_use(doc["source_id"], doc["sha256"], use, records).permitted, use
    assert not any(
        "groq" in json.dumps(r).lower()
        for r in records
        if "uses" in r and any("groq" in u for u in r["uses"])
    )
