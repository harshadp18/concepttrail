"""M3: review events, hash chain, anchors, register and approval verification (synthetic).

Synthetic log: RR-0001 KC1 (RV-002), RR-0002 KC2 (RV-002), RR-0003 KC4 (RV-003),
RR-0004/5 edge KC1->KC2 (RV-002, RV-003), RR-0006/7 edge KC4->KC1 (RV-002, RV-003).
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from kc_graph_fixtures import pkg_fixture  # noqa: F401  (registers the `pkg` fixture)

from app.services.audit_chain import seal
from data_pipeline.kc_graph import contract as c
from data_pipeline.kc_graph import people, review_log

E12 = "KC-MAT-00001->KC-MAT-00002"
E41 = "KC-MAT-00004->KC-MAT-00001"
T12 = "src:SRC-C07-MAT-EXMP1-01@5:para2#a1b2c3d4e5f6"
T41 = "src:SRC-C07-MAT-EXMP1-01@3:para1#a1b2c3d4e5f6"


def reseal(pkg, mutate) -> None:
    """Rewrite the whole log as a consistent chain after `mutate(events)` (a forgery)."""
    events = pkg.events()
    mutate(events)
    out: list[dict] = []
    for e in events:
        out.append(seal({k: v for k, v in e.items() if k != "event_hash"}, out, "RR-"))
    pkg.write_log([json.dumps(e, sort_keys=True) for e in out])


def test_synthetic_log_verifies_and_every_approval_is_bound(pkg) -> None:
    result = pkg.run()
    assert result.ok
    assert result.approving_ids[E12] == ["RR-0004", "RR-0005"]
    edge = next(e for e in result.graph.released_edges if e.key == ("KC-MAT-00001", "KC-MAT-00002"))
    assert edge.evidence_refs == (T12, "rev:RR-0004", "rev:RR-0005")  # derived, not in the CSV
    assert "rev:" not in pkg.inputs.edge_csv.read_text()


# --- tampering ---------------------------------------------------------------------------


def test_interior_edit_is_detected(pkg) -> None:
    lines = pkg.log_lines()
    event = json.loads(lines[1])
    event["rationale"] = "changed after the fact"
    lines[1] = json.dumps(event, sort_keys=True)
    pkg.write_log(lines)
    assert "LOG_CHAIN_BROKEN" in pkg.codes()


def test_deleted_and_reordered_events_are_detected(pkg) -> None:
    lines = pkg.log_lines()
    pkg.write_log(lines[:2] + lines[3:])
    assert {"LOG_CHAIN_BROKEN", "LOG_ANCHOR_MISMATCH"} <= pkg.codes()
    pkg.write_log([lines[0], lines[2], lines[1], *lines[3:]])
    assert "LOG_CHAIN_BROKEN" in pkg.codes()


def test_truncation_is_invisible_to_the_chain_but_caught_by_anchors(pkg) -> None:
    pkg.write_log(pkg.log_lines()[:-1])
    found = pkg.codes()
    assert "LOG_CHAIN_BROKEN" not in found and "LOG_ANCHOR_MISMATCH" in found


def test_whole_log_forgery_is_caught_only_by_anchors(pkg) -> None:
    reseal(pkg, lambda events: events[0].update(rationale="forged"))
    found = pkg.codes()
    assert "LOG_CHAIN_BROKEN" not in found and "LOG_ANCHOR_MISMATCH" in found


def test_invalid_and_duplicate_event_ids(pkg) -> None:
    lines = pkg.log_lines()
    pkg.write_log([*lines, lines[-1]])
    assert "LOG_CHAIN_BROKEN" in pkg.codes()
    reseal(pkg, lambda events: None)  # restore a consistent log first
    lines = pkg.log_lines()
    event = json.loads(lines[0])
    event["event_id"] = "RR-1"
    lines[0] = json.dumps(event)
    pkg.write_log(lines)
    assert "LOG_CHAIN_BROKEN" in pkg.codes()


def test_unreadable_line_and_append_refuses_a_broken_log(pkg) -> None:
    pkg.write_log([*pkg.log_lines(), "{not json"])
    assert {"LOG_INVALID", "LOG_CHAIN_BROKEN"} <= pkg.codes()
    with pytest.raises(RuntimeError, match="does not verify"):
        pkg.review(**pkg.kc_entry("KC-MAT-00001", "RV-003"))


def test_anchor_custody_gates(pkg) -> None:
    anchor = pkg.custody[1] / "anchor-7.json"
    data = json.loads(anchor.read_text())
    anchor.unlink()
    assert any("LOG_ANCHOR_MISSING" in b for b in pkg.run().release_blockers)
    anchor.write_text(json.dumps({**data, "head_hash": "0" * 64}))
    assert "LOG_ANCHOR_MISMATCH" in pkg.codes()
    with pytest.raises(RuntimeError, match="immutable"):
        review_log.write_anchor([pkg.custody[1]], {**data, "recorded_at": "later"})


def test_custody_must_be_two_locations_outside_the_repository(pkg, tmp_path) -> None:
    path = pkg.review_dir / c.CUSTODY_FILE.name
    path.write_text(json.dumps({"locations": [{"label": "one", "path": str(tmp_path)}]}))
    assert review_log.load_custody(path)[0] is None
    path.write_text(
        json.dumps(
            {
                "locations": [
                    {"label": "a", "path": str(c.PROJECT_ROOT / "x")},
                    {"label": "b", "path": str(tmp_path)},
                ]
            }
        )
    )
    custody, why = review_log.load_custody(path)
    assert custody is None and "inside the repository" in why
    path.unlink()
    assert any("CUSTODY_NOT_CONFIGURED" in b for b in pkg.run().release_blockers)


# --- people ------------------------------------------------------------------------------


def test_reviewer_must_be_registered_qualified_and_not_the_author(pkg) -> None:
    with pytest.raises(ValueError, match="REVIEWER_UNKNOWN"):
        pkg.review(**pkg.kc_entry("KC-MAT-00001", "RV-099"))
    with pytest.raises(ValueError, match="REVIEWER_NOT_INDEPENDENT"):
        pkg.review(**pkg.kc_entry("KC-MAT-00001", "RV-001"))
    with pytest.raises(ValueError, match="fields the reviewer may not set"):
        pkg.review(**pkg.kc_entry("KC-MAT-00001", "RV-003"), approved_by_model=True)


def test_subject_qualification_and_register_changes(pkg) -> None:
    register = pkg.register()
    register["people"][2]["subjects"] = ["science"]  # RV-003
    (pkg.review_dir / "people.json").write_text(json.dumps(register))
    assert "REGISTER_NOT_VERIFIED" in pkg.codes("error")  # changed after verification
    record = people.build_verification(pkg.review_dir / "people.json", "SYNTHETIC", "2026-02-01")
    people.write_verification(pkg.review_dir, record)
    assert "REVIEWER_NOT_QUALIFIED" in pkg.codes("error")  # RV-003 approved maths records


def test_duplicate_register_codes_are_invalid(pkg) -> None:
    register = pkg.register()
    register["people"].append(dict(register["people"][1]))
    (pkg.review_dir / "people.json").write_text(json.dumps(register))
    assert "REGISTER_INVALID" in pkg.codes("error")


def test_synthetic_data_is_refused_in_a_real_run(pkg) -> None:
    pkg.inputs.allow_synthetic = False
    assert "SYNTHETIC_DATA" in pkg.codes("error")


# --- approvals ---------------------------------------------------------------------------


def test_second_review_is_required_and_must_be_a_different_person(pkg) -> None:
    pkg.edit_edge(E12, review_record_ids="RR-0004")
    assert "QUORUM_NOT_MET" in pkg.codes("error")
    pkg.edit_edge(E12, review_record_ids="RR-0004;RR-0005")
    pkg.review(**pkg.edge_entry(E12, T12, "RV-002", rationale="A second, separate text."))
    pkg.edit_edge(E12, review_record_ids="RR-0004;RR-0008")
    assert "REVIEWER_NOT_INDEPENDENT" in pkg.codes("error")


def test_cited_events_must_exist_and_match(pkg) -> None:
    pkg.edit_kc("KC-MAT-00001", review_record_ids="RR-0099")
    assert "REVIEW_RECORD_MISSING" in pkg.codes("error")
    pkg.edit_kc("KC-MAT-00001", review_record_ids="RR-0002")
    assert "REVIEW_MISMATCH" in pkg.codes("error")
    pkg.edit_kc("KC-MAT-00001", review_record_ids="RR-0001", review_status="rejected")
    assert "REVIEW_MISMATCH" in pkg.codes("error")


def test_model_drafted_row_cannot_self_approve(pkg) -> None:
    pkg.edit_kc("KC-MAT-00003", review_status="approved", review_record_ids="RR-0001")
    assert {"AI_FIELD_VIOLATION", "AI_SELF_APPROVAL"} <= pkg.codes("error")


def test_owner_attestation_basis_cannot_approve(pkg) -> None:
    reseal(pkg, lambda events: events[0].update(basis="owner_attestation"))
    assert "REVIEW_NOT_INDIVIDUAL" in pkg.codes("error")


def test_substantive_change_stales_and_needs_a_version_bump(pkg) -> None:
    pkg.edit_kc("KC-MAT-00001", learning_objective="Decide whether two fractions are equal.")
    found = pkg.codes("error")
    assert {"REVIEW_STALE", "VERSION_NOT_BUMPED"} <= found
    pkg.edit_kc("KC-MAT-00001", content_version="kc-v2")
    found = pkg.codes("error")
    assert "VERSION_NOT_BUMPED" not in found and "REVIEW_STALE" in found
    result = pkg.run()
    stale = {f.record for f in result.findings if f.code == "REVIEW_STALE"}
    assert {"KC-MAT-00001", E12, E41} <= stale  # endpoint version change stales both edges
    # Human re-review of the KC and reaffirmation of each edge, by two reviewers each.
    kc = pkg.review(**pkg.kc_entry("KC-MAT-00001", "RV-003"))
    pkg.edit_kc("KC-MAT-00001", review_record_ids=kc["event_id"])
    ids = {}
    for key, token in ((E12, T12), (E41, T41)):
        ids[key] = [
            pkg.review(
                **pkg.edge_entry(
                    key,
                    token,
                    r,
                    event_type="reaffirmation",
                    rationale=f"{r} reaffirms {key} for kc-v2.",
                )
            )["event_id"]
            for r in ("RV-002", "RV-003")
        ]
        pkg.edit_edge(key, review_record_ids=";".join(ids[key]))
    assert pkg.run().ok
    assert pkg.run().approving_ids[E12] == ids[E12]


def test_clerical_change_needs_a_documented_confirmation(pkg) -> None:
    pkg.edit_kc("KC-MAT-00001", name="Recognise equal fractions")
    assert "REVIEW_STALE" in pkg.codes("error")
    event = pkg.review(
        **pkg.kc_entry(
            "KC-MAT-00001",
            "RV-003",
            event_type="clerical_confirmation",
            clerical_class="clerical",
            rationale="Display name only.",
        )
    )
    pkg.edit_kc("KC-MAT-00001", review_record_ids=f"RR-0001;{event['event_id']}")
    assert pkg.run().ok


def test_clerical_event_cannot_cover_a_substantive_change(pkg) -> None:
    pkg.edit_kc("KC-MAT-00001", kc_type="fact")
    event = pkg.review(
        **pkg.kc_entry(
            "KC-MAT-00001",
            "RV-003",
            event_type="clerical_confirmation",
            clerical_class="clerical",
            rationale="Called it clerical.",
        )
    )
    pkg.edit_kc("KC-MAT-00001", review_record_ids=f"RR-0001;{event['event_id']}")
    assert "CLERICAL_EVENT_ON_SUBSTANTIVE_CHANGE" in pkg.codes("error")


def test_wording_only_reclassification_needs_two_reviewers(pkg) -> None:
    old = pkg.events()[0]["pedagogical_digest"]
    pkg.edit_kc(
        "KC-MAT-00001",
        learning_objective="Identify whether two fractions represent the same quantity",
    )  # punctuation only
    ids = []
    for reviewer in ("RV-003", "RV-004"):
        ids.append(
            pkg.review(
                **pkg.kc_entry(
                    "KC-MAT-00001",
                    reviewer,
                    event_type="clerical_confirmation",
                    clerical_class="wording_only",
                    old_pedagogical_digest=old,
                    rationale=f"{reviewer}: punctuation only; meaning unchanged.",
                )
            )["event_id"]
        )
        pkg.edit_kc("KC-MAT-00001", review_record_ids=";".join(["RR-0001", *ids]))
        assert pkg.run().ok is (len(ids) == 2)


def test_conflict_needs_adjudication_by_a_third_reviewer(pkg) -> None:
    rejection = pkg.review(
        **pkg.kc_entry("KC-MAT-00002", "RV-003", decision="rejected", rationale="Not atomic.")
    )
    assert "REVIEW_CONFLICT" in pkg.codes("error")
    adjudication = pkg.review(
        **pkg.kc_entry(
            "KC-MAT-00002",
            "RV-004",
            event_type="adjudication",
            supersedes=[rejection["event_id"]],
            rationale=f"Adjudicated {rejection['event_id']}: the skill is atomic.",
        )
    )
    pkg.edit_kc("KC-MAT-00002", review_record_ids=f"RR-0002;{adjudication['event_id']}")
    assert pkg.run().ok


def test_an_event_may_cite_only_earlier_events(pkg) -> None:
    event = pkg.review(**pkg.kc_entry("KC-MAT-00001", "RV-003", rationale="As in RR-0050."))
    pkg.edit_kc("KC-MAT-00001", review_record_ids=f"RR-0001;{event['event_id']}")
    assert "EVENT_CITES_FUTURE" in pkg.codes("error")


def test_evidence_must_support_the_dependency_and_stay_current(pkg) -> None:
    ids = [
        pkg.review(
            **pkg.edge_entry(
                E12,
                T12,
                r,
                rationale=f"{r} re-reviewed.",
                evidence_assessment=[
                    {"token": T12, "supports": False, "note": "only mentions both"}
                ],
            )
        )["event_id"]
        for r in ("RV-002", "RV-003")
    ]
    pkg.edit_edge(E12, review_record_ids=";".join(ids))
    assert "EVIDENCE_NOT_SUPPORTING" in pkg.codes("error")
    pkg.edit_edge(E12, review_record_ids="RR-0004;RR-0005")
    doc = pkg.inputs.sources.documents["SRC-C07-MAT-EXMP1-01"]
    pages = list(doc.pages)
    pages[5] = (False, ("x" * 64, "y" * 64, "z" * 64))  # the paragraph was re-extracted
    pkg.inputs.sources.documents[doc.source_id] = replace(doc, pages=tuple(pages))
    assert "EVIDENCE_STALE" in pkg.codes("error")


def test_expert_judgement_needs_individual_expert_rationales(pkg) -> None:
    pkg.edit_edge(E41, dependency_basis="expert_judgement")
    assert "REVIEW_STALE" in pkg.codes("error")  # basis is pedagogical content
    with pytest.raises(ValueError, match="RATIONALE_MISSING"):
        pkg.review(**pkg.edge_entry(E41, T41, "RV-002"))
    same = "Equal sharing is needed to judge equal quantities; not based on sequence."
    ids = [
        pkg.review(
            **pkg.edge_entry(E41, T41, r, expert_rationale=same, rationale=f"{r} expert review.")
        )["event_id"]
        for r in ("RV-002", "RV-003")
    ]
    pkg.edit_edge(E41, review_record_ids=";".join(ids))
    assert "RATIONALE_DUPLICATED" in pkg.codes("error")


def test_reviewer_who_authored_an_endpoint_is_warned(pkg) -> None:
    pkg.edit_kc("KC-MAT-00002", author_id="RV-002")
    found = {f.code: f.severity for f in pkg.run().findings}
    assert found.get("REVIEWER_AUTHORED_ENDPOINT") == "warning"


def test_missing_checklist_blocks_approval(pkg) -> None:
    with pytest.raises(ValueError, match="CHECKLIST_INCOMPLETE"):
        pkg.review(**pkg.kc_entry("KC-MAT-00001", "RV-003", checklist={"atomic_skill": True}))
