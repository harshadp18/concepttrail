"""Rights gate, metadata enrichment rules and source-URL verification (no network)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from data_pipeline import authorization as auth
from data_pipeline import enrich_metadata as enrich
from data_pipeline import verify_source_urls as urls

DOC = {
    "source_id": "SRC-C06-MAT-FEGP1-01",
    "inventory_id": "CT-C06-MAT-001",
    "sha256": "a" * 64,
    "class_level": "6",
    "subject_id": "mathematics",
    "chapter_title": "Patterns in Mathematics",
    "academic_session": "2026-27",
    "acquired_at": "",
}


# --- authorisation ---------------------------------------------------------------------------


@pytest.fixture
def record() -> dict:
    return auth.owner_local_processing_record([DOC, {**DOC, "source_id": "S2", "sha256": "b" * 64}])


def test_owner_record_scope_and_audit_fields(record: dict) -> None:
    assert record["authorization_basis"] == "owner_attestation"
    assert record["scope"] == "local_hackathon_processing"
    assert set(record["uses"]) == set(auth.LOCAL_USES)
    assert "model_training_or_fine_tuning" in record["not_covered"]
    assert record["inventory_field_overlay"]["permitted_training"]["note"] == "stays not_permitted"
    assert record["evidence_reference_status"].startswith("owner_statement_only")
    assert record["document_count"] == 2


def test_gate_permits_only_covered_local_uses(record: dict) -> None:
    ok = auth.check_use(DOC["source_id"], DOC["sha256"], "local_pdf_extraction", [record])
    assert ok.permitted and ok.record_id == auth.OWNER_LOCAL_RECORD_ID
    for use in auth.EXTERNAL_OR_RESTRICTED_USES:
        assert not auth.check_use(DOC["source_id"], DOC["sha256"], use, [record]).permitted
    assert not auth.check_use("UNKNOWN", "c" * 64, "local_ocr", [record]).permitted
    assert not auth.check_use(DOC["source_id"], DOC["sha256"], "made_up_use", [record]).permitted


def test_gate_binds_to_exact_bytes(record: dict) -> None:
    changed = auth.check_use(DOC["source_id"], "f" * 64, "local_pdf_extraction", [record])
    assert not changed.permitted and "bytes differ" in changed.reason


def test_records_are_write_once(record: dict, tmp_path: Path) -> None:
    path = auth.write_record(record, tmp_path)
    assert auth.write_record(record, tmp_path) == path  # identical content: no-op
    with pytest.raises(RuntimeError, match="immutable"):
        auth.write_record({**record, "scope": "everything"}, tmp_path)
    assert auth.load_records(tmp_path)[0]["scope"] == "local_hackathon_processing"


# --- topics and objectives -------------------------------------------------------------------


def hierarchy(*topics: str) -> list[dict]:
    entries = [
        {
            "kind": "chapter",
            "title": "Patterns in Mathematics",
            "number": None,
            "pdf_page_index": 0,
            "printed_page_label": "1",
            "method": "m",
            "confidence": "medium",
        }
    ]
    entries += [
        {
            "kind": "topic",
            "title": t,
            "number": f"1.{i}",
            "pdf_page_index": i,
            "printed_page_label": str(i + 1),
            "method": "numbered_heading",
            "confidence": "medium",
        }
        for i, t in enumerate(topics, 1)
    ]
    return entries


def test_topic_provenance_and_proposals() -> None:
    topics = enrich.topic_records(DOC, hierarchy("1.1 Number Patterns"), "norm.json")
    assert {t["kind"] for t in topics} == {"chapter", "topic"}
    assert all(
        t["pdf_page_index"] is not None and t["evidence_reference"] == "norm.json" for t in topics
    )
    single = enrich.propose_topic_title(topics, False, "norm.json")
    assert (single["value"], single["value_status"]) == ("1.1 Number Patterns", "source_explicit")
    multi = enrich.propose_topic_title(
        enrich.topic_records(DOC, hierarchy("1.1 A", "1.2 B"), "n"), False, "n"
    )
    assert multi["value"] is None and multi["value_status"] == "requires_human_review"
    assert "2 topics" in multi["reason"]  # never joins unrelated titles into one value
    assert enrich.propose_topic_title([], False, "n")["value_status"] == "not_found"
    assert enrich.propose_topic_title(topics, True, "n")["value_status"] == "not_yet_extracted"


def test_objective_origins_are_classified() -> None:
    topics = enrich.topic_records(
        DOC, hierarchy("1.1 Number Patterns", "1.2 Visualising Sequences"), "n"
    )
    derived = enrich.derived_objectives(DOC, topics, "n")
    assert len(derived) == 2 and {o["value_origin"] for o in derived} == {
        "source_derived_candidate"
    }
    assert "Number Patterns" in derived[0]["objective"] and derived[0]["pdf_page_index"] == 1
    assert derived[0]["confidence"] == "low"
    assert enrich.derived_objectives({**DOC, "subject_id": "english"}, topics, "n") == []

    proposal = enrich.propose_objective(derived, False, "mathematics")
    assert proposal["value"] is None  # candidates never fill the inventory field
    assert proposal["value_status"] == "source_derived_candidate"

    opening = normalized_page(0, ("prose", "In this chapter, we will study number patterns."))
    explicit = enrich.explicit_objectives(DOC, {"pages": [opening]}, "n")
    assert enrich.propose_objective(explicit + derived, False, "mathematics")["value_status"] == (
        "source_explicit"
    )


def normalized_page(index: int, *paragraphs: tuple[str, str], unusable: bool = False) -> dict:
    """The shape written by clean_text.normalize_document (kind/bbox/text per paragraph)."""
    paras = [
        {"kind": kind, "bbox": [0, i * 20, 500, i * 20 + 18], "text": text}
        for i, (kind, text) in enumerate(paragraphs)
    ]
    return {
        "page_index": index,
        "page_label": {
            "value": str(index + 1),
            "method": "pdf_page_label_rules",
            "confidence": "high",
        },
        "paragraphs": paras,
        "text": "\n\n".join(t for _, t in paragraphs),
        "text_unusable": unusable,
    }


def objectives_of(*pages: dict) -> list[tuple[str, int]]:
    found = enrich.explicit_objectives(DOC, {"pages": list(pages)}, "norm.json")
    assert all(o["value_origin"] == "textbook_explicit" for o in found)
    return [(o["objective"], o["pdf_page_index"]) for o in found]


def test_opening_marker_sentence_is_recognised() -> None:
    page = normalized_page(
        0,
        (
            "prose",
            "Earlier we met shapes. In this chapter, we will study algebraic identities."
            " They are useful.",
        ),
    )
    assert objectives_of(page) == [("In this chapter, we will study algebraic identities.", 0)]


def test_only_list_items_after_the_marker_are_captured() -> None:
    page = normalized_page(
        1,
        ("preserved_layout", "In this chapter, you will learn to:"),
        ("preserved_layout", "(i) identify number patterns"),
        ("preserved_layout", "(ii) extend a sequence by its rule"),
        ("prose", "Patterns are everywhere around us and this paragraph explains why."),
        ("preserved_layout", "(iii) a later list that belongs to an exercise"),
    )
    opening = normalized_page(0, ("prose", "A chapter epigraph that states no objective."))
    assert objectives_of(opening, page) == [
        ("In this chapter, you will learn to:", 1),
        ("(i) identify number patterns", 1),
        ("(ii) extend a sequence by its rule", 1),
    ]


def test_ordinary_paragraph_after_the_marker_is_ignored() -> None:
    page = normalized_page(
        0,
        ("prose", "In this chapter, we will explore polynomials."),
        ("prose", "A polynomial is an expression built from variables and coefficients."),
        ("table_region", "x | 1 | 2"),
    )
    assert objectives_of(page) == [("In this chapter, we will explore polynomials.", 0)]


def test_mid_chapter_you_will_learn_is_ignored() -> None:
    pages = [
        normalized_page(0, ("prose", "The chapter opens with a story about a market.")),
        normalized_page(1, ("prose", "Traders exchanged goods across long distances.")),
        normalized_page(
            7,
            ("prose", "You will learn more about this in higher classes."),
            ("preserved_layout", "(i) an item that must not be captured"),
        ),
    ]
    assert objectives_of(*pages) == []


def test_unusable_pages_do_not_count_as_opening_pages() -> None:
    pages = [
        normalized_page(0, ("unusable_legacy_encoding", "dqN ugha"), unusable=True),
        normalized_page(1, ("prose", "")),  # no text at all
        normalized_page(2, ("prose", "In this chapter, we will read a one-act play.")),
        normalized_page(3, ("prose", "Plain narrative.")),
        normalized_page(4, ("prose", "In this chapter, we will also read poems.")),
    ]
    # Opening pages are the first two pages with usable text: indexes 2 and 3.
    assert objectives_of(*pages) == [("In this chapter, we will read a one-act play.", 2)]


def test_official_objectives_require_matching_scope() -> None:
    catalogue = [
        {
            "class_level": "6",
            "subject_id": "mathematics",
            "academic_session": "2026-27",
            "chapter_match": "patterns",
            "objective": "Official outcome text",
            "source_url": "https://example.org/lo.pdf",
            "source_title": "LO doc",
            "source_page": 4,
        }
    ]
    found = enrich.official_objectives(DOC, catalogue)
    assert (
        found[0]["value_origin"] == "official_source"
        and "example.org" in found[0]["evidence_reference"]
    )
    assert enrich.official_objectives({**DOC, "class_level": "7"}, catalogue) == []
    assert enrich.official_objectives({**DOC, "academic_session": "2025-26"}, catalogue) == []
    proposal = enrich.propose_objective(found, False, "mathematics")
    assert proposal["value_status"] == "verified" and proposal["value"] == "Official outcome text"


def test_language_chapter_without_objectives_needs_teachers() -> None:
    result = enrich.propose_objective([], False, "english")
    assert result["value_status"] == "requires_human_review" and "teacher" in result["reason"]


# --- acquisition date ---------------------------------------------------------------------------


def fake_xattr(stdout: str, rc: int = 0):
    return lambda cmd: subprocess.CompletedProcess(cmd, rc, stdout=stdout, stderr="")


def test_unknown_acquisition_date_is_explicit(tmp_path: Path) -> None:
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    result = enrich.acquisition_evidence(
        DOC,
        pdf,
        [tmp_path],
        {"creation_date": "D:2025", "modification_date": ""},
        run=fake_xattr("0087;6ae4ec90;ExampleChatApp;"),
    )
    assert result["value"] is None
    assert (result["acquisition_date_status"], result["reason"], result["review_status"]) == (
        "unknown",
        "acquisition_evidence_unavailable",
        "needs_evidence",
    )
    considered = {e["type"]: e for e in result["evidence_considered"]}
    transfer = considered["macos_quarantine_transfer"]
    assert transfer["found"]["agent"] == "ExampleChatApp" and transfer["accepted"] is False
    assert considered["pdf_creation_or_modification_date"]["accepted"] is False
    assert considered["file_modification_time"]["accepted"] is False


def test_inventory_date_and_possible_records(tmp_path: Path) -> None:
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert (
        enrich.acquisition_evidence({**DOC, "acquired_at": "2026-04-01"}, pdf, [], {})["value"]
        == "2026-04-01"
    )
    (tmp_path / "download_log.txt").write_text("2026-03-02 fetched x.pdf from publisher")
    found = enrich.acquisition_evidence(DOC, pdf, [tmp_path], {}, run=fake_xattr("", 1))
    assert found["acquisition_date_status"] == "requires_human_review" and found["value"] is None


# --- source URLs --------------------------------------------------------------------------------

INDEX_HTML = (
    b'document.test.tbook.options[1].text="Ganita Prakash";\n'
    b'document.test.tbook.options[1].value="textbook.php?fegp1=0-10"\n'
    b'if(ss==1)  {  omyFrame.src = "../textbook/pdf/" + name+ "01.pdf";    }'
)
PDF_BYTES = b"%PDF-1.7 synthetic"


def fake_fetch(responses: dict[str, tuple[int, bytes | None]]):
    def get(url: str):
        status, body = responses.get(url, (404, None))
        return status, body, "application/pdf", None if status == 200 else f"HTTP {status}"

    return get


SELECTION = {
    "selected": [
        {
            "status": "selected",
            "source_id": DOC["source_id"],
            "inventory_id": DOC["inventory_id"],
            "local_path": "class 6/maths/fegp101.pdf",
            "sha256": hashlib.sha256(PDF_BYTES).hexdigest(),
        }
    ]
}


def test_url_verified_only_on_exact_byte_match() -> None:
    get = fake_fetch(
        {urls.NCERT_INDEX: (200, INDEX_HTML), urls.NCERT_PDF_BASE + "fegp101.pdf": (200, PDF_BYTES)}
    )
    result = urls.run(SELECTION, get, today="2026-10-31")["results"][0]
    assert result["url_value_status"] == "verified" and result["confidence"] == "high"
    assert result["url"] == "https://ncert.nic.in/textbook/pdf/fegp101.pdf"
    assert result["source_title"] == "Ganita Prakash"
    assert result["book_page_url"] == "https://ncert.nic.in/textbook.php?fegp1=0-10"


def test_url_with_different_bytes_or_failures_stays_unresolved() -> None:
    other = fake_fetch(
        {
            urls.NCERT_INDEX: (200, INDEX_HTML),
            urls.NCERT_PDF_BASE + "fegp101.pdf": (200, b"%PDF other"),
        }
    )
    differs = urls.run(SELECTION, other, today="d")["results"][0]
    assert differs["url"] is None and differs["url_value_status"] == "requires_human_review"
    missing = urls.run(SELECTION, fake_fetch({urls.NCERT_INDEX: (200, INDEX_HTML)}), today="d")[
        "results"
    ][0]
    assert missing["url"] is None and missing["url_value_status"] == "unknown"
    offline = urls.run(SELECTION, fake_fetch({}), today="d")["results"][0]
    assert offline["reason"] == "official_index_unreachable"
    no_rule = fake_fetch({urls.NCERT_INDEX: (200, b"<html>no rule</html>")})
    assert urls.run(SELECTION, no_rule, today="d")["results"][0]["url_value_status"] == "not_found"


def test_url_proposal_from_evidence() -> None:
    evidence = {
        "results": [
            {
                "source_id": DOC["source_id"],
                "url": "https://x/y.pdf",
                "url_value_status": "verified",
                "review_status": "verified_automatically",
                "reason": "exact_byte_match",
                "confidence": "high",
            }
        ]
    }
    assert enrich.propose_url(DOC, evidence)["value"] == "https://x/y.pdf"
    assert enrich.propose_url(DOC, None)["value_status"] == "unknown"
    assert json.dumps(enrich.propose_url({**DOC, "source_id": "other"}, evidence))


# --- official outcome catalogue -----------------------------------------------------------------


def test_official_outcomes_are_parsed_verbatim_per_chapter() -> None:
    from data_pipeline.official_outcomes import parse_outcomes

    pages = [
        "Chapter I -The First Topic\nLearning outcome- The students will be able to\n"
        "⮚ Infer how one event shaped a\nsecond development.\n⮚ Compare two ideas.\n",
        "Chapter 3-. The Third Topic\nSubtopic 1. Something\n"
        "Inter disciplinary Project with chapter 7 of Geography: X and\n"
        "chapter 4 of Economics: Y\nRefer Annexure\n"
        "Learning outcome- The students will be able to\n⮚ Explain the third idea.\n"
        "Interdisciplinary project note that is not an outcome\n",
    ]
    parsed = parse_outcomes(pages)
    assert [(p["chapter_title"], p["outcome"], p["pdf_page_index"]) for p in parsed] == [
        ("The First Topic", "Infer how one event shaped a second development.", 0),
        ("The First Topic", "Compare two ideas.", 0),
        ("The Third Topic", "Explain the third idea.", 1),  # cross-reference is not a chapter
    ]


def test_low_confidence_single_heading_never_fills_topic_title() -> None:
    entries = hierarchy()
    entries.append(
        {
            "kind": "topic",
            "title": "An Author Name",
            "number": None,
            "pdf_page_index": 0,
            "printed_page_label": "1",
            "method": "larger_font_heading",
            "confidence": "low",
        }
    )
    proposal = enrich.propose_topic_title(enrich.topic_records(DOC, entries, "n"), False, "n")
    assert proposal["value"] is None and proposal["value_status"] == "requires_human_review"
    assert "low-confidence" in proposal["reason"]


def test_heading_candidates_are_not_topics_and_feed_no_objectives() -> None:
    entries = hierarchy("1.1 Number Patterns")
    entries.append(
        {
            "kind": "heading_candidate",
            "title": "How did people trade long ago?",
            "number": None,
            "pdf_page_index": 2,
            "printed_page_label": "3",
            "method": "larger_font_heading",
            "confidence": "low",
        }
    )
    topics = enrich.topic_records(DOC, entries, "n")
    candidate = next(t for t in topics if t["kind"] == "heading_candidate")
    assert candidate["value_status"] == "requires_human_review"
    proposal = enrich.propose_topic_title(topics, False, "n")
    assert proposal["topic_count"] == 1 and proposal["value"] == "1.1 Number Patterns"
    derived = enrich.derived_objectives(DOC, topics, "n")
    assert [o["supporting_heading"] for o in derived] == ["1.1 Number Patterns"]


def test_display_title_drops_unmapped_glyph_codes_but_keeps_verbatim() -> None:
    entries = hierarchy("4.3 \x07Factorisation Using Identities")
    topic = next(t for t in enrich.topic_records(DOC, entries, "n") if t["kind"] == "topic")
    assert topic["title"] == "4.3 \x07Factorisation Using Identities"  # verbatim kept
    assert topic["display_title"] == "4.3 Factorisation Using Identities"
    assert topic["contains_control_characters"] is True
    proposal = enrich.propose_topic_title([topic], False, "n")
    assert proposal["value"] == "4.3 Factorisation Using Identities"
    derived = enrich.derived_objectives(DOC, [topic], "n")
    assert "\x07" not in derived[0]["objective"]


def test_ocr_paragraphs_are_read_only_for_unusable_pages_and_marked_low() -> None:
    legacy = normalized_page(0, ("unusable_legacy_encoding", "dqN ugha"), unusable=True)
    legacy["ocr"] = {
        "status": "completed",
        "paragraphs": ["In this chapter, we will read a one-act play."],
    }
    weak = normalized_page(1, ("unusable_legacy_encoding", "xyz"), unusable=True)
    weak["ocr"] = {"status": "minimal_text", "paragraphs": ["In this chapter, we will skip."]}
    found = enrich.explicit_objectives(DOC, {"pages": [legacy, weak]}, "norm.json")
    assert [(o["objective"], o["confidence"], o["extraction_method"]) for o in found] == [
        ("In this chapter, we will read a one-act play.", "low", "ocr")
    ]
    native = normalized_page(0, ("prose", "In this chapter, we will explore polynomials."))
    native["ocr"] = {"status": "completed", "paragraphs": ["In this chapter, OCR differs."]}
    found = enrich.explicit_objectives(DOC, {"pages": [native]}, "norm.json")
    assert [o["extraction_method"] for o in found] == ["native_text"]  # OCR never overrides


def test_chapter_title_check_via_ocr() -> None:
    from data_pipeline.stages.structure_content import chapter_title_check_ocr

    assert chapter_title_check_ocr("Kartoos", None)["status"] == "cannot_compare_text_unusable"
    hit = chapter_title_check_ocr("Kartoos (Habib Tanvir)", "14 kartoos\nhabib tanvir ...")
    assert hit["status"] == "consistent_via_ocr" and hit["similarity"] == 1.0
    near = chapter_title_check_ocr("Kartoos", "14 Kartos page text")
    assert near["status"] == "consistent_via_ocr" and near["similarity"] < 1.0
    miss = chapter_title_check_ocr("Kartoos", "an unrelated page about rivers")
    assert miss["status"] == "conflict_requires_review_via_ocr"


def test_explicit_objective_must_be_self_contained() -> None:
    def explicit(*texts: str) -> list[dict]:
        return [{"objective": t, "value_origin": "textbook_explicit"} for t in texts]

    lone = enrich.propose_objective(
        explicit("In this chapter, we will try to answer these questions."), False, "mathematics"
    )
    assert lone["value"] is None
    assert lone["value_status"] == "requires_human_review"
    assert "not self-contained" in lone["reason"]

    with_items = enrich.propose_objective(
        explicit("In this chapter, you will learn the following:", "(i) identify patterns"),
        False,
        "mathematics",
    )
    assert with_items["value_status"] == "source_explicit"
    assert with_items["value"].endswith("(i) identify patterns")

    plain = enrich.propose_objective(
        explicit("In this chapter, we will explore algebraic identities."), False, "mathematics"
    )
    assert plain["value"] == "In this chapter, we will explore algebraic identities."


def test_project_use_record_grants_listed_uses_only(record: dict) -> None:
    project = auth.owner_project_use_record([DOC])
    sid, digest = DOC["source_id"], DOC["sha256"]
    for use in auth.PROJECT_USES + auth.LOCAL_USES:
        decision = auth.check_use(sid, digest, use, [project])
        assert decision.permitted and decision.record_id == auth.OWNER_PROJECT_RECORD_ID
    # The local record alone never grants project uses.
    for use in auth.PROJECT_USES:
        assert not auth.check_use(sid, digest, use, [record]).permitted
    for use in ("external_embedding", "external_gemini_processing", "third_party_ocr"):
        assert not auth.check_use(sid, digest, use, [record, project]).permitted
    overlay = project["inventory_field_overlay"]
    assert overlay["permitted_training"]["overlay_value"] is None
    assert overlay["rights_status"]["overlay_value"] == "approved"
    assert "model_training_or_fine_tuning" in project["not_covered"]
    assert project["nature"].endswith("not independent legal verification.")


def test_training_and_redistribution_are_refused_even_if_listed() -> None:
    rogue = auth.owner_project_use_record([DOC])
    rogue["uses"]["model_training_or_fine_tuning"] = "permitted"
    rogue["uses"]["redistribution"] = "permitted"
    for use in auth.SEPARATE_AUTHORIZATION_ONLY:
        decision = auth.check_use(DOC["source_id"], DOC["sha256"], use, [rogue])
        assert not decision.permitted and "dedicated" in decision.reason


GENERATED = {
    DOC["source_id"]: {
        "meta": {
            "record_id": "LO-AI-test",
            "generation_method": "ai_assisted_authoring",
            "generator": "test model",
            "review_status": "pending_teacher_review",
        },
        "chapter": {
            "inventory_id": DOC["inventory_id"],
            "source_id": DOC["source_id"],
            "language": "en",
            "objectives": [
                {"text": "Identify number patterns.", "evidence_terms": ["number patterns"]},
                {"text": "Explain magic squares.", "evidence_terms": ["magic squares"]},
            ],
        },
    }
}


def test_generated_objectives_are_grounded_per_page_and_labelled() -> None:
    pages = [
        normalized_page(0, ("prose", "We look at number\npatterns here.")),
        normalized_page(1, ("prose", "More number patterns.")),
    ]
    found = enrich.ai_generated_objectives(DOC, {"pages": pages}, GENERATED, "n.json")
    first, second = found
    assert first["grounding"] == "grounded" and first["pdf_page_index"] == "0 1"
    assert (
        first["value_origin"] == "ai_generated"
        and first["review_status"] == "pending_teacher_review"
    )
    assert first["objective_id"] == "CT-C06-MAT-001-AI-LO01"
    assert second["grounding"] == "rejected_ungrounded"  # term not in the chapter
    assert (
        enrich.ai_generated_objectives(
            {**DOC, "source_id": "other"}, {"pages": pages}, GENERATED, "n"
        )
        == []
    )


def test_generated_objectives_fill_only_when_no_stated_objective_exists() -> None:
    generated = [
        {
            "objective": "Identify number patterns.",
            "value_origin": "ai_generated",
            "grounding": "grounded",
        },
        {
            "objective": "Unsupported.",
            "value_origin": "ai_generated",
            "grounding": "rejected_ungrounded",
        },
    ]
    only_ai = enrich.propose_objective(generated, False, "mathematics")
    assert only_ai["value"] == "Identify number patterns."  # rejected one is never used
    assert only_ai["value_status"] == "ai_generated"
    assert only_ai["review_status"] == "pending_teacher_review"
    stated = [
        {
            "objective": "In this chapter, we will explore patterns.",
            "value_origin": "textbook_explicit",
        }
    ]
    keep = enrich.propose_objective(stated + generated, False, "mathematics")
    assert keep["value_status"] == "source_explicit"  # textbook statement takes precedence
    lone = [
        {"objective": "We will try to answer these questions.", "value_origin": "textbook_explicit"}
    ]
    replaced = enrich.propose_objective(lone + generated, False, "mathematics")
    assert replaced["value_status"] == "ai_generated"  # not self-contained -> generated used
    assert replaced["counts_by_origin"]["ai_generated"] == 2


def test_generated_objectives_must_match_inventory_id() -> None:
    wrong = {
        DOC["source_id"]: {
            **GENERATED[DOC["source_id"]],
            "chapter": {**GENERATED[DOC["source_id"]]["chapter"], "inventory_id": "X"},
        }
    }
    with pytest.raises(ValueError, match="another inventory_id"):
        enrich.ai_generated_objectives(DOC, {"pages": []}, wrong, "n")
