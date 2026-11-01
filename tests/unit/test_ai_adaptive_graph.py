"""LLM/embedding adapters (mock transport), grounded generation, adaptive engine, graph."""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

import httpx
import pytest

from app.schemas.knowledge import EdgeRecord, KcRecord
from app.services import adaptive, ai_generation, graph_runtime
from app.services.embeddings import (
    EmbeddingUnavailable,
    InvalidEmbedding,
    OllamaEmbedder,
    validate_vectors,
)
from app.services.llm import (
    LLMInvalidOutput,
    LLMNotPermitted,
    LLMTimeout,
    LLMUnavailable,
    LocalLLM,
    build_llm,
)
from app.services.prerequisite_graph import PrerequisiteGraph, validate_graph
from app.services.rag import Evidence
from data_pipeline.authorization import Decision

TAGS = {
    "models": [
        {"name": "qwen3.5:9b", "digest": "abc123def456789"},
        {"name": "bge-m3:latest", "digest": "fff111222333444"},
    ]
}


def llm(handler) -> LocalLLM:
    return LocalLLM("http://localhost:11434", "qwen3.5:9b", transport=httpx.MockTransport(handler))


def chat_reply(content: dict | str):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=TAGS)
        body = json.loads(request.content)
        assert body["think"] is False and body["stream"] is False and body["format"]
        assert body["options"]["num_ctx"] == 4096
        text = content if isinstance(content, str) else json.dumps(content)
        return httpx.Response(200, json={"message": {"content": text}, "eval_count": 7})

    return handler


