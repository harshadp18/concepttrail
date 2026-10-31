"""Raw extraction and page classification on synthetic PDFs."""

from __future__ import annotations

import hashlib

import pymupdf
import pytest
from conftest import SYNTHETIC_PROSE, UNICODE_FONT

from data_pipeline.stages.classify_pages import OCR_CANDIDATES, classify_page
from data_pipeline.stages.extract_pdf import ExtractionError, extract_document, open_pdf

needs_unicode_font = pytest.mark.skipif(not UNICODE_FONT.exists(), reason="no Unicode font")


def test_valid_pdf_metadata_and_page_records(pdfs) -> None:
    path = pdfs.build("doc.pdf", [{"heading": "1.1 Patterns", "lines": [SYNTHETIC_PROSE]}] * 2)
    metadata, pages = extract_document(path)
    assert metadata["page_count"] == 2 and metadata["is_encrypted"] is False
    assert [p["page_index"] for p in pages] == [0, 1]  # zero-based, contiguous
    page = pages[0]
    assert page["extraction_method"] == "pymupdf_native_text"
    assert page["text_length"] > 40
    assert any(c["number"] == "1.1" for c in page["heading_candidates"])
    assert page["blocks"] and all(len(b["bbox"]) == 4 for b in page["blocks"])


def test_missing_pdf(tmp_path) -> None:
    with pytest.raises(ExtractionError) as exc:
        open_pdf(tmp_path / "absent.pdf")
    assert exc.value.code == "PDF_NOT_FOUND"


