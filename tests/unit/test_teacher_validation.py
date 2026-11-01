"""Owner-attested teacher validation: completion is recorded apart from approval (D-054)."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from data_pipeline import enrich_metadata as enrich
from data_pipeline import teacher_validation as tv

ROOT = Path(__file__).resolve().parents[2]
REAL_ATTESTATION = tv.ATTESTATION_PATH
REAL_GENERATION = tv.GENERATION_PATH
D050 = ROOT / "data_pipeline/data/overrides/authorizations/AUTH-2026-10-31-owner-project-use.json"
D050_SHA256 = "f13e8b696f881e3a055a1f2735f7b628ce5b4f3a36bb40b5b9dabad6adf338f9"
GENERATION_SHA256 = "7b6de7f1c9c3ecdef68720da11392c1bbd72ca762ce3ae9ea84299618e39acb6"
needs_private = pytest.mark.skipif(
    not (REAL_ATTESTATION.exists() and REAL_GENERATION.exists() and D050.exists()),
    reason="private owner records (gitignored) are not present in this checkout",
)


def generation(sizes: tuple[int, ...] = (6, 6, 6, 6, 6, 6, 5, 5, 5)) -> dict:
    chapters = []
    for n, size in enumerate(sizes, 1):
        chapters.append(
            {
                "inventory_id": f"CT-C09-MAT-{n:03d}",
                "source_id": f"SRC-C09-MAT-TEST{n}-01",
                "language": "en",
                "objectives": [
                    {"text": f"Explain idea {n}.{k}.", "evidence_terms": [f"term {n}.{k}"]}
                    for k in range(1, size + 1)
                ],
            }
        )
    return {"record_id": "LO-TEST", "review_status": "pending_teacher_review", "chapters": chapters}


def topic_rows(source_id: str = "SRC-C09-MAT-TEST1-01", inventory_id: str = "CT-C09-MAT-001"):
    def row(kind: str, number: str, title: str) -> dict:
        return {
            "source_document_id": source_id,
            "inventory_id": inventory_id,
            "kind": kind,
            "number": number,
            "title": title,
            "review_status": "requires_human_review",
            "review_completion": None,
        }

    return [
        row("chapter", "", "A Chapter"),
        row("topic", "1.1", "1.1 First"),
        row("subtopic", "1.1.1", "1.1.1 Sub"),
        row("heading_candidate", "", "Big Print"),
    ]


@pytest.fixture
def attestation() -> dict:
    return tv.build_attestation(generation(), topic_rows(), "a" * 64)


# --- the attestation records completion, never approval -------------------------------------


def test_attestation_confirms_completion_but_not_approval(attestation: dict) -> None:
    gen = generation()
    state = tv.objective_validation(attestation, gen["chapters"][0], "CT-C09-MAT-001-AI-LO01")
    assert state["review_completion"] == tv.REVIEW_COMPLETED
    assert state["approval_outcome"] == tv.NOT_RECORDED
    assert state["review_status"] == "teacher_reviewed_outcome_not_recorded"
    assert "approved" not in state["review_status"]
    assert attestation["individual_outcomes"] == []
    assert "teacher identities" in attestation["not_held_by_the_project"]
    assert attestation["scope"]["ai_generated_objectives"][
        "generation_record_status_preserved"
    ] == ("pending_teacher_review")


def test_no_attestation_leaves_everything_pending() -> None:
    gen = generation()
    state = tv.objective_validation({}, gen["chapters"][0], "CT-C09-MAT-001-AI-LO01")
    assert state["review_status"] == tv.PENDING_STATUS
    assert state["review_completion"] == tv.REVIEW_PENDING
    assert tv.topic_validation({}, "SRC-C09-MAT-TEST1-01", topic_rows()) is None


def test_exactly_51_objectives_in_9_chapters_are_required() -> None:
    assert len(tv.validate_generation(generation())) == 51
    for sizes in ((6,) * 9, (6, 6, 6, 6, 6, 6, 5, 5, 5, 1), (6, 6, 6, 6, 6, 6, 6, 6)):
        with pytest.raises(ValueError, match="expected"):
            tv.validate_generation(generation(sizes))


# --- bindings: identity, ids, text and evidence ----------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["objectives"][0].update(text="Explain something else."),
        lambda c: c["objectives"][0].update(evidence_terms=["another term"]),
        lambda c: c["objectives"].reverse(),
        lambda c: c["objectives"].pop(),
        lambda c: c.update(source_id="SRC-C09-MAT-OTHER-01"),
    ],
)
def test_changes_to_a_chapter_invalidate_its_objective_attestation(attestation, mutate) -> None:
    changed = copy.deepcopy(generation())
    chapter = changed["chapters"][0]
    mutate(chapter)
    state = tv.objective_validation(attestation, chapter, "CT-C09-MAT-001-AI-LO01")
    assert state["review_status"] == tv.PENDING_STATUS
    # Other chapters are unaffected.
    other = tv.objective_validation(
        attestation, generation()["chapters"][1], "CT-C09-MAT-002-AI-LO01"
    )
    assert other["review_completion"] == tv.REVIEW_COMPLETED


def test_objective_id_changes_invalidate_the_digest(attestation: dict) -> None:
    gen = generation()
    original = tv.objectives_digest(gen["chapters"][0])
    renamed = copy.deepcopy(gen["chapters"][0])
    renamed["inventory_id"] = "CT-C09-MAT-099"  # every objective ID derives from this
    assert tv.objectives_digest(renamed) != original
    state = tv.objective_validation(attestation, renamed, "CT-C09-MAT-099-AI-LO01")
    assert state["review_status"] == tv.PENDING_STATUS
    # An ID the attestation never listed is not covered even for an unchanged chapter.
    unknown = tv.objective_validation(attestation, gen["chapters"][0], "CT-C09-MAT-001-AI-LO99")
    assert unknown["review_status"] == tv.PENDING_STATUS


def test_duplicate_objective_ids_are_rejected() -> None:
    gen = generation()
    gen["chapters"][1]["inventory_id"] = gen["chapters"][0]["inventory_id"]
    with pytest.raises(ValueError, match="duplicate"):
        tv.validate_generation(gen)
    forged = tv.build_attestation(generation(), topic_rows(), "a" * 64)
    ids = forged["scope"]["ai_generated_objectives"]["objective_ids"]
    ids[1] = ids[0]
    with pytest.raises(ValueError, match="duplicated or miscounted"):
        tv.validate_attestation(forged)


# --- individual outcomes ------------------------------------------------------------------


def with_outcomes(attestation: dict, *entries: dict) -> dict:
    record = copy.deepcopy(attestation)
    record["individual_outcomes"] = list(entries)
    return record


def test_unknown_outcome_is_rejected(attestation: dict) -> None:
    bad = with_outcomes(attestation, {"objective_id": "CT-C09-MAT-001-AI-LO01", "outcome": "great"})
    with pytest.raises(ValueError, match="unknown outcome"):
        tv.validate_attestation(bad)


def test_outcome_for_unknown_objective_is_rejected(attestation: dict) -> None:
    bad = with_outcomes(attestation, {"objective_id": "CT-X-AI-LO01", "outcome": "approved"})
    with pytest.raises(ValueError, match="unknown objective"):
        tv.validate_attestation(bad)


def test_duplicate_outcomes_are_rejected(attestation: dict) -> None:
    entry = {"objective_id": "CT-C09-MAT-001-AI-LO01", "outcome": "approved"}
    with pytest.raises(ValueError, match="duplicate outcome"):
        tv.validate_attestation(with_outcomes(attestation, entry, dict(entry)))


@pytest.mark.parametrize("extra", ["teacher_name", "comment", "score"])
def test_outcome_entries_cannot_carry_invented_teacher_data(attestation: dict, extra: str) -> None:
    entry = {"objective_id": "CT-C09-MAT-001-AI-LO01", "outcome": "approved", extra: "x"}
    with pytest.raises(ValueError, match="hold only"):
        tv.validate_attestation(with_outcomes(attestation, entry))


def test_recorded_individual_outcomes_are_preserved_and_distinguished(attestation: dict) -> None:
    record = with_outcomes(
        attestation,
        {"objective_id": "CT-C09-MAT-001-AI-LO01", "outcome": "approved"},
        {"objective_id": "CT-C09-MAT-001-AI-LO02", "outcome": "rejected"},
        {"objective_id": "CT-C09-MAT-001-AI-LO03", "outcome": "revision_required"},
    )
    tv.validate_attestation(record)
    chapter = generation()["chapters"][0]
    got = {
        n: tv.objective_validation(record, chapter, f"CT-C09-MAT-001-AI-LO0{n}")
        for n in range(1, 5)
    }
    assert [got[n]["review_status"] for n in range(1, 5)] == [
        "teacher_approved",
        "teacher_rejected",
        "teacher_revision_required",
        "teacher_reviewed_outcome_not_recorded",
    ]
    assert all(g["review_completion"] == tv.REVIEW_COMPLETED for g in got.values())
    assert tv.aggregate(list(got.values()))["review_status"] == tv.MIXED_STATUS


def test_rejected_and_revision_required_objectives_are_not_written(attestation: dict) -> None:
    record = with_outcomes(
        attestation,
        {"objective_id": "CT-C09-MAT-001-AI-LO02", "outcome": "rejected"},
        {"objective_id": "CT-C09-MAT-001-AI-LO03", "outcome": "revision_required"},
    )
    doc = {
        "source_id": "SRC-C09-MAT-TEST1-01",
        "inventory_id": "CT-C09-MAT-001",
        "academic_session": "2026-27",
    }
    text = " ".join(f"term 1.{k}" for k in range(1, 7))
    pages = {"pages": [{"page_index": 0, "text": text, "text_unusable": False}]}
    meta = {
        "record_id": "LO-TEST",
        "generation_method": "m",
        "generator": "g",
        "review_status": "pending_teacher_review",
    }
    chapter = generation()["chapters"][0]
    generated = {doc["source_id"]: {"meta": meta, "chapter": chapter}}
    objectives = enrich.ai_generated_objectives(doc, pages, generated, "n.json", record)
    proposal = enrich.propose_objective(objectives, False, "mathematics")
    assert proposal["value"].count(" | ") == 3  # 4 of 6 written
    assert "idea 1.2." not in proposal["value"] and "idea 1.3." not in proposal["value"]
    assert proposal["review_status"] == tv.MIXED_STATUS


# --- enrichment keeps provenance and the AI label ---------------------------------------------


def test_enrichment_reconciles_status_but_keeps_provenance(attestation: dict) -> None:
    doc = {
        "source_id": "SRC-C09-MAT-TEST1-01",
        "inventory_id": "CT-C09-MAT-001",
        "academic_session": "2026-27",
    }
    chapter = generation()["chapters"][0]
    meta = {
        "record_id": "LO-TEST",
        "generation_method": "ai_assisted_authoring",
        "generator": "test model",
        "review_status": "pending_teacher_review",
    }
    text = " ".join(f"term 1.{k}" for k in range(1, 7))
    pages = {"pages": [{"page_index": 0, "text": text, "text_unusable": False}]}
    generated = {doc["source_id"]: {"meta": meta, "chapter": chapter}}
    done = enrich.ai_generated_objectives(doc, pages, generated, "n.json", attestation)
    before = enrich.ai_generated_objectives(doc, pages, generated, "n.json", None)
    assert [o["objective"] for o in done] == [o["objective"] for o in before]
    assert [o["objective_id"] for o in done] == [o["objective_id"] for o in before]
    for o in done:
        assert o["value_origin"] == "ai_generated"
        assert o["review_status_at_generation"] == "pending_teacher_review"
        assert o["review_status"] == "teacher_reviewed_outcome_not_recorded"
        assert o["generator"] == "test model" and o["grounding"] == "grounded"
    assert {o["review_status"] for o in before} == {"pending_teacher_review"}
    proposal = enrich.propose_objective(done, False, "mathematics")
    assert proposal["value_status"] == "ai_generated"  # still labelled AI-generated
    assert proposal["review_status"] == "teacher_reviewed_outcome_not_recorded"
    assert proposal["approval_outcome"] == tv.NOT_RECORDED
    assert "not_individually_recorded" in proposal["reason"]


# --- topics ---------------------------------------------------------------------------------


def test_topic_validation_covers_only_numbered_topic_rows(attestation: dict) -> None:
    rows = enrich.apply_topic_validation(topic_rows(), attestation)
    by_kind = {r["kind"]: r for r in rows}
    for kind in ("topic", "subtopic"):
        assert by_kind[kind]["review_completion"] == tv.REVIEW_COMPLETED
        assert by_kind[kind]["approval_outcome"] == tv.NOT_RECORDED
        assert by_kind[kind]["review_status"] == "teacher_reviewed_outcome_not_recorded"
    for kind in ("chapter", "heading_candidate"):  # never approved without evidence
        assert by_kind[kind]["review_completion"] is None
        assert by_kind[kind]["review_status"] == "requires_human_review"


def test_topic_list_change_invalidates_topic_coverage(attestation: dict) -> None:
    for mutate in (
        lambda rows: rows[1].update(title="1.1 Renamed"),
        lambda rows: rows[1].update(number="1.2"),
        lambda rows: rows.append({**rows[1], "number": "1.2", "title": "1.2 Extra"}),
        lambda rows: [r.update(inventory_id="CT-C09-MAT-099") for r in rows],
    ):
        rows = topic_rows()
        mutate(rows)
        assert tv.topic_validation(attestation, "SRC-C09-MAT-TEST1-01", rows) is None
    # Heading candidates and chapter rows are not part of the covered list.
    rows = topic_rows()
    rows[3]["title"] = "Different big print"
    assert tv.topic_validation(attestation, "SRC-C09-MAT-TEST1-01", rows) is not None


def test_chapter_without_a_topic_list_gets_nothing(attestation: dict) -> None:
    only_heading = [r for r in topic_rows() if r["kind"] in ("chapter", "heading_candidate")]
    assert tv.topic_list_digest("SRC-C09-MAT-TEST1-01", only_heading) is None
    assert tv.topic_validation(attestation, "SRC-C09-MAT-TEST1-01", only_heading) is None
    proposal = enrich.propose_topic_title(
        enrich.apply_topic_validation(only_heading, attestation), False, "n.json"
    )
    assert proposal["value_status"] == "not_found"
    assert proposal["review_status"] == "requires_human_review"


# --- write-once, deterministic -------------------------------------------------------------


def test_attestation_is_write_once_deterministic_and_not_rewritten(tmp_path: Path) -> None:
    record = tv.build_attestation(generation(), topic_rows(), "a" * 64)
    assert record == tv.build_attestation(generation(), topic_rows(), "a" * 64)
    path = tmp_path / "attestation.json"
    assert tv.write_once(path, record) == (path, True)
    first = path.stat().st_mtime_ns
    assert tv.write_once(path, copy.deepcopy(record)) == (path, False)
    assert path.stat().st_mtime_ns == first  # identical content: no rewrite
    altered = copy.deepcopy(record)
    altered["statement"] = "Something else."
    with pytest.raises(RuntimeError, match="immutable"):
        tv.write_once(path, altered)
    assert json.loads(path.read_text("utf-8")) == record
    assert tv.load_attestation(path)["record_id"] == tv.RECORD_ID


def test_malformed_attestation_is_refused(attestation: dict) -> None:
    for key, value in (
        ("review_completion", "approved"),
        ("default_approval_outcome", "approved"),
        ("record_id", "OTHER"),
    ):
        bad = copy.deepcopy(attestation)
        bad[key] = value
        with pytest.raises(ValueError):
            tv.validate_attestation(bad)


# --- the real private records ---------------------------------------------------------------


@needs_private
def test_real_attestation_binds_the_real_generation_record() -> None:
    record = tv.load_attestation()
    gen = json.loads(REAL_GENERATION.read_text("utf-8"))
    scope = record["scope"]["ai_generated_objectives"]
    assert scope["objective_count"] == 51 and scope["chapter_count"] == 9
    assert scope["objective_ids"] == tv.validate_generation(gen)
    assert scope["objectives_digest_by_source_id"] == {
        c["source_id"]: tv.objectives_digest(c) for c in gen["chapters"]
    }
    assert (
        scope["generation_record_sha256"]
        == hashlib.sha256(REAL_GENERATION.read_bytes()).hexdigest()
    )
    assert scope["generation_record_sha256"] == GENERATION_SHA256  # original, unedited
    assert gen["review_status"] == "pending_teacher_review"  # history is not falsified
    assert record["individual_outcomes"] == []
    assert record["authorization_basis"] == "owner_attestation"
    assert record["recorded_on"] == "2026-10-31"


@needs_private
def test_d050_is_unchanged() -> None:
    assert hashlib.sha256(D050.read_bytes()).hexdigest() == D050_SHA256


# --- a missing private attestation is reported, never assumed ------------------------------


def _record(reconciled: bool, topics: bool = False) -> dict:
    state = tv.REVIEW_COMPLETED if reconciled else tv.REVIEW_PENDING
    return {
        "objectives": [
            {"value_origin": "ai_generated", "grounding": "grounded", "review_completion": state},
            {"value_origin": "ai_generated", "grounding": "rejected_ungrounded"},
            {"value_origin": "textbook_explicit"},
        ],
        "topics": [
            {"kind": "topic", "review_completion": tv.REVIEW_COMPLETED if topics else None},
            {"kind": "heading_candidate", "review_completion": None},
        ],
    }


def test_missing_attestation_is_reported_as_absent_not_applied() -> None:
    from data_pipeline.run_extraction_pilot import teacher_validation_summary as summary

    absent = summary([_record(False)], attestation_present=False)
    assert absent["status"] == "attestation_absent"
    assert (absent["ai_generated_objectives"], absent["objectives_reconciled"]) == (1, 0)
    stale = summary([_record(False)], attestation_present=True)
    assert stale["status"] == "attestation_does_not_bind"  # present but text changed
    applied = summary([_record(True, topics=True)], attestation_present=True)
    assert applied["status"] == "applied"
    assert (applied["topic_rows"], applied["topic_rows_reconciled"]) == (1, 1)
    none = summary([{"objectives": [], "topics": []}], attestation_present=False)
    assert none["status"] == "not_applicable"
