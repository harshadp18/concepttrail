"""OCR adapter (mocked Tesseract), normalisation, structure detection and quality metrics."""

from __future__ import annotations

import subprocess

import pymupdf
import pytest
from conftest import SYNTHETIC_PROSE

from data_pipeline.stages import ocr_pages
from data_pipeline.stages.classify_pages import classify_page
from data_pipeline.stages.clean_text import header_footer_patterns, join_prose, normalize_document
from data_pipeline.stages.extract_pdf import extract_document
from data_pipeline.stages.structure_content import build_hierarchy, chapter_title_check
from data_pipeline.stages.validate_content import document_quality


def completed(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def fake_runner(langs: list[str], tsv: str = "", ocr_rc: int = 0):
    def run(cmd: list[str]):
        if "--version" in cmd:
            return completed("tesseract 5.4.1\n leptonica")
        if "--list-langs" in cmd:
            return completed("List of available languages (2):\n" + "\n".join(langs) + "\n")
        return completed(tsv, ocr_rc, "engine error" if ocr_rc else "")

    return run


TSV_HEADER = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
)


def tsv(*words: tuple[str, float]) -> str:
    rows = [TSV_HEADER] + [
        f"5\t1\t1\t1\t1\t{i}\t0\t0\t10\t10\t{conf}\t{w}" for i, (w, conf) in enumerate(words, 1)
    ]
    return "\n".join(rows)


@pytest.fixture
def blank_page():
    doc = pymupdf.open()
    page = doc.new_page()
    yield page
    doc.close()


# --- OCR ------------------------------------------------------------------------------------


def test_tesseract_unavailable_is_reported() -> None:
    availability = ocr_pages.detect_tesseract(which=lambda _: None)
    assert not availability.available
    assert availability.as_dict()["hindi_available"] is False


def test_detects_version_and_languages() -> None:
    availability = ocr_pages.detect_tesseract(
        which=lambda _: "/usr/bin/tesseract", run=fake_runner(["eng", "hin", "osd"])
    )
    assert availability.version == "tesseract 5.4.1"
    assert availability.as_dict()["english_available"] and availability.as_dict()["hindi_available"]


def test_ocr_unavailable_and_disabled(blank_page) -> None:
    missing = ocr_pages.OcrAvailability(None, None, error="not found")
    assert ocr_pages.ocr_page(blank_page, "latin", missing, enabled=True, dpi=72)["status"] == (
        "unavailable"
    )
    present = ocr_pages.OcrAvailability("/t", "tesseract 5", ["eng"])
    assert ocr_pages.ocr_page(blank_page, "latin", present, enabled=False, dpi=72)["status"] == (
        "disabled"
    )


def test_hindi_never_falls_back_to_english_ocr(blank_page) -> None:
    english_only = ocr_pages.OcrAvailability("/t", "tesseract 5", ["eng"])
    result = ocr_pages.ocr_page(blank_page, "devanagari", english_only, enabled=True, dpi=72)
    assert result["status"] == "language_unavailable"
    assert "hin" in result["reason"] and result["text"] is None
    assert ocr_pages.select_languages("devanagari", ["eng", "hin"]) == ("hin+eng", "ok")
    assert ocr_pages.select_languages("devanagari", ["hin"]) == ("hin", "ok")


def test_ocr_success_low_confidence_and_failure(blank_page) -> None:
    env = ocr_pages.OcrAvailability("/t", "tesseract 5", ["eng"])
    good = ocr_pages.ocr_page(
        blank_page,
        "latin",
        env,
        enabled=True,
        dpi=72,
        run=fake_runner(
            [], tsv(("Hello", 96), ("world", 90), ("this", 92), ("is", 94), ("text", 93))
        ),
    )
    assert (good["status"], good["text"], good["mean_confidence"]) == (
        "completed",
        "Hello world this is text",
        93.0,
    )
    assert good["uncertain_words"] == 0 and good["config"]["psm"] == 3
    few = ocr_pages.ocr_page(
        blank_page, "latin", env, enabled=True, dpi=72, run=fake_runner([], tsv(("Map", 95)))
    )
    assert few["status"] == "minimal_text"  # a picture page with a stray label
    empty = ocr_pages.ocr_page(
        blank_page, "latin", env, enabled=True, dpi=72, run=fake_runner([], tsv())
    )
    assert empty["status"] == "no_text_found" and empty["word_count"] == 0
    weak = ocr_pages.ocr_page(
        blank_page,
        "latin",
        env,
        enabled=True,
        dpi=72,
        run=fake_runner([], tsv(*[(w, 40) for w in ("Hel1o", "wor1d", "th1s", "1s", "b4d")])),
    )
    assert weak["status"] == "low_confidence" and weak["uncertain_words"] == 5
    failed = ocr_pages.ocr_page(
        blank_page, "latin", env, enabled=True, dpi=72, run=fake_runner([], "", 1)
    )
    assert failed["status"] == "failed" and failed["text"] is None


