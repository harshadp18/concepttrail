"""M4/M5: retirement, released snapshots, fail-closed runtime loading and coverage (synthetic)."""

from __future__ import annotations

import json

import pytest
from kc_graph_fixtures import pkg_fixture  # noqa: F401  (registers the `pkg` fixture)

from app.services.audit_chain import seal
from app.services.graph_snapshot import (
    load_released_graph,
    snapshot_digest,
    verify_snapshot,
)
from data_pipeline.kc_graph import contract as c
from data_pipeline.kc_graph import lifecycle, release, review_log, validate

E12 = "KC-MAT-00001->KC-MAT-00002"


def retire_entry(**extra) -> dict:
    return {
        "kc_id": "KC-MAT-00002",
        "action": "retire",
        "authorised_by": "RV-004",
        "reason": "Split into two narrower skills.",
        "effective_at": "2026-02-01",
        "replacement_kc_ids": [],
        "learner_history_note": "student_kc_state kept; no transfer",
        "edge_resolution": [{"edge": E12, "resolution": "rejected"}],
        **extra,
    }


def lifecycle_append(pkg, entry: dict) -> dict:
    result = pkg.run()
    event = lifecycle.build_event(entry, result.kcs, result.edges, result.register, "2026-02-01")
    return review_log.append(pkg.review_dir / c.LIFECYCLE_LOG.name, event, "LC-")


def reject_edge(pkg) -> None:
    event = pkg.review(
        **pkg.edge_entry(
            E12,
            "src:SRC-C07-MAT-EXMP1-01@5:para2#a1b2c3d4e5f6",
            "RV-002",
            decision="rejected",
            rationale="KC2 retires.",
        )
    )
    pkg.edit_edge(E12, review_status="rejected", review_record_ids=event["event_id"])


def retired_pkg(pkg):
    reject_edge(pkg)
    lifecycle_append(pkg, retire_entry())
    pkg.anchor()
    return pkg


def released(pkg) -> dict:
    path = release.release(pkg.run(), pkg.root / "final", allow_synthetic_output=True)
    return json.loads(path.read_text())


def lifecycle_events(pkg) -> list[dict]:
    return review_log.read_jsonl(pkg.review_dir / c.LIFECYCLE_LOG.name, "lc")[0]


def test_retirement_needs_resolved_edges_and_a_senior_authoriser(pkg) -> None:
    with pytest.raises(ValueError, match="LIFECYCLE_EDGE_UNRESOLVED"):
        lifecycle_append(pkg, retire_entry(edge_resolution=[]))
    with pytest.raises(ValueError, match="LIFECYCLE_EDGE_UNRESOLVED"):
        lifecycle_append(pkg, retire_entry())  # recorded as rejected, but still approved
    with pytest.raises(ValueError, match="LIFECYCLE_UNAUTHORISED"):
        lifecycle_append(pkg, retire_entry(authorised_by="RV-002"))
    with pytest.raises(ValueError, match="LIFECYCLE_INVALID"):
        lifecycle_append(pkg, retire_entry(replacement_kc_ids=["KC-MAT-00009"], reason=""))


def test_retirement_is_non_destructive_and_excludes_the_kc(pkg) -> None:
    retired_pkg(pkg)
    result = pkg.run()
    assert result.ok and result.retired == {"KC-MAT-00002"}
    assert result.kcs["KC-MAT-00002"].review_status == "approved"  # lifecycle != review status
    assert "KC-MAT-00002" in pkg.inputs.kc_csv.read_text()  # nothing deleted
    coverage = result.graph.coverage
    assert coverage["subjects"]["mathematics"]["retired_kcs"] == ["KC-MAT-00002"]
    excluded = coverage["released_class_coverage"]["mathematics"]["excluded"]
    assert excluded["retired"] == ["KC-MAT-00002"]


def test_an_approved_edge_on_a_retired_kc_blocks_release(pkg) -> None:
    result = pkg.run()
    # Bypass the entry checks to simulate a hand-edited lifecycle log.
    raw = {**retire_entry(), "kc_row_digest": "x", "recorded_at": "t"}
    sealed = seal(raw, [], "LC-")
    (pkg.review_dir / c.LIFECYCLE_LOG.name).write_text(json.dumps(sealed) + "\n")
    found = pkg.codes("error")
    assert {"EDGE_TOUCHES_RETIRED_KC", "LIFECYCLE_STALE", "LIFECYCLE_EDGE_UNRESOLVED"} <= found
    assert result.ok


def test_editing_a_retired_kc_makes_the_retirement_stale(pkg) -> None:
    retired_pkg(pkg)
    pkg.edit_kc("KC-MAT-00002", name="Add unlike fractions")
    assert "LIFECYCLE_STALE" in pkg.codes("error")


