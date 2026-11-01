"""Learning routes over HTTP: chapter topics, recommendation and grounded doubts.

Live PostgreSQL in an always-rolled-back transaction; the local model is a mock transport and
the embedder is a fake, so no model is called. Synthetic evidence rows are created per test.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from live_db_fixtures import MARK, World, live_engine, pg_fixture  # noqa: F401  (fixtures)

from app.api.v1 import doubts
from app.core.config import get_settings
from app.db.models import ContentUnit, EmbeddingChunk, SourceDocument
from app.db.session import get_db
from app.main import create_app
from app.services.llm import LocalLLM
from data_pipeline.authorization import Decision

pytestmark = pytest.mark.live_db
TAGS = {"models": [{"name": "qwen3.5:9b", "digest": "abc123def456789"}]}
MODEL_ID = "fake:embed@1"


def chat(content: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=TAGS)
        assert "SYNTHETIC evidence" in json.loads(request.content)["messages"][1]["content"]
        return httpx.Response(200, json={"message": {"content": json.dumps(content)}})

    return LocalLLM("http://localhost:11434", "qwen3.5:9b", transport=httpx.MockTransport(handler))


class FakeEmbedder:
    def describe(self):
        return SimpleNamespace(model_id=MODEL_ID, dimensions=3)

    def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


def allow_all(source_id, sha256, use, records=None):
    return Decision(use, True, "synthetic test", "SYN")


def deny_all(source_id, sha256, use, records=None):
    return Decision(use, False, "synthetic test", None)


GOOD = {
    "sufficient": True,
    "concept": "Fractions",
    "explanation": "Add the numerators when denominators match (E1).",
    "steps": ["Check denominators", "Add numerators"],
    "hint": "",
    "evidence_labels": [],
}


@pytest.fixture
def ctx(pg, monkeypatch):
    w = World(pg)
    w.config("learn", datetime.now(UTC) - timedelta(days=1))
    settings = get_settings().model_copy(
        update={"rag_index_generation": f"ig-syn-{w.tag}", "doubt_requests_per_hour": 4}
    )
    monkeypatch.setattr(doubts, "get_settings", lambda: settings)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: pg
    app.dependency_overrides[doubts.get_embedder] = FakeEmbedder
    app.dependency_overrides[doubts.get_rights_check] = lambda: allow_all
    app.dependency_overrides[doubts.get_llm] = lambda: chat(GOOD)
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/auth/login",
            json={"login_identifier": w.student_user.login_identifier, "credential": w.pin},
        )
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        yield client, w, pg, app, h


def add_evidence(pg, w: World, grade: int = 7) -> str:
    source_id = f"SRC-SYN-{w.tag}-{grade}"
    pg.add(
        SourceDocument(
            source_id=source_id,
            subject_id="mathematics",
            title=f"{MARK} source",
            sha256=hashlib.sha256(source_id.encode()).hexdigest(),
            rights_status="synthetic",
            permitted_uses=["indexing_retrieval", "student_facing_display"],
            status="synthetic",
        )
    )
    pg.flush()
    unit = f"CU-SYN-{w.tag}-{grade}"
    pg.add(
        ContentUnit(
            content_unit_id=unit,
            source_id=source_id,
            item_id=w.grade_item(grade),
            unit_type="page",
            content_text="SYNTHETIC evidence about fractions",
            pdf_page_index=3,
            printed_page_label="4",
            extraction_status="pymupdf_native_text",
            review_status="approved",
            asset_refs={"classification": "chapter_body"},
        )
    )
    pg.flush()
    pg.add(
        EmbeddingChunk(
            chunk_id=uuid.uuid4(),
            content_unit_id=unit,
            chunk_order=0,
            chunk_text="SYNTHETIC evidence about fractions: add numerators.",
            token_count=8,
            embedding_model_id=MODEL_ID,
            embedding=[1.0, 0.0, 0.0],
            index_generation=f"ig-syn-{w.tag}",
            created_at=datetime.now(UTC),
        )
    )
    pg.flush()
    return source_id


def ask(client, h, **body):
    return client.post(
        "/api/v1/doubts", headers=h, json={"question": "How do I add 1/5 + 2/5?", **body}
    )


def test_chapter_topics_are_scoped_and_carry_own_mastery(ctx) -> None:
    client, w, pg, _app, h = ctx
    q = w.question([w.kc_a])
    client.post(
        "/api/v1/attempts",
        headers=h,
        json={
            "question_id": q,
            "question_version": 1,
            "submitted_answer": {"option_key": "B"},
            "idempotency_key": "synthetic-topics-0001",
        },
    )
    from app.db.models import KnowledgeComponent

    pg.get(KnowledgeComponent, w.kc_a).difficulty_tier = 2  # stored as smallint
    pg.flush()
    body = client.get(f"/api/v1/curriculum/items/{w.grade_item(7)}/topics", headers=h).json()
    by_id = {t["kc_id"]: t for t in body["topics"]}
    assert set(by_id) >= {w.kc_a, w.kc_b} and body["grade_level"] == 7
    assert by_id[w.kc_a]["question_count"] == 1 and by_id[w.kc_a]["evidence_count"] == 1
    assert by_id[w.kc_a]["difficulty_tier"] == 2
    assert by_id[w.kc_b]["mastery_probability"] is None
    w.kc("G9", grade=9)
    r = client.get(f"/api/v1/curriculum/items/{w.grade_item(9)}/topics", headers=h)
    assert r.status_code == 404 and r.json()["error"]["code"] == "item_not_found"
    teacher = client.post(
        "/api/v1/auth/login",
        json={"login_identifier": w.teacher_user.login_identifier, "credential": w.password},
    ).json()["access_token"]
    staff = client.get(
        f"/api/v1/curriculum/items/{w.grade_item(9)}/topics",
        headers={"Authorization": f"Bearer {teacher}"},
    )
    assert staff.status_code == 200


def test_recommendation_endpoint_is_deterministic_and_typed(ctx) -> None:
    client, w, pg, _app, h = ctx
    r = client.get("/api/v1/student/recommendation", headers=h)
    assert r.status_code == 200
    body = r.json()
    # Production mode with no released snapshot: a controlled outcome, never a guess.
    assert body["status"] == "insufficient_data" and body["reason"]
    assert body["content_release"] == "production"
    assert (
        client.get("/api/v1/student/recommendation?subject_id=nope", headers=h).status_code == 404
    )
    teacher = client.post(
        "/api/v1/auth/login",
        json={"login_identifier": w.teacher_user.login_identifier, "credential": w.password},
    ).json()["access_token"]
    assert (
        client.get(
            "/api/v1/student/recommendation", headers={"Authorization": f"Bearer {teacher}"}
        ).status_code
        == 403
    )


def test_doubt_is_grounded_with_database_citations(ctx) -> None:
    client, w, pg, _app, h = ctx
    source = add_evidence(pg, w)
    body = ask(client, h).json()
    assert body["status"] == "ok" and body["grounding"] == "grounded"
    assert body["citations"] == [
        {
            "label": "E1",
            "source_id": source,
            "pdf_page_index": 3,
            "printed_page_label": "4",
            "item_title": f"{MARK} chapter",
        }
    ]
    assert "SYNTHETIC evidence" not in json.dumps(body)  # source text is not echoed


def test_doubt_abstains_without_evidence_rights_or_model(ctx) -> None:
    client, w, pg, app, h = ctx
    none = ask(client, h).json()
    assert none["status"] == "insufficient_evidence" and none["grounding"] == "abstained"
    assert none["explanation"] == "" and none["citations"] == []
    add_evidence(pg, w)
    app.dependency_overrides[doubts.get_rights_check] = lambda: deny_all
    assert ask(client, h).json()["status"] == "not_authorized"
    app.dependency_overrides[doubts.get_rights_check] = lambda: allow_all
    app.dependency_overrides[doubts.get_llm] = lambda: chat(dict(GOOD, explanation="no cite"))
    assert ask(client, h).json()["status"] == "invalid_model_output"
    app.dependency_overrides[doubts.get_llm] = lambda: None
    assert ask(client, h).json()["status"] == "model_unavailable"


def test_doubt_model_timeout_is_a_controlled_outcome(ctx) -> None:
    client, w, pg, app, h = ctx
    add_evidence(pg, w)

    def slow(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=TAGS)
        raise httpx.ReadTimeout("slow")

    app.dependency_overrides[doubts.get_llm] = lambda: LocalLLM(
        "http://localhost:11434", "qwen3.5:9b", transport=httpx.MockTransport(slow)
    )
    r = ask(client, h)
    assert r.status_code == 200 and r.json()["status"] == "model_timeout"
    assert r.json()["grounding"] == "abstained" and r.json()["explanation"] == ""


def test_doubt_scope_comes_from_enrollment_and_requests_are_limited(ctx) -> None:
    client, w, pg, _app, h = ctx
    add_evidence(pg, w, grade=9)  # evidence exists only for a class the learner is not in
    assert ask(client, h).json()["status"] == "insufficient_evidence"
    grade9 = w.kc("G9", grade=9)
    assert ask(client, h, kc_id=grade9).status_code == 404
    assert ask(client, h, subject_id="nope").status_code == 404
    # 404s above are refused before the quota; three more requests use it up (4 per hour).
    assert [ask(client, h).status_code for _ in range(3)] == [200, 200, 200]
    limited = ask(client, h)
    assert limited.status_code == 429 and limited.headers["Retry-After"]
    assert client.post("/api/v1/doubts", headers=h, json={"question": "hi"}).status_code == 422
    assert (
        client.post("/api/v1/doubts", json={"question": "How do fractions work?"}).status_code
        == 401
    )