def test_native_vs_ocr_comparison() -> None:
    assert ocr_pages.compare_native_and_ocr("abc def", None) is None
    assert ocr_pages.compare_native_and_ocr("abc def", "abc def")["similarity"] == 1.0


# --- normalisation ---------------------------------------------------------------------------


def _raw(pdfs, specs, script="latin"):
    _, pages = extract_document(pdfs.build("n.pdf", specs))
    for page in pages:
        page["classification"] = classify_page(page, script)
        page["ocr"] = {"status": "not_required"}
    return {"pages": pages, "document": {"pdf_metadata": {"toc": []}}}


def test_header_footer_detection_and_paragraphs(pdfs) -> None:
    specs = [
        {
            "heading": "Repeated Running Head",
            "lines": [SYNTHETIC_PROSE[:90], SYNTHETIC_PROSE[90:]],
            "footer": str(n),
        }
        for n in range(5, 10)
    ]
    raw = _raw(pdfs, specs)
    assert "Repeated Running Head" in header_footer_patterns(raw["pages"])
    normalized = normalize_document(raw, "raw.json")
    page = normalized["pages"][0]
    assert "Repeated Running Head" in page["removed_header_footer_lines"]
    assert page["raw_ref"]["artifact"] == "raw.json" and page["raw_ref"]["page_index"] == 0
    assert any(p["kind"] == "prose" for p in page["paragraphs"])
    assert raw["pages"][0]["text"].count("\n") > page["text"].count("\n")  # raw untouched


def test_join_prose_keeps_every_character() -> None:
    assert join_prose(["self-", "control  and   care"]) == "self-control and care"


def test_math_blocks_and_hindi_are_preserved(pdfs) -> None:
    math = ["x + y = 7", "2x − y = 2", "√16 = 4"]
    raw = _raw(pdfs, [{"lines": math}])
    page = normalize_document(raw, "r")["pages"][0]
    assert all(line in page["text"] for line in math)
    assert page["paragraphs"][0]["kind"] == "preserved_layout"


def test_legacy_hindi_pages_are_flagged_unusable() -> None:
    page = {
        "page_index": 0,
        "text": "Hkkjr",
        "blocks": [{"type": "text", "bbox": [0, 0, 10, 10], "text": "Hkkjr esa"}],
        "classification": {
            "class": "low_quality_extraction",
            "needs_review": True,
            "quality_problems": ["legacy_devanagari_font_encoding"],
        },
    }
    out = normalize_document({"pages": [page]}, "r")["pages"][0]
    assert out["text_unusable"] and out["paragraphs"][0]["kind"] == "unusable_legacy_encoding"
    assert out["review_status"] == "needs_review"


# --- structure and quality ---------------------------------------------------------------------


def test_hierarchy_and_chapter_title_check(pdfs) -> None:
    specs = [
        {"heading": "Patterns in Numbers", "lines": [SYNTHETIC_PROSE]},
        {"lines": ["1.1 Counting Shapes", SYNTHETIC_PROSE, "1.1.1 Triangles", "Exercise 1.1"]},
    ]
    raw = _raw(pdfs, specs)
    hierarchy = build_hierarchy(raw, set())
    kinds = {(e["kind"], e["title"]) for e in hierarchy}
    assert ("chapter", "Patterns in Numbers") in kinds
    assert ("topic", "1.1 Counting Shapes") in kinds
    assert ("subtopic", "1.1.1 Triangles") in kinds
    assert all(e["pdf_page_index"] is not None for e in hierarchy)
    assert chapter_title_check("Patterns in Numbers", hierarchy, False)["status"] == "consistent"
    assert chapter_title_check("Light and Shadows", hierarchy, False)["status"] == (
        "conflict_requires_review"
    )
    assert chapter_title_check("x", hierarchy, True)["status"] == "cannot_compare_text_unusable"


def test_quality_metrics_by_subject(pdfs) -> None:
    raw = _raw(pdfs, [{"lines": ["x + y = 7", "θ = 30°"] * 3, "table": [["a", "b"], ["1", "2"]]}])
    normalized = normalize_document(raw, "r")
    metrics = document_quality(raw, normalized, "mathematics")
    assert metrics["pages"] == 1 and metrics["tables"] == 1
    assert metrics["equation_lines"] >= 3 and metrics["math_symbols"] >= 6
    assert {f["code"] for f in metrics["findings"]} >= {"TABLES_NEED_STRUCTURE_REVIEW"}


