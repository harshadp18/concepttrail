"""Release gates never pass on demo content or unreviewed AI-drafted questions."""

from __future__ import annotations

import pytest
from live_db_fixtures import World, live_engine, pg_fixture  # noqa: F401  (fixtures)

from app.db.models import Question
from scripts.release_gate import application_gate, database_gates

pytestmark = pytest.mark.live_db


def test_unreviewed_ai_questions_fail_the_content_gate(pg) -> None:
    w = World(pg)
    qid = w.question([w.kc_a])  # approved KC and question
    q = pg.get(Question, qid)
    q.verification = {"provenance": {"origin": "ai_drafted"}, "reviews": []}
    pg.flush()
    gates = database_gates(pg, None)
    assert gates["content"]["pass"] is False
    assert "without a recorded review=1" in gates["content"]["detail"]
    q.verification = {"provenance": {"origin": "ai_drafted"}, "reviews": [{"reviewer": "r"}]}
    pg.flush()
    assert "without a recorded review=0" in database_gates(pg, None)["content"]["detail"]
    assert gates["rag"]["pass"] is False  # no index configured


def test_development_settings_fail_the_application_gate() -> None:
    ok, _settings = application_gate(None)
    assert ok["pass"] is False


def test_ai_review_never_satisfies_the_human_review_requirement(pg) -> None:
    w = World(pg)
    qid = w.question([w.kc_a])
    q = pg.get(Question, qid)
    q.verification = {
        "provenance": {"origin": "ai_drafted"},
        "reviews": [],
        "ai_review": {"type": "ai_reviewed", "verdict": "no_defect_found"},
    }
    pg.flush()
    gates = database_gates(pg, None)
    assert gates["content"]["pass"] is False
    assert "without a recorded review=1" in gates["content"]["detail"]
