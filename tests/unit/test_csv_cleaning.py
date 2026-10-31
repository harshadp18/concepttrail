"""Cell cleaning: only outer whitespace and in-cell line endings change; the rest is reported."""

from __future__ import annotations

import unicodedata

import pytest

from data_pipeline.inventory_schema import CANONICAL_HEADER
from data_pipeline.stages.clean_csv import (
    NORMALIZE_LINE_ENDINGS,
    TRIM_OUTER_WHITESPACE,
    clean_row,
    clean_value,
    inspect_text,
)


def test_outer_whitespace_is_trimmed_and_logged() -> None:
    value, transforms = clean_value("chapter_title", "  Number Play \t")
    assert value == "Number Play"
    assert [t.rule for t in transforms] == [TRIM_OUTER_WHITESPACE]
    assert transforms[0].before_length == 15 and transforms[0].after_length == 11


def test_internal_spacing_and_capitalisation_are_preserved() -> None:
    value, transforms = clean_value("chapter_title", "The  BIG   idea of maths")
    assert value == "The  BIG   idea of maths"
    assert transforms == []


def test_whitespace_only_becomes_empty() -> None:
    value, transforms = clean_value("topic_title", "   ")
    assert value == ""
    assert [t.rule for t in transforms] == [TRIM_OUTER_WHITESPACE]


def test_line_endings_inside_cells_are_normalised() -> None:
    value, transforms = clean_value("notes", "line1\r\nline2\rline3")
    assert value == "line1\nline2\nline3"
    assert [t.rule for t in transforms] == [NORMALIZE_LINE_ENDINGS]


@pytest.mark.parametrize(
    "text",
    [
        "मल्हार: कक्षा 6 के लिए हिंदी की पाठ्यपुस्तक",
        "Ganita Prakash गणित प्रकाश — Grade 6",
        "√2 × π ≤ ∞, x² + y₁ = ½, ∠ABC = 90°",
        "क़ ख़ ग़",  # precomposed nukta letters (NFC would decompose them)
        "क़",  # decomposed form of the same letter
        "क्‍ष",  # zero-width joiner is meaningful in Devanagari
    ],
)
def test_unicode_text_is_never_rewritten(text: str) -> None:
    value, transforms = clean_value("chapter_title", text)
    assert value == text and value.encode() == text.encode()
    assert transforms == []


def test_non_nfc_text_is_reported_not_normalised() -> None:
    text = "क़"  # precomposed QA; composition-excluded, so NFC differs
    assert unicodedata.normalize("NFC", text) != text
    findings = inspect_text("chapter_title", text)
    assert [f.code for f in findings] == ["UNICODE_NOT_NFC"]
    assert clean_value("chapter_title", text)[0] == text


def test_control_characters_are_reported_not_stripped() -> None:
    text = "Title\x07 with bell"
    assert [f.code for f in inspect_text("chapter_title", text)] == ["CONTROL_CHARACTER"]
    assert clean_value("chapter_title", text)[0] == text


@pytest.mark.parametrize("text", ["Ã©tude", "à¤®à¤²à¥à¤¹à¤¾à¤°", "donâ€™t", "bad �"])
def test_mis_decoded_text_is_flagged(text: str) -> None:
    assert "ENCODING_SUSPECT" in [f.code for f in inspect_text("chapter_title", text)]


@pytest.mark.parametrize("token", ["NA", "n/a", "-", "null", "TBD"])
def test_null_like_tokens_are_reported_not_converted(token: str) -> None:
    assert [f.code for f in inspect_text("source_url", token)] == ["NULL_LIKE_TOKEN"]
    assert clean_value("source_url", token)[0] == token


def test_clean_row_keeps_identifiers_as_strings(inventory) -> None:
    row = inventory.row(7, inventory_id="CT-C06-MAT-007", class_level=" 6 ")
    values = tuple(row[c] for c in CANONICAL_HEADER)
    cleaned, transforms, _ = clean_row(CANONICAL_HEADER, values)
    assert cleaned["inventory_id"] == "CT-C06-MAT-007"
    assert cleaned["class_level"] == "6"
    assert [(t.column, t.rule) for t in transforms] == [("class_level", TRIM_OUTER_WHITESPACE)]


def test_cleaning_is_deterministic(inventory) -> None:
    values = tuple(inventory.row(3, chapter_title="  Shapes  ")[c] for c in CANONICAL_HEADER)
    assert clean_row(CANONICAL_HEADER, values) == clean_row(CANONICAL_HEADER, values)
