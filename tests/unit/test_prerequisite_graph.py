"""Phase 5 slice: KC/edge schemas, graph validation, release gate, traversal and coverage."""

from __future__ import annotations

import random
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.schemas.knowledge import EdgeRecord, KcRecord
from app.services import prerequisite_graph as pg


def kc(
    kc_id: str, subject: str = "mathematics", status: str = "approved", classes=(7,), **kw
) -> KcRecord:
    return KcRecord(
        kc_id=kc_id,
        stable_key=kw.pop("stable_key", f"key.{kc_id.lower()}"),
        subject_id=subject,
        name=f"Skill {kc_id}",
        review_status=status,
        class_levels=classes,
        **kw,
    )


def edge(pre: str, dep: str, status: str = "approved", evidence=("src-1",), **kw) -> EdgeRecord:
    return EdgeRecord(
        prerequisite_kc_id=pre,
        dependent_kc_id=dep,
        reason=kw.pop("reason", f"{dep} uses {pre}"),
        evidence_refs=evidence,
        review_status=status,
        **kw,
    )


def chain():
    kcs = [kc("A", classes=(6, 7)), kc("B"), kc("C", classes=(7, 8)), kc("D", classes=(8,))]
    edges = [edge("A", "B"), edge("B", "C"), edge("A", "D")]
    return kcs, edges


# --- schemas ---------------------------------------------------------------------------


def test_schema_rejects_bad_shapes() -> None:
    good = dict(kc_id="K1", stable_key="skill.one", subject_id="mathematics", name="One")
    KcRecord(**good)
    for change in (
        {"kc_id": ""},
        {"kc_id": "has space"},
        {"stable_key": "Bad Key"},
        {"stable_key": "UPPER"},
        {"name": "  "},
        {"class_levels": (5,)},
        {"class_levels": (11,)},
        {"review_status": "pending"},
        {"difficulty_tier": 0},
        {"extra_field": 1},
    ):
        with pytest.raises(ValidationError):
            KcRecord(**{**good, **change})
    egood = dict(prerequisite_kc_id="A", dependent_kc_id="B", reason="B needs A")
    EdgeRecord(**egood)
    for change in (
        {"reason": ""},
        {"reason": "   "},
        {"strength": 0},
        {"review_status": "x"},
        {"score": 1},
    ):
        with pytest.raises(ValidationError):
            EdgeRecord(**{**egood, **change})
    assert EdgeRecord(**egood).review_status == "needs_review"  # never approved by default


def test_records_are_immutable() -> None:
    with pytest.raises(ValidationError):
        chain()[0][0].name = "other"  # type: ignore[misc]


# --- validation rules ------------------------------------------------------------------


def test_valid_graph_is_released() -> None:
    kcs, edges = chain()
    report = pg.validate_graph(kcs, edges)
    assert report.ok and not report.issues
    assert [e.key for e in report.released_edges] == [("A", "B"), ("A", "D"), ("B", "C")]


def test_duplicate_ids_and_keys_are_errors() -> None:
    kcs, edges = chain()
    dup = kcs + [kc("A", stable_key="key.other")]
    assert "DUPLICATE_KC_ID" in pg.validate_graph(dup, edges).codes("error")
    dupkey = kcs + [kc("Z", stable_key="key.a")]
    assert "DUPLICATE_STABLE_KEY" in pg.validate_graph(dupkey, edges).codes("error")


def test_orphan_endpoints_self_edges_and_duplicate_edges() -> None:
    kcs, _ = chain()
    report = pg.validate_graph(
        kcs, [edge("A", "GHOST"), edge("B", "B"), edge("A", "B"), edge("A", "B")]
    )
    assert {"MISSING_ENDPOINT", "SELF_EDGE", "DUPLICATE_EDGE"} <= set(report.codes("error"))
    missing = next(i for i in report.issues if i.code == "MISSING_ENDPOINT")
    assert missing.items == ("GHOST",)
    assert report.released_edges == ()  # fail closed


def test_approved_cycle_is_an_error_and_blocks_release() -> None:
    kcs, edges = chain()
    cyc = edges + [edge("C", "A")]
    report = pg.validate_graph(kcs, cyc)
    assert "CYCLE" in report.codes("error") and not report.ok
    assert report.released_edges == ()
    two = pg.validate_graph(kcs, [edge("A", "B"), edge("B", "A")])
    assert "CYCLE" in two.codes("error")
    with pytest.raises(pg.GraphNotReleasable):
        pg.PrerequisiteGraph(kcs, report)


def test_cycle_among_proposals_is_a_warning_not_a_release() -> None:
    kcs, edges = chain()
    report = pg.validate_graph(kcs, edges + [edge("C", "A", status="needs_review")])
    assert report.ok and "CYCLE_IN_PROPOSALS" in report.codes("warning")
    assert ("C", "A") not in [e.key for e in report.released_edges]  # proposals are never released
    # A cycle that includes only rejected edges is ignored.
    assert not pg.validate_graph(kcs, edges + [edge("C", "A", status="rejected")]).issues


def test_unapproved_edges_are_never_released() -> None:
    kcs, _ = chain()
    for status in ("needs_review", "in_review", "rejected"):
        report = pg.validate_graph(kcs, [edge("A", "B", status=status)])
        assert report.ok and report.released_edges == (), status