def test_llm_identity_and_unavailability() -> None:
    assert llm(chat_reply({})).identity().digest == "abc123def456789"

    def down(request):
        raise httpx.ConnectError("refused")

    assert llm(down).identity().available is False
    with pytest.raises(LLMUnavailable):
        llm(down).generate("s", "u", ai_generation.HintOut)

    def slow(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(LLMTimeout):
        llm(slow).generate("s", "u", ai_generation.HintOut)


def test_llm_structured_output_is_validated() -> None:
    ok = llm(chat_reply({"sufficient": True, "hint": "h", "evidence_labels": ["E1"]}))
    gen = ok.generate("s", "u", ai_generation.HintOut)
    assert gen.value.hint == "h" and gen.model.digest == "abc123def456789"
    assert gen.usage == {"eval_count": 7}
    with pytest.raises(LLMInvalidOutput):
        llm(chat_reply("not json")).generate("s", "u", ai_generation.HintOut)
    with pytest.raises(LLMInvalidOutput):
        llm(chat_reply({"sufficient": True, "extra": 1})).generate("s", "u", ai_generation.HintOut)


def test_no_cloud_route_is_ever_built() -> None:
    from app.core.config import get_settings

    settings = get_settings()
    with pytest.raises(LLMNotPermitted):
        build_llm(settings.model_copy(update={"llm_fallback_enabled": True}))
    with pytest.raises(LLMNotPermitted):
        build_llm(settings.model_copy(update={"llm_primary_provider": "groq"}))
    assert build_llm(settings).base_url.startswith("http")


def test_embedder_identity_dimensions_and_failures() -> None:
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=TAGS)
        texts = json.loads(request.content)["input"]
        return httpx.Response(200, json={"embeddings": [[1.0, 0.5, 0.25]] * len(texts)})

    embedder = OllamaEmbedder("bge-m3", transport=httpx.MockTransport(handler), batch_size=2)
    model = embedder.describe()
    assert model.dimension == 3 and model.model_id == "ollama:bge-m3@fff111222333"
    assert len(embedder.embed(["a", "b", "c"])) == 3
    with pytest.raises(InvalidEmbedding):
        validate_vectors([[1.0, 2.0], [1.0]])
    with pytest.raises(InvalidEmbedding):
        validate_vectors([[0.0, 0.0]])
    with pytest.raises(InvalidEmbedding):
        validate_vectors([[float("inf"), 1.0]])
    with pytest.raises(InvalidEmbedding):
        validate_vectors([[1.0, 2.0]], expected=1024)

    def down(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(EmbeddingUnavailable):
        OllamaEmbedder("bge-m3", transport=httpx.MockTransport(down)).describe()
    missing = OllamaEmbedder("nomic", transport=httpx.MockTransport(handler))
    with pytest.raises(EmbeddingUnavailable, match="not_installed"):
        missing.describe()


# --- grounded generation ------------------------------------------------------------------


def ev(label: str, source: str = "SRC-SYN-1") -> Evidence:
    return Evidence(
        label,
        uuid.uuid4(),
        f"{source}:p000",
        source,
        "a" * 64,
        0,
        "1",
        "I1",
        "Item",
        "V1",
        "b" * 64,
        "approved",
        "ollama:test",
        "g1",
        0.9,
        "Equivalent fractions name the same part of a whole.",
    )


def gate(allowed: set[str]):
    return lambda sid, sha, use, records=None: Decision(use, sid in allowed, "test gate")


def test_grounded_explanation_paths() -> None:
    good = {
        "sufficient": True,
        "concept": "c",
        "explanation": "e",
        "steps": [],
        "hint": "",
        "evidence_labels": ["E1"],
    }
    assert (
        ai_generation.generate_explanation(llm(chat_reply(good)), "q", [], gate(set())).status
        == "insufficient_evidence"
    )
    denied = ai_generation.generate_explanation(llm(chat_reply(good)), "q", [ev("E1")], gate(set()))
    assert denied.status == "not_authorized" and denied.excluded_sources
    ok = ai_generation.generate_explanation(
        llm(chat_reply(good)), "q", [ev("E1")], gate({"SRC-SYN-1"})
    )
    assert ok.status == "ok" and ok.citations[0]["source_id"] == "SRC-SYN-1"
    assert ok.citations[0]["pdf_page_index"] == 0 and "text" not in ok.citations[0]
    invented = dict(good, evidence_labels=["E9"])
    assert (
        ai_generation.generate_explanation(
            llm(chat_reply(invented)), "q", [ev("E1")], gate({"SRC-SYN-1"})
        ).status
        == "invalid_model_output"
    )
    unsure = dict(good, sufficient=False, evidence_labels=[])
    assert (
        ai_generation.generate_explanation(
            llm(chat_reply(unsure)), "q", [ev("E1")], gate({"SRC-SYN-1"})
        ).status
        == "insufficient_evidence"
    )

    def down(request):
        raise httpx.ConnectError("x")

    assert (
        ai_generation.generate_hint(llm(down), "q", [ev("E1")], gate({"SRC-SYN-1"})).status
        == "model_unavailable"
    )


def test_real_sources_are_not_authorised_for_generation_today() -> None:
    from data_pipeline.authorization import check_use

    for use in (ai_generation.EXPLANATION_USE, ai_generation.QUESTION_USE):
        assert not check_use("SRC-C10-MAT-JEMH1-02", "f040ca888111" + "0" * 52, use).permitted


def test_question_draft_from_model_is_a_draft_with_provenance() -> None:
    out = {
        "stem": "Which fraction equals one half?",
        "explanation": "2/4 = 1/2",
        "evidence_labels": [],
        "options": [
            {"option_key": k, "option_text": t, "is_correct": k == "B"}
            for k, t in zip("ABCD", ["1/3", "2/4", "3/4", "1/4"], strict=True)
        ],
    }
    spec = ai_generation.QuestionSpec(
        7, "mathematics", "fractions", "equivalence", 2, synthetic=True
    )
    draft, result = ai_generation.generate_question_draft(
        llm(chat_reply(out)), spec, [], gate(set())
    )
    assert result.status == "ok" and draft.origin == "synthetic" and not draft.source_refs
    real = ai_generation.QuestionSpec(7, "mathematics", "fractions", "equivalence", 2)
    none, refused = ai_generation.generate_question_draft(
        llm(chat_reply(out)), real, [ev("E1")], gate(set())
    )
    assert none is None and refused.status == "not_authorized"


# --- graph runtime and adaptive ------------------------------------------------------------


def released(kcs: list[KcRecord], edges: list[EdgeRecord]) -> graph_runtime.ReleasedGraph:
    report = validate_graph(kcs, edges)
    assert report.ok
    return graph_runtime.ReleasedGraph(
        PrerequisiteGraph(kcs, report), 1, "f" * 64, {k.kc_id: k.model_dump() for k in kcs}
    )


def kc(kc_id: str, classes=(7,), scope="target") -> KcRecord:
    return KcRecord(
        kc_id=kc_id,
        stable_key=f"syn.{kc_id.lower()}",
        subject_id="mathematics",
        name=kc_id,
        review_status="approved",
        class_levels=classes,
        scope=scope,
    )


def edge(a: str, b: str) -> EdgeRecord:
    return EdgeRecord(
        prerequisite_kc_id=a,
        dependent_kc_id=b,
        reason="uses",
        evidence_refs=("x",),
        review_status="approved",
    )


G = released(
    [kc("F", (), "foundation"), kc("A"), kc("B"), kc("C")],
    [edge("F", "A"), edge("A", "B"), edge("A", "C")],
)
QS = {
    k: [adaptive.QuestionView(f"Q-{k}-1", 1), adaptive.QuestionView(f"Q-{k}-5", 5)]
    for k in ("F", "A", "B", "C")
}
SCOPE = adaptive.LearnerScope(class_level=7)
M = adaptive.MasteryView


def test_unreleased_graph_gives_typed_insufficient_data() -> None:
    result = adaptive.recommend(
        graph_runtime.GraphUnavailable("graph_not_released"), SCOPE, {}, QS, set()
    )
    assert result.status == "insufficient_data" and result.reason == "graph_not_released"
    with tempfile.TemporaryDirectory() as tmp:
        state = graph_runtime.get_released_graph(Path(tmp), Path(tmp) / "none.jsonl")
    assert state.reason == "graph_not_released"
    assert graph_runtime.get_prerequisites(state, "A").reason == "graph_not_released"


def test_missing_evidence_on_a_prerequisite_triggers_remediation_first() -> None:
    rec = adaptive.recommend(G, SCOPE, {}, QS, set())
    assert rec.kc_id == "F" and rec.category == "remediate_prerequisite"
    assert any("no evidence" in r for r in rec.rationale) and rec.question_id == "Q-F-1"


def test_low_mastery_vs_ready_and_deterministic_ranking() -> None:
    mastery = {"F": M(0.9, 5), "A": M(0.4, 3)}
    rec = adaptive.recommend(G, SCOPE, mastery, QS, set())
    # A is in scope but blocks B and C at 0.40 (< readiness 0.70): listed once, as remediation.
    assert (rec.kc_id, rec.category) == ("A", "remediate_prerequisite")
    assert "low mastery 0.40" in rec.rationale[0] and "B, C" in rec.rationale[1]
    ranking = adaptive.rank_learning_candidates(G, SCOPE, mastery, {k: 2 for k in "FABC"})
    assert [c.kc_id for c in ranking.candidates] == ["A"]
    assert rec.question_id == "Q-A-1"  # closest difficulty to 1 + 4 * 0.4
    mastery["A"] = M(0.96, 9)
    rec = adaptive.recommend(G, SCOPE, mastery, QS, {"Q-B-1"})
    assert (rec.kc_id, rec.category, rec.question_id) == ("B", "new", "Q-B-5")
    assert adaptive.recommend(G, SCOPE, mastery, QS, set()) == adaptive.recommend(
        G, SCOPE, mastery, QS, set()
    )


def test_only_approved_content_and_all_mastered() -> None:
    mastery = {"F": M(0.9, 5), "A": M(0.4, 3)}
    rec = adaptive.recommend(G, SCOPE, mastery, {"B": QS["B"]}, set())
    assert rec.status == "insufficient_data" and rec.reason == "no_recommendable_content"
    done = {k: M(0.99, 10) for k in "FABC"}
    assert adaptive.recommend(G, SCOPE, done, QS, set()).reason == "all_scoped_kcs_mastered"
    assert (
        adaptive.explain_recommendation(adaptive.recommend(G, SCOPE, {}, QS, set()))["thresholds"][
            "provisional"
        ]
        is True
    )


def test_learning_path_validation() -> None:
    assert graph_runtime.validate_learning_path(G, ["F", "A", "B"]).valid
    bad = graph_runtime.validate_learning_path(G, ["B", "A", "X"])
    assert not bad.valid and len(bad.problems) == 2
    assert graph_runtime.get_prerequisites(G, "B") == ["A", "F"]
    assert graph_runtime.get_prerequisites(G, "Z").reason == "kc_not_in_released_graph"


def test_released_snapshot_from_the_phase5_pipeline_loads_and_tamper_fails(tmp_path) -> None:
    from data_pipeline.kc_graph import release, synthetic, validate

    inputs = synthetic.build(tmp_path / "pkg")
    path = release.release(validate.run(inputs), tmp_path / "final", allow_synthetic_output=True)
    lifecycle = inputs.review_dir / "lifecycle_log.jsonl"
    state = graph_runtime.get_released_graph(tmp_path / "final", lifecycle)
    assert state.available and state.version.startswith("released_graph_1@")
    assert graph_runtime.get_prerequisites(state, "KC-MAT-00002") == [
        "KC-MAT-00001",
        "KC-MAT-00004",
    ]
    data = json.loads(path.read_text())
    data["kcs"][0]["name"] = "tampered"
    (tmp_path / "final" / "released_graph_2.json").write_text(json.dumps(data))
    broken = graph_runtime.get_released_graph(tmp_path / "final", lifecycle)
    assert not broken.available and "SNAPSHOT_DIGEST_MISMATCH" in broken.detail


def test_inline_labels_fill_empty_evidence_labels_but_stay_checkable() -> None:
    from app.services.ai_generation import _inline_labels

    value = {
        "explanation": "Tracks show a limp (E4) and a short tail (E2, E2).",
        "evidence_labels": [],
    }
    assert _inline_labels(value) == ["E2", "E4"]
    assert _inline_labels({"explanation": "No citation here."}) == []


def test_uncited_answer_gets_one_citation_repair_and_is_still_validated() -> None:
    uncited = {
        "sufficient": True,
        "concept": "c",
        "explanation": "An answer with no citation.",
        "steps": [],
        "hint": "",
        "evidence_labels": [],
    }
    cited = dict(uncited, evidence_labels=["E1"])
    invented = dict(uncited, evidence_labels=["E7"])
    replies = iter([uncited, cited])

    def sequence(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=TAGS)
        return httpx.Response(200, json={"message": {"content": json.dumps(next(replies))}})

    ok = ai_generation.generate_explanation(llm(sequence), "q", [ev("E1")], gate({"SRC-SYN-1"}))
    assert ok.status == "ok" and ok.citations[0]["source_id"] == "SRC-SYN-1"
    replies = iter([uncited, invented])
    bad = ai_generation.generate_explanation(llm(sequence), "q", [ev("E1")], gate({"SRC-SYN-1"}))
    assert bad.status == "invalid_model_output"  # the repair cannot invent a citation
    replies = iter([uncited, uncited])
    still = ai_generation.generate_explanation(llm(sequence), "q", [ev("E1")], gate({"SRC-SYN-1"}))
    assert still.status == "invalid_model_output"