OPENINGS = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]


def test_header_footer_removal_never_touches_body_lines(pdfs) -> None:
    """A lone number inside the body survives even though lone numbers are the footers."""
    specs = []
    for n in range(5, 10):
        spec = {
            "lines": [f"{OPENINGS[n - 5]} opens this page.", "3", SYNTHETIC_PROSE],
            "footer": str(n),
        }
        if n == 5:
            spec["label_start"] = 5
        specs.append(spec)
    normalized = normalize_document(_raw(pdfs, specs), "r")
    for page in normalized["pages"]:
        assert page["removed_header_footer_lines"] == [page["page_label"]["value"]]
        assert " 3 " in f" {page['text']} "  # the digit-only body line is never deleted


def test_noise_outline_entry_falls_back_to_headings(pdfs) -> None:
    raw = _raw(pdfs, [{"heading": "Ideas and Markets", "lines": [SYNTHETIC_PROSE]}])
    raw["document"]["pdf_metadata"]["toc"] = [[1, "iest206", 0], [1, "Chapter 7 Map", 0]]
    chapter = next(e for e in build_hierarchy(raw, set()) if e["kind"] == "chapter")
    assert chapter["title"] == "Ideas and Markets"
    assert chapter["method"] == "largest_font_on_first_content_pages"
    raw["document"]["pdf_metadata"]["toc"] = [[1, "Ideas and Markets", 0]]
    assert build_hierarchy(raw, set())[0]["method"] == "pdf_outline"


def test_ocr_paragraphs_and_uncertain_words() -> None:
    rows = [
        TSV_HEADER,
        "5\t1\t1\t1\t1\t1\t0\t0\t9\t9\t95\tFirst",
        "5\t1\t1\t1\t1\t2\t0\t0\t9\t9\t40\tline",
        "5\t1\t2\t1\t1\t1\t0\t0\t9\t9\t90\tSecond",
    ]
    text, mean, words = ocr_pages.parse_tsv("\n".join(rows))
    assert text == "First line\n\nSecond" and words == 3  # blank line between paragraphs


def test_tesseract_runs_single_threaded(monkeypatch) -> None:
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs.get("env", {}))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ocr_pages.subprocess, "run", fake_run)
    ocr_pages._run(["tesseract", "--version"])
    assert seen["OMP_THREAD_LIMIT"] == "1"


def test_unapproved_language_is_not_used() -> None:
    assert ocr_pages.select_languages("devanagari", ["eng", "hin"], approved=["eng"])[0] is None
    assert ocr_pages.select_languages("latin", ["eng", "hin"], approved=["eng"]) == ("eng", "ok")


def test_prose_fragments_are_not_heading_candidates(pdfs) -> None:
    raw = _raw(pdfs, [{"lines": [SYNTHETIC_PROSE]}])
    page = raw["pages"][0]
    page["heading_candidates"] = [
        {"text": t, "size": 16, "signals": ["larger_font"], "number": None}
        for t in ("“Shh … Grandpa’ll", "hear", "you,”", "Reading for Meaning")
    ]
    kinds = {(e["kind"], e["title"]) for e in build_hierarchy(raw, set())}
    assert ("heading_candidate", "Reading for Meaning") in kinds
    assert not any(t in {"“Shh … Grandpa’ll", "hear", "you,”"} for _, t in kinds)


def test_numbered_lines_out_of_sequence_are_not_topics() -> None:
    from data_pipeline.stages.structure_content import demote_out_of_sequence

    def entry(number: str) -> dict:
        depth = number.count(".")
        return {
            "kind": "topic" if depth == 1 else "subtopic",
            "number": number,
            "title": f"{number} x",
            "confidence": "medium",
            "method": "numbered_heading",
        }

    numbers = ["1.1", "1.1.1", "1.2", "1.2.1", "1.7", "1.2.2", "1.3", "3.4"]
    entries = [entry(n) for n in numbers]
    demote_out_of_sequence(entries)
    demoted = [e["number"] for e in entries if e["kind"] == "heading_candidate"]
    assert demoted == ["1.7", "3.4"]  # sequence outlier; wrong chapter number
    assert all(
        e["method"] == "numbered_out_of_sequence"
        for e in entries
        if e["kind"] == "heading_candidate"
    )

    in_order = [entry(n) for n in ["2.1", "2.2", "2.3", "2.4"]]
    demote_out_of_sequence(in_order)
    assert all(e["kind"] == "topic" for e in in_order)
