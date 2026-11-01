import pytest
from pydantic import ValidationError

from app.schemas.attempts import AttemptCreate


def test_attempt_requires_idempotency_and_option_answer():
    payload = AttemptCreate(
        question_id="q-1",
        question_version=1,
        submitted_answer={"option_key": "A"},
        idempotency_key="client-generated-key-0001",
    )
    assert payload.submitted_answer == {"option_key": "A"}
    assert payload.hint_tier == 0


def test_attempt_rejects_client_supplied_correctness():
    with pytest.raises(ValidationError):
        AttemptCreate(
            question_id="q-1",
            question_version=1,
            submitted_answer={"option_key": "A", "is_correct": True},
            idempotency_key="client-generated-key-0001",
        )


def test_attempt_rejects_too_short_idempotency_key():
    with pytest.raises(ValidationError):
        AttemptCreate(
            question_id="q-1",
            question_version=1,
            submitted_answer={"option_key": "A"},
            idempotency_key="short",
        )