def test_release_writes_a_verified_snapshot_once(pkg) -> None:
    snapshot = released(retired_pkg(pkg))
    assert [k["kc_id"] for k in snapshot["kcs"]] == ["KC-MAT-00001", "KC-MAT-00004"]
    assert snapshot["retired_kcs"][0]["kc_id"] == "KC-MAT-00002"
    assert [f"{e['prerequisite_kc_id']}->{e['dependent_kc_id']}" for e in snapshot["edges"]] == [
        "KC-MAT-00004->KC-MAT-00001"
    ]
    assert snapshot["kc_content"]["KC-MAT-00001"]["description"].startswith("Identify")
    assert verify_snapshot(snapshot, lifecycle_events(pkg)) == []
    graph = load_released_graph(snapshot, lifecycle_events(pkg))
    assert graph.prerequisites("KC-MAT-00001") == ["KC-MAT-00004"]
    assert graph.roots() == ["KC-MAT-00004"]  # a foundation KC as a prerequisite root
    assert graph.layers() == [["KC-MAT-00004"], ["KC-MAT-00001"]]
    assert (pkg.root / "final/release_manifest_1.json").exists()
    released(pkg)  # a second release is a new sequence number, never an overwrite
    assert (pkg.root / "final/released_graph_2.json").exists()


def _redigest(snapshot: dict) -> dict:
    snapshot["snapshot_sha256"] = snapshot_digest(snapshot)
    return snapshot


def test_every_fail_closed_case(pkg) -> None:
    snapshot = released(retired_pkg(pkg))
    events = lifecycle_events(pkg)

    def check(changes: dict, code: str, lc=events) -> None:
        bad = _redigest({**json.loads(json.dumps(snapshot)), **changes})
        assert code in {p.code for p in verify_snapshot(bad, lc)}, code
        assert load_released_graph(bad, lc) is None

    tampered = json.loads(json.dumps(snapshot))
    tampered["kcs"][0]["name"] = "tampered"
    assert [p.code for p in verify_snapshot(tampered, events)] == ["SNAPSHOT_DIGEST_MISMATCH"]
    assert load_released_graph(tampered, events) is None
    retired = snapshot["retired_kcs"][0]
    check({"lifecycle_log_head": "0" * 64}, "SNAPSHOT_LIFECYCLE_MISMATCH")
    check({"retired_kcs": [{**retired, "lifecycle_event_id": "LC-0009"}]}, "LIFECYCLE_MISSING")
    check({"retired_kcs": [{**retired, "kc_row_digest": "f" * 64}]}, "LIFECYCLE_STALE")
    check({"retired_kcs": []}, "SNAPSHOT_LIFECYCLE_MISMATCH")
    kc2 = {**snapshot["kcs"][0], "kc_id": "KC-MAT-00002", "stable_key": "mathematics.fractions.x"}
    check({"kcs": [*snapshot["kcs"], kc2]}, "RETIRED_KC_IN_PATH")
    back = {
        **snapshot["edges"][0],
        "prerequisite_kc_id": "KC-MAT-00001",
        "dependent_kc_id": "KC-MAT-00004",
    }
    check({"edges": [*snapshot["edges"], back]}, "CYCLE")
    check(
        {"kcs": [{**snapshot["kcs"][0], "review_status": "needs_review"}, snapshot["kcs"][1]]},
        "EDGE_ENDPOINT_KC_NOT_APPROVED",
    )
    broken = [dict(events[0], reason="edited")]
    assert "LOG_CHAIN_BROKEN" in {p.code for p in verify_snapshot(snapshot, broken)}


def test_release_is_refused_while_any_gate_is_open(pkg) -> None:
    with pytest.raises(release.ReleaseRefused, match="SYNTHETIC_DATA"):
        release.release(pkg.run(), pkg.root / "final")
    pkg.edit_edge(E12, dependency_basis="chapter_order")
    with pytest.raises(release.ReleaseRefused, match="validation errors"):
        release.release(pkg.run(), pkg.root / "final", allow_synthetic_output=True)
    pkg.edit_edge(E12, dependency_basis="uses_concept")
    pkg.inputs.vocabulary = None
    with pytest.raises(release.ReleaseRefused, match="VOCABULARY_NOT_CONFIRMED"):
        release.release(pkg.run(), pkg.root / "final", allow_synthetic_output=True)
    assert not (pkg.root / "final").exists()


def test_coverage_keeps_foundation_and_declared_versus_mapped_apart(pkg) -> None:
    result = pkg.run()
    cov = result.graph.coverage
    maths = cov["released_class_coverage"]["mathematics"]
    assert maths["foundation_kcs"] == 1 and maths["counted_kcs"] == 2
    assert maths["classes"]["7"] == {
        "declared_kcs": 2,
        "mapped_kcs": None,
        "declared_not_mapped": None,
    }
    assert maths["classes_without_coverage"] == ["8", "9", "10"]
    assert maths["excluded"]["not_approved"] == ["KC-MAT-00003"]
    assert cov["foundation"] == {
        "count": 1,
        "kc_ids": ["KC-MAT-00004"],
        "roots": ["KC-MAT-00004"],
        "edges_into_target": ["KC-MAT-00004->KC-MAT-00001"],
    }
    assert "KC-MAT-00004" not in cov["subjects"]["mathematics"]["kcs_without_class_mapping"]
    pkg.inputs.curriculum_classes = {"KC-MAT-00001": (6,), "KC-MAT-00002": (7,)}
    result = validate.run(pkg.inputs)
    mapped = result.graph.coverage["released_class_coverage"]["mathematics"]["classes"]["7"]
    assert mapped == {"declared_kcs": 2, "mapped_kcs": 1, "declared_not_mapped": 1}
    assert [f.record for f in result.findings if f.code == "CLASS_MAPPING_MISMATCH"] == [
        "KC-MAT-00001"
    ]