def test_approved_edge_needs_evidence_and_approved_kcs() -> None:
    kcs, _ = chain()
    no_evidence = pg.validate_graph(kcs, [edge("A", "B", evidence=())])
    assert (
        "EDGE_WITHOUT_EVIDENCE" in no_evidence.codes("error") and no_evidence.released_edges == ()
    )
    proposal = pg.validate_graph(kcs, [edge("A", "B", status="needs_review", evidence=())])
    assert proposal.ok and "PROPOSAL_WITHOUT_EVIDENCE" in proposal.codes("warning")
    unreviewed = [kc("A"), kc("B", status="needs_review")]
    assert "EDGE_ENDPOINT_KC_NOT_APPROVED" in pg.validate_graph(unreviewed, [edge("A", "B")]).codes(
        "error"
    )
    rejected = [kc("A"), kc("B", status="rejected")]
    assert "EDGE_TOUCHES_REJECTED_KC" in pg.validate_graph(rejected, [edge("A", "B")]).codes(
        "error"
    )


def test_report_is_deterministic_for_any_input_order() -> None:
    kcs, edges = chain()
    edges += [edge("C", "A", status="needs_review"), edge("A", "GHOST", status="needs_review")]
    base = pg.validate_graph(kcs, edges)
    rng = random.Random(7)
    for _ in range(5):
        a, b = kcs[:], edges[:]
        rng.shuffle(a)
        rng.shuffle(b)
        assert pg.validate_graph(a, b) == base


# --- released graph --------------------------------------------------------------------


def released(kcs, edges) -> pg.PrerequisiteGraph:
    return pg.PrerequisiteGraph(kcs, pg.validate_graph(kcs, edges))


def test_traversal_on_a_released_graph() -> None:
    kcs, edges = chain()
    graph = released(kcs, edges)
    assert graph.prerequisites("C") == ["B", "A"]  # nearest first
    assert graph.prerequisites("C", max_depth=1) == ["B"]
    assert graph.direct_prerequisites("C") == ["B"]
    assert graph.dependents("A") == ["B", "D", "C"]
    assert graph.roots() == ["A"]
    assert graph.layers() == [["A"], ["B", "D"], ["C"]]
    assert graph.prerequisites("A") == []
    with pytest.raises(pg.UnknownKc):
        graph.prerequisites("nope")


def test_roots_are_not_assumed_to_be_in_class_6() -> None:
    kcs = [kc("X", classes=(8,)), kc("Y", classes=(9,))]
    graph = released(kcs, [edge("X", "Y")])
    assert graph.roots() == ["X"]
    cov = pg.coverage_report(kcs, [edge("X", "Y")])
    assert cov["roots_by_class"]["8"] == ["X"] and cov["roots_by_class"]["6"] == []


def test_unapproved_edges_do_not_appear_in_traversal() -> None:
    kcs, edges = chain()
    graph = released(kcs, edges + [edge("D", "C", status="needs_review")])
    assert graph.direct_prerequisites("C") == ["B"]


# --- coverage --------------------------------------------------------------------------


def test_coverage_by_subject_and_class() -> None:
    kcs = [
        kc("A", classes=(6, 7)),
        kc("B", classes=(7,)),
        kc("S1", subject="science", classes=(8,)),
        kc("S2", subject="science", status="needs_review", classes=()),
    ]
    edges = [edge("A", "B"), edge("A", "S1"), edge("S1", "S2", status="needs_review")]
    cov = pg.coverage_report(kcs, edges)
    assert (cov["kc_count"], cov["edge_count"], cov["approved_edge_count"]) == (4, 3, 2)
    assert cov["cross_subject_approved_edges"] == 1
    maths, science = cov["subjects"]["mathematics"], cov["subjects"]["science"]
    assert maths["kcs_by_class"] == {"6": 1, "7": 2, "8": 0, "9": 0, "10": 0}
    assert science["kcs_by_class"]["8"] == 1 and science["kcs_without_class_mapping"] == ["S2"]
    assert science["kcs_by_review_status"] == {"approved": 1, "needs_review": 1}
    assert science["edges_by_review_status"] == {
        "needs_review": 1,
        "in_review": 0,
        "approved": 1,
        "rejected": 0,
    }
    assert science["kcs_without_approved_edges"] == ["S2"]
    assert science["roots"] == ["S2"]  # no approved prerequisite yet
    assert cov["roots_by_class"]["6"] == ["A"]
    assert pg.validate_graph(kcs, edges).coverage == cov


def test_empty_input_is_valid_and_reports_zero() -> None:
    report = pg.validate_graph([], [])
    assert report.ok and report.coverage["kc_count"] == 0 and report.released_edges == ()


# --- purity ----------------------------------------------------------------------------


def test_service_has_no_framework_database_or_provider_imports() -> None:
    code = (
        "import sys, app.services.prerequisite_graph;"
        "banned=('fastapi','sqlalchemy','psycopg','groq','httpx','ollama');"
        "bad=[m for m in banned if m in sys.modules];"
        "print(bad)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout
    assert out.strip() == "[]"
