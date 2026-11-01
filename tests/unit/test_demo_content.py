"""Demo-release mode: fail-closed config, serving split, demo graph, importer, assembly checks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from live_db_fixtures import World, live_engine, pg_fixture  # noqa: F401  (fixtures)
from sqlalchemy import select

from app.core import content_release
from app.core.config import get_settings
from app.db.models import (
    CurriculumItem,
    CurriculumVersion,
    KcCurriculumMap,
    KcEdge,
    KnowledgeComponent,
    SourceDocument,
)
from app.db.session import get_db
from app.main import create_app
from app.services import graph_runtime, learning
from app.services.question_bank import OptionDraft
from data_pipeline.demo_content import assemble, importer


@pytest.fixture
def demo_mode(monkeypatch):
    demo = get_settings().model_copy(
        update={"content_release_mode": "demo", "app_env": "development"}
    )
    monkeypatch.setattr(content_release, "get_settings", lambda: demo)
    return demo


def test_demo_mode_is_refused_outside_development() -> None:
    from app.core.config import Settings

    base = get_settings().model_dump()
    for env in ("staging", "production"):
        with pytest.raises(ValueError, match="CONTENT_RELEASE_MODE=demo"):
            Settings(
                **{
                    **base,
                    "app_env": env,
                    "content_release_mode": "demo",
                    "database_url": get_settings().database_url,
                }
            )
    prod = get_settings().model_copy(update={"content_release_mode": "production"})
    assert content_release.servable_review_statuses(prod) == ("approved",)
    assert content_release.servable_curriculum_statuses(prod) == ("published",)
    staged = get_settings().model_copy(
        update={"content_release_mode": "demo", "app_env": "staging"}
    )
    assert content_release.demo_enabled(staged) is False  # even a bypassed validator fails closed


def demo_world(pg) -> World:
    w = World(pg)
    for kc_id in (w.kc_a, w.kc_b):
        pg.get(KnowledgeComponent, kc_id).review_status = "demo_release"
    vid, item = f"SYN-V-{w.tag}", f"SYN-I-{w.tag}"
    pg.add(
        CurriculumVersion(
            curriculum_version_id=vid,
            board="SYN",
            class_level=7,
            academic_session="2026-27",
            status="demo_release",
        )
    )
    pg.flush()
    pg.add(
        CurriculumItem(
            item_id=item,
            curriculum_version_id=vid,
            subject_id="mathematics",
            title="SYNTHETIC chapter",
            status="demo_release",
        )
    )
    pg.flush()
    for kc_id in (w.kc_a, w.kc_b):
        pg.add(KcCurriculumMap(kc_id=kc_id, item_id=item, review_status="demo_release"))
    pg.add(
        KcEdge(
            prerequisite_kc_id=w.kc_a,
            dependent_kc_id=w.kc_b,
            strength=2,
            reason="[uses_concept] synthetic",
            review_status="demo_release",
        )
    )
    pg.flush()
    w.item = item
    w.config("demo", datetime.now(UTC) - timedelta(days=1))
    return w


@pytest.mark.live_db
def test_demo_rows_are_invisible_in_production_and_served_in_demo(pg, monkeypatch) -> None:
    w = demo_world(pg)
    qid = w.question([w.kc_a], status="demo_release", mapping_status="demo_release")
    app = create_app()
    app.dependency_overrides[get_db] = lambda: pg
    with TestClient(app) as client:
        token = client.post(
            "/api/v1/auth/login",
            json={"login_identifier": w.student_user.login_identifier, "credential": w.pin},
        ).json()
        h = {"Authorization": f"Bearer {token['access_token']}"}
        prod = get_settings().model_copy(update={"content_release_mode": "production"})
        monkeypatch.setattr(content_release, "get_settings", lambda: prod)
        assert client.get(f"/api/v1/topics/{w.kc_a}/questions", headers=h).status_code == 404
        assert (
            client.post(
                "/api/v1/attempts",
                headers=h,
                json={
                    "question_id": qid,
                    "question_version": 1,
                    "submitted_answer": {"option_key": "B"},
                    "idempotency_key": "synthetic-demo-0001",
                },
            ).status_code
            == 404
        )
        assert isinstance(graph_runtime.get_runtime_graph(pg), graph_runtime.GraphUnavailable)
        demo = get_settings().model_copy(
            update={"content_release_mode": "demo", "app_env": "development"}
        )
        monkeypatch.setattr(content_release, "get_settings", lambda: demo)
        listed = client.get(f"/api/v1/topics/{w.kc_a}/questions", headers=h).json()
        assert [q["question_id"] for q in listed["questions"]] == [qid]
        r = client.post(
            "/api/v1/attempts",
            headers=h,
            json={
                "question_id": qid,
                "question_version": 1,
                "submitted_answer": {"option_key": "B"},
                "idempotency_key": "synthetic-demo-0002",
            },
        ).json()
        assert r["scored_correct"] is True and r["bkt"]["updated"] is True
        curriculum = client.get("/api/v1/curriculum?grade_level=7", headers=h).json()
        mine = [
            c for c in curriculum["curricula"] if c["curriculum_version_id"] == f"SYN-V-{w.tag}"
        ]
        assert mine and mine[0]["coverage"]["state"] == "demo_release"  # never "published"


@pytest.mark.live_db
def test_demo_graph_and_recommendation_end_to_end(pg, demo_mode) -> None:
    w = demo_world(pg)
    w.question([w.kc_a], status="demo_release", mapping_status="demo_release")
    w.question([w.kc_b], status="demo_release", mapping_status="demo_release")
    graph = graph_runtime.get_demo_graph(pg)
    assert graph.available and graph.kind == "demo" and graph.version.startswith("demo_graph@")
    assert graph_runtime.get_prerequisites(graph, w.kc_b) == [w.kc_a]
    rec = learning.recommend_for_learner(pg, w.learner.learner_id)
    # the dev database now holds the real demo dataset for the same class and subject, so the
    # ranked pick is not necessarily the synthetic KC; assert the contract, not the identity
    assert rec["status"] == "ok" and rec["content_release"] == "demo" and rec["kc_id"]
    assert rec["category"] == "remediate_prerequisite" and rec["rationale"]
    stranger = uuid.uuid4()
    assert learning.recommend_for_learner(pg, stranger)["reason"] == "no_active_enrollment"


def dataset(w: World, source_id: str) -> dict:
    kc = {
        "kc_id": f"KC-MAT-9{w.tag[:4]}",
        "stable_key": f"mathematics.fractions.syn-{w.tag}",
        "subject_id": "mathematics",
        "name": "SYNTHETIC KC",
        "learning_objective": "Do it.",
        "kc_type": "procedure",
        "difficulty_tier": 2,
        "misconceptions": [],
        "inventory_ids": [w.item],
        "class_level": 7,
    }
    question = {
        "item_type": "single_choice",
        "stem": "SYNTHETIC: which fraction equals one half?",
        "options": [
            {"option_key": k, "option_text": t, "is_correct": k == "B", "explanation": None}
            for k, t in zip("ABC", ["1/3", "2/4", "3/4"], strict=True)
        ],
        "difficulty": 2,
        "class_level": 7,
        "subject_id": "mathematics",
        "kc_ids": [kc["kc_id"]],
        "curriculum_item_id": w.item,
        "source_refs": [{"source_id": source_id, "sha256": "ab" * 6, "pdf_page_index": 0}],
        "origin": "ai_drafted",
        "origin_ref": "ollama:test|demo|r1",
        "language": "en",
    }
    return {
        "chapters": [{"source_id": source_id, "inventory_id": w.item}],
        "kcs": [kc],
        "edges": [],
        "questions": [question],
        "prompt_version": "test",
    }


@pytest.mark.live_db
def test_importer_is_idempotent_and_never_overwrites_reviewed_rows(pg) -> None:
    w = demo_world(pg)
    source_id = f"SYN-SRC-{w.tag}"
    pg.add(
        SourceDocument(
            source_id=source_id, subject_id="mathematics", sha256="ab" * 32, status="synthetic"
        )
    )
    pg.get(CurriculumItem, w.item).status = "needs_review"
    pg.flush()
    data = dataset(w, source_id)
    first = importer.apply_dataset(pg, data)
    assert first["stats"]["knowledge_component"]["insert"] == 1
    assert first["stats"]["questions"]["insert"] == 1 and first["rejected_questions"] == []
    assert pg.get(CurriculumItem, w.item).status == "demo_release"
    second = importer.apply_dataset(pg, data)
    assert second["stats"]["questions"] == {"insert": 0, "update": 0, "unchanged": 1}
    assert second["stats"]["knowledge_component"]["unchanged"] == 1
    kc = pg.scalar(
        select(KnowledgeComponent).where(KnowledgeComponent.kc_id == data["kcs"][0]["kc_id"])
    )
    kc.review_status = "approved"  # pretend a human approved it
    pg.flush()
    with pytest.raises(importer.ImportConflict, match="non-demo"):
        importer.apply_dataset(pg, data)
    bad = dataset(w, source_id)
    bad["questions"][0]["source_refs"][0]["sha256"] = "cd" * 6
    bad["kcs"][0]["review_status"] = "demo_release"
    kc.review_status = "demo_release"
    pg.flush()
    assert importer.apply_dataset(pg, bad)["rejected_questions"][0]["problems"] == [
        "SOURCE_REF_UNVERIFIED"
    ]


def test_assembly_checks() -> None:
    o = lambda k, t, c: OptionDraft(option_key=k, option_text=t, is_correct=c)  # noqa: E731
    wrong = [o("A", "$14/8$", False), o("B", "$25/16$", True), o("C", "$49/8$", False)]
    assert assemble.numeric_option_problems(wrong, "(7/4)**2", "single_choice") == [
        "maths_no_unique_matching_option"
    ]
    right = [o("A", "14/8", False), o("B", "49/16", True), o("C", "49/8", False)]
    assert assemble.numeric_option_problems(right, "(7/4)**2", "single_choice") == []
    swapped = [o("A", "49/16", False), o("B", "25/16", True), o("C", "1", False)]
    assert assemble.numeric_option_problems(swapped, "(7/4)**2", "single_choice") == [
        "maths_key_disagrees_with_expression"
    ]
    words = [o("A", "a square", True), o("B", "a cube", False)]
    assert assemble.numeric_option_problems(words, None, "single_choice") == []
    kc = {
        "name": "Add fractions",
        "learning_objective": "Add two fractions.",
        "kc_type": "procedure",
        "domain": "fractions",
        "concept_slug": "Add Unlike Fractions",
        "facet": "compute",
        "difficulty_tier": 2,
        "misconceptions": ["adds denominators"],
        "page_indices": [3, 99],
    }
    ok, problems = assemble.kc_problems(kc, "mathematics", {3, 4})
    assert (
        problems == [] and ok["stable_key"] == "mathematics.fractions.add-unlike-fractions.compute"
    )
    assert ok["page_indices"] == [3]
    assert assemble.kc_problems({**kc, "domain": "calculus"}, "mathematics", {3})[1] == [
        "unknown_domain"
    ]
    assert (
        "bad_concept_slug"
        in assemble.kc_problems({**kc, "concept_slug": "class-7-fractions"}, "mathematics", {3})[1]
    )

    def k(kid, cls):
        return {
            "kc_id": kid,
            "class_level": cls,
            "page_indices": [1],  # noqa: E731
            "source_id": "S",
        }

    by_local = {"a": k("A", 7), "b": k("B", 7), "c": k("C", 6)}

    def e(p, d, s=2):
        return (
            {
                "prerequisite": p,
                "dependent": d,
                "basis": "uses_concept",  # noqa: E731
                "reason": "uses it",
                "strength": s,
                "evidence_page": 1,
            },
            "batch",
        )

    kept, rejected = assemble.accept_edges(
        [e("a", "b", 3), e("b", "a", 1), e("b", "c"), e("a", "a"), e("a", "b")], by_local, []
    )
    assert [(x["prerequisite_kc_id"], x["dependent_kc_id"]) for x in kept] == [("A", "B")]
    assert sorted(r["reason_rejected"] for r in rejected) == [
        "duplicate",
        "prerequisite_in_later_class",
        "self_edge",
        "would_create_cycle",
    ]
    assert assemble._shingles(
        "one two three four five six seven eight nine ten eleven"
    ) & assemble._shingles("x one two three four five six seven eight nine ten y")


def test_slug_style_model_names_are_humanised_but_real_names_untouched() -> None:
    assert assemble.humanize("analyze-clues-to-infer-context") == "Analyze clues to infer context"
    assert assemble.humanize("Add two fractions") == "Add two fractions"
    assert assemble.humanize("  already_named ") == "Already named"


def test_topup_filters_reject_passage_dependence_duplicates_and_bare_options() -> None:
    def q(stem, item_type="single_choice", options=None):
        return {
            "item_type": item_type,
            "stem": stem,
            "options": options
            or [
                {"key": k, "text": f"opt {k}", "is_correct": k == "B", "explanation": "because x"}
                for k in "ABCD"
            ],
        }

    batch = {
        "output": {
            "questions": [
                q("According to the story, why did the merchant leave the village early?"),
                q("Which fraction is equal to one half of three quarters of a cake?"),
                q("Which fraction equals one half of three quarters of a cake?"),
                q(
                    "Water boils at 100 degrees Celsius at sea level.",
                    "true_false",
                    [
                        {"key": "B", "text": "true", "is_correct": True, "explanation": "it does"},
                        {"key": "A", "text": "false", "is_correct": False, "explanation": "no"},
                    ],
                ),
                q(
                    "Pick the prime number among the following options given here.",
                    options=[
                        {"key": k, "text": k, "is_correct": k == "A", "explanation": ""}
                        for k in "ABCD"
                    ],
                ),
            ]
        }
    }
    kept, rejected = assemble.topup_filters(batch, ["Which fraction is equal to one half?"])
    reasons = sorted(p for r in rejected for p in r["problems"])
    assert reasons == [
        "near_duplicate",  # a light paraphrase of the question kept just before it
        "option_explanation_missing",  # true/false with a two-letter explanation
        "option_explanation_missing",  # empty explanations
        "passage_dependent_stem",
    ]
    stems = [x["stem"] for x in kept["output"]["questions"]]
    assert stems == ["Which fraction is equal to one half of three quarters of a cake?"]


def test_rekey_spreads_the_correct_answer_and_keeps_one_key() -> None:
    positions = []
    for n in range(200):
        options = [
            {"key": k, "text": f"{n}-{k}", "is_correct": k == "B", "explanation": "e"}
            for k in "ABCD"
        ]
        out = assemble.rekey_single_choice(f"stem number {n}", options)
        assert [o["key"] for o in out] == list("ABCD")
        assert sum(o["is_correct"] for o in out) == 1
        positions.append(next(o["key"] for o in out if o["is_correct"]))
    counts = {k: positions.count(k) for k in "ABCD"}
    assert all(30 <= c <= 70 for c in counts.values()), counts


def test_ai_edges_are_never_labelled_as_expert_judgement() -> None:
    from data_pipeline.demo_content.importer import edge_reason

    assert edge_reason({"basis": "expert_judgement", "reason": "r"}) == "[ai-drafted:judgement] r"
    assert edge_reason({"basis": "uses_concept", "reason": "r"}) == "[ai-drafted:uses_concept] r"