def test_corrupted_pdf(tmp_path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.7\n this is not a real pdf body")
    with pytest.raises(ExtractionError) as exc:
        open_pdf(bad)
    assert exc.value.code in {"PDF_OPEN_FAILED", "PDF_NO_PAGES"}


def test_encrypted_pdf(pdfs) -> None:
    path = pdfs.build(
        "locked.pdf",
        [{"lines": ["secret"]}],
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw="u-pass",
        owner_pw="o-pass",
    )
    with pytest.raises(ExtractionError) as exc:
        open_pdf(path)
    assert exc.value.code == "PDF_ENCRYPTED"


def test_original_pdf_is_never_modified(pdfs) -> None:
    path = pdfs.build("keep.pdf", [{"lines": [SYNTHETIC_PROSE]}])
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    extract_document(path)
    extract_document(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@needs_unicode_font
def test_hindi_text_is_preserved_exactly(pdfs) -> None:
    hindi = "हिंदी पाठ: बच्चों ने क़िताब पढ़ी। ज्ञान और श्रम"
    path = pdfs.build("hi.pdf", [{"lines": [hindi] * 4}])
    _, pages = extract_document(path)
    assert hindi in pages[0]["text"]
    stats = pages[0]["char_stats"]
    assert stats["devanagari"] > 0 and stats["virama"] > 0 and stats["danda"] >= 4
    assert classify_page(pages[0], "devanagari")["class"] == "text_native"


@needs_unicode_font
def test_math_symbols_and_script_positions(pdfs) -> None:
    spec = {
        "lines": ["√2 × π ≤ ∞, a ÷ b ≠ c, ½ + ¾, θ = 30°"] * 3,
        "spans": [
            (72, 300, "Area x", 12),
            (108, 295, "2", 7),
            (72, 340, "H", 12),
            (81, 343, "2", 7),
            (86, 340, "O", 12),
        ],
    }
    _, pages = extract_document(pdfs.build("math.pdf", [spec]))
    page = pages[0]
    assert "√2 × π ≤ ∞" in page["text"] and "½ + ¾" in page["text"]
    assert page["char_stats"]["math_symbols"] >= 6 and page["char_stats"]["greek"] >= 2
    assert page["superscript_spans"] >= 1 and page["subscript_like_spans"] >= 1
    # Plain text flattens script positions; the markup keeps them.
    assert "x 2" in page["text"] or "x2" in page["text"]
    assert "^{2}" in page["script_markup_text"] and "H_{2}O" in page["script_markup_text"]


def test_table_extraction_keeps_rows_and_columns(pdfs) -> None:
    rows = [["Year", "Value"], ["2001", "10"], ["2011", "12"]]
    _, pages = extract_document(pdfs.build("table.pdf", [{"lines": ["Data"], "table": rows}]))
    tables = pages[0]["tables"]
    assert tables["status"] == "completed"
    assert len(tables["tables"]) == 1
    table = tables["tables"][0]
    assert (table["row_count"], table["col_count"]) == (3, 2)
    assert [table["header"], *table["rows"][1:]] == rows or table["rows"] == rows


def test_figure_references_and_captions(pdfs) -> None:
    spec = {"lines": ["Fig. 2.1 A labelled diagram", SYNTHETIC_PROSE], "image_coverage": 0.25}
    _, pages = extract_document(pdfs.build("fig.pdf", [spec]))
    page = pages[0]
    assert page["images"] and page["images"][0]["bbox"] and page["images"][0]["xref"]
    assert 0.2 < page["image_coverage"] < 0.3
    assert page["caption_candidates"][0]["text"].startswith("Fig. 2.1")


def test_printed_page_labels(pdfs) -> None:
    with_rules = pdfs.build("labels.pdf", [{"lines": ["a"], "label_start": 17}, {"lines": ["b"]}])
    _, pages = extract_document(with_rules)
    assert [p["page_label"]["value"] for p in pages] == ["17", "18"]
    assert pages[0]["page_label"]["method"] == "pdf_page_label_rules"

    footer = pdfs.build("footer.pdf", [{"lines": [SYNTHETIC_PROSE], "footer": "42"}])
    _, pages = extract_document(footer)
    assert pages[0]["page_label"] == {
        "value": "42",
        "method": "margin_number_heuristic",
        "confidence": "medium",
    }


# --- classification -------------------------------------------------------------------------


def test_classification_of_page_kinds(pdfs) -> None:
    text_page = {"lines": [SYNTHETIC_PROSE] * 3}
    mixed_page = {"lines": [SYNTHETIC_PROSE] * 3, "image_coverage": 0.5}
    empty_page: dict = {}
    figure_page = {"image_coverage": 0.3}
    path = pdfs.build("kinds.pdf", [text_page, mixed_page, empty_page, figure_page])
    _, pages = extract_document(path)
    classes = [classify_page(p, "latin")["class"] for p in pages]
    assert classes == ["text_native", "mixed_text_image", "empty_or_non_text", "image_heavy"]

    _, scanned = extract_document(pdfs.scanned("scan.pdf"))
    result = classify_page(scanned[0], "latin")
    assert result["class"] == "scanned" and result["ocr_candidate"] is True
    assert "ocr_required:scanned" in result["review_reasons"]


def test_legacy_devanagari_encoding_is_low_quality() -> None:
    page = {
        "text_length": 500,
        "image_coverage": 0.0,
        "legacy_devanagari_font": True,
        "char_stats": {
            "non_whitespace": 500,
            "devanagari": 0,
            "latin": 480,
            "replacement": 0,
            "private_use": 0,
            "control": 0,
        },
        "tables": {"tables": []},
    }
    result = classify_page(page, "devanagari")
    assert result["class"] == "low_quality_extraction"
    assert result["quality_problems"] == ["legacy_devanagari_font_encoding"]
    assert result["ocr_candidate"] and "low_quality_extraction" in OCR_CANDIDATES
    assert classify_page(page, "latin")["class"] == "text_native"  # English text is fine


def test_replacement_and_private_use_glyphs_flag_low_quality() -> None:
    base = {"text_length": 200, "image_coverage": 0.0, "tables": {"tables": []}}
    stats = {
        "non_whitespace": 200,
        "devanagari": 0,
        "latin": 150,
        "replacement": 5,
        "private_use": 0,
        "control": 0,
    }
    assert classify_page({**base, "char_stats": stats}, "latin")["quality_problems"] == [
        "unmapped_glyph_codes"
    ]
    pua = {**stats, "replacement": 0, "private_use": 20}
    assert (
        "private_use_glyphs"
        in classify_page({**base, "char_stats": pua}, "latin")["quality_problems"]
    )


def test_failed_page_is_explicit() -> None:
    result = classify_page({"page_index": 3, "extraction_method": "failed"}, "latin")
    assert result["class"] == "extraction_failed" and result["needs_review"]


def test_single_unmapped_glyph_code_means_review_not_ocr() -> None:
    base = {"text_length": 900, "image_coverage": 0.0, "tables": {"tables": []}}
    one = {
        "non_whitespace": 900,
        "devanagari": 0,
        "latin": 800,
        "replacement": 0,
        "private_use": 0,
        "control": 1,
    }
    result = classify_page({**base, "char_stats": one}, "latin")
    assert result["class"] == "text_native" and not result["ocr_candidate"]
    assert "some_unmapped_glyph_codes" in result["review_reasons"] and result["needs_review"]
    many = {**one, "control": 50}
    assert classify_page({**base, "char_stats": many}, "latin")["quality_problems"] == [
        "unmapped_glyph_codes"
    ]


def test_table_detections_are_labelled_by_shape(pdfs) -> None:
    grid = [["Year", "Value"], ["2001", "10"], ["2011", "12"]]
    _, pages = extract_document(
        pdfs.build("g.pdf", [{"table": grid}, {"table": [["boxed", "note", "strip"]]}])
    )
    kinds = [t["kind"] for p in pages for t in p["tables"]["tables"]]
    assert kinds == ["data_grid", "box_or_frame"]


def test_layout_frames_do_not_trigger_table_review() -> None:
    stats = {
        "non_whitespace": 500,
        "devanagari": 0,
        "latin": 450,
        "replacement": 0,
        "private_use": 0,
        "control": 0,
    }
    page = {"text_length": 500, "image_coverage": 0.0, "char_stats": stats}
    frame = {**page, "tables": {"tables": [{"kind": "box_or_frame"}]}}
    grid = {**page, "tables": {"tables": [{"kind": "data_grid"}]}}
    assert classify_page(frame, "latin")["needs_review"] is False
    assert classify_page(grid, "latin")["review_reasons"] == ["table_structure_check"]


def test_wrapped_heading_lines_are_joined_and_big_prose_is_not_a_heading() -> None:
    from data_pipeline.stages.extract_pdf import heading_candidates

    def line(text: str, y: float, size: float = 14.0, block: int = 1, bold: bool = True) -> dict:
        return {
            "text": text,
            "size": size,
            "bold": bold,
            "bbox": [72, y, 400, y + size],
            "block_no": block,
            "superscript_spans": 0,
            "subscript_like_spans": 0,
            "markup": text,
            "chars": len(text),
        }

    lines = [
        line("4.3 Factorisation of Algebraic Expressions Using", 100),
        line("Algebraic Identities", 115),
        line("Body text at the normal size of the page body.", 160, size=10, block=2, bold=False),
    ]
    found = heading_candidates(lines, body_size=10)
    assert [c["text"] for c in found] == [
        "4.3 Factorisation of Algebraic Expressions Using Algebraic Identities"
    ]
    assert found[0]["number"] == "4.3" and found[0]["lines_joined"] == 2

    story = [
        line(
            f"Line {i} of a story printed in a large typeface for young readers",
            100 + 15 * i,
            block=5,
        )
        for i in range(4)
    ]
    assert heading_candidates(story, body_size=10) == []  # merged run is far too long


def test_layered_heading_fragments_are_reassembled() -> None:
    from data_pipeline.stages.extract_pdf import heading_candidates, merge_layered_fragments

    def frag(text: str, x0: float, x1: float) -> dict:
        return {
            "text": text,
            "size": 14.0,
            "bold": False,
            "bbox": [x0, 447, x1, 461],
            "block_no": 17,
            "superscript_spans": 0,
            "subscript_like_spans": 0,
            "markup": text,
            "chars": len(text),
        }

    # The fragment pattern PyMuPDF returns for a heading painted as stacked layers.
    lines = [frag("1.1 CHEMIC", 163, 240)] * 4 + [frag("1.1 CHEMICAL EQUA", 163, 302)]
    lines += [frag("AL EQUA", 241, 302)] * 3 + [frag("AL EQUATIONS", 241, 342)]
    lines += [frag("TIONS", 302, 342)] * 4
    merged = merge_layered_fragments(lines)
    assert [m["text"] for m in merged] == ["1.1 CHEMICAL EQUATIONS"]
    found = heading_candidates(lines, body_size=10.5)
    assert [(c["text"], c["number"]) for c in found] == [("1.1 CHEMICAL EQUATIONS", "1.1")]

    side_by_side = [frag("Left column", 50, 200), frag("Right column", 300, 450)]
    assert len(merge_layered_fragments(side_by_side)) == 2  # no overlap -> not merged


def test_numbered_heading_without_space() -> None:
    from data_pipeline.stages.extract_pdf import NUMBERED_HEADING

    assert NUMBERED_HEADING.match("2.1Introduction")["number"] == "2.1"
    assert NUMBERED_HEADING.match("4.4. More Identities")["number"] == "4.4"
    assert NUMBERED_HEADING.match("2.5cm long") is None  # a measurement, not a heading
