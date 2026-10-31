"""Baseline review-queue triage: every item gets exactly one rule-based disposition."""

from __future__ import annotations

from data_pipeline import triage_review_queue as triage


def record(sid: str, **overrides) -> dict:
    base = {
        "source_document_id": sid,
        "topic_value_status": "not_found",
        "objective_value_status": "requires_human_review",
        "acquisition_date_status": "unknown",
        "chapter_title_check": "consistent",
        "topic_count": 0,
        "objective_counts_by_origin": {"textbook_explicit": 0, "source_derived_candidate": 0},
        "reasons": {
            "topic_title": "no topic-level heading detected",
            "learning_objective": "language chapter; needs teacher-authored objectives",
            "acquired_at": "acquisition_evidence_unavailable",
        },
    }
    base.update(overrides)
    return base


def item(sid: str, name: str, pages: str = "") -> dict:
    return {"priority": "high", "item": name, "source_document_id": sid, "pdf_page_indexes": pages}


def q(sid: str, name: str, reason: str = "r") -> dict:
    return {
        "priority": "m",
        "item": name,
        "source_document_id": sid,
        "pdf_page_indexes": "",
        "reason": reason,
    }


def test_dispositions_follow_current_evidence() -> None:
    baseline = [
        item("A", "ocr_required", "1 2"),
        item("B", "ocr_required", "3"),
        item("C", "ocr_required", "4"),
        item("A", "page_review", "1"),
        item("A", "topic_title:requires_human_review"),
        item("B", "topic_title:requires_human_review"),
        item("A", "learning_objective:source_explicit"),
        item("B", "learning_objective:requires_human_review"),
        item("A", "acquired_at:unknown"),
        item("C", "chapter_title_check"),
    ]
    records = [
        record("A", topic_count=8, objective_counts_by_origin={"textbook_explicit": 1}),
        record("B"),
        record("C", chapter_title_check="consistent_via_ocr"),
    ]
    queue = [
        q("A", "ocr_quality_review"),
        q("B", "ocr_low_confidence_or_empty", "weak {'minimal_text': 1}"),
        q("C", "ocr_required", "not run"),
    ]
    result = triage.triage(baseline, records, queue)
    got = [(r[1], r[2], r[4]) for r in result["rows"]]
    assert got == [
        ("ocr_required", "A", "resolved"),
        ("ocr_required", "B", "open"),  # OCR ran but weak: still needs a human
        ("ocr_required", "C", "open"),  # OCR never ran
        ("page_review", "A", "open"),
        ("topic_title:requires_human_review", "A", "resolved"),  # one row per PDF rule
        ("topic_title:requires_human_review", "B", "open"),
        ("learning_objective:source_explicit", "A", "open"),
        ("learning_objective:requires_human_review", "B", "owner_decision"),
        ("acquired_at:unknown", "A", "owner_decision"),
        ("chapter_title_check", "C", "resolved"),
    ]
    assert result["rows"][0][6] == "ocr_quality_review"  # follow-up recorded
    assert sum(result["summary"]["dispositions"].values()) == len(baseline)
    # The two OCR follow-ups are new kinds of item for A and B; C's item is not new.
    assert result["summary"]["new_items_by_kind"] == {
        "ocr_quality_review": 1,
        "ocr_low_confidence_or_empty": 1,
    }


def test_unknown_item_is_never_silently_resolved() -> None:
    result = triage.triage([item("A", "something_else")], [record("A")], [])
    assert result["rows"][0][4] == "open"


def test_baseline_is_hash_pinned() -> None:
    assert len(triage.BASELINE_SHA256) == 64
    assert triage.BASELINE.name == "human_review_queue.baseline_2026-10-31.csv"


def test_owner_decisions_change_only_what_they_decide() -> None:
    baseline = [
        item("A", "acquired_at:unknown"),
        item("A", "learning_objective:requires_human_review"),
        item("A", "page_review", "1"),
    ]
    records = [record("A", objective_value_status="ai_generated")]
    owner = {"acquired_at": {"status": "accept_unknown"}}
    rows = triage.triage(baseline, records, [], owner)["rows"]
    assert [r[4] for r in rows] == ["resolved", "open", "open"]
    assert "D-052" in rows[0][5] and "pending teacher review" in rows[1][5]
    # Without the owner decision the acquisition date stays an owner decision.
    assert triage.triage(baseline, records, [])["rows"][0][4] == "owner_decision"
