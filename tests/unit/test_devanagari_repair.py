"""D-044 same-glyph Devanagari repair: exact, scoped, logged, deterministic, idempotent."""

from __future__ import annotations

import copy

from data_pipeline.stages import repair_devanagari as rd


class FakePage:
    """PyMuPDF page stand-in: blocks of lines of (character, x-origin) glyphs."""

    def __init__(self, blocks: list[list[list[tuple[str, float]]]]) -> None:
        self.blocks = blocks

    def get_text(self, kind: str) -> dict:
        assert kind == "rawdict"
        return {
            "blocks": [
                {
                    "type": 0,
                    "lines": [
                        {"spans": [{"chars": [{"c": c, "origin": (x, 0.0)} for c, x in line]}]}
                        for line in block
                    ],
                }
                for block in self.blocks
            ]
        }


def glyphs(text: str, same_origin_after: set[int] = frozenset()) -> list[tuple[str, float]]:
    """Glyphs for `text`; indexes in `same_origin_after` share the previous glyph's origin."""
    out, x = [], 0.0
    for i, ch in enumerate(text):
        if i not in same_origin_after:
            x += 5.0
        out.append((ch, x))
    return out


# As the Kokila font emits them: the repeated code point sits at the same glyph origin.
ANYA = glyphs("अन््य", {3})  # अन््य -> अन्य
APNE = glyphs("अपनने", {3})  # अपनने -> अपने
SUNNE = glyphs("सुनने")  # a real double न: two glyphs, two positions


def raw_page(*block_texts: str) -> dict:
    return {
        "page_index": 4,
        "page_label": {"value": "21"},
        "text": "\n".join(block_texts) + "\n",
        "blocks": [
            {"block_no": i, "type": "text", "bbox": [0, i, 1, i + 1], "text": t + "\n"}
            for i, t in enumerate(block_texts)
        ],
        "heading_candidates": [{"text": "अन््य", "size": 16}],
    }


def test_reported_examples_are_repaired_with_exact_offsets() -> None:
    page = raw_page("अन््य अपनने")
    pdf_page = FakePage([[ANYA + [(" ", 30.0)] + [(c, x + 40) for c, x in APNE]]])
    result = rd.repair_page(page, pdf_page)
    assert result["page"]["blocks"][0]["text"] == "अन्य अपने\n"
    assert [(c["word_before"], c["word_after"], c["offset"]) for c in result["corrections"]] == [
        ("अन््य", "अन्य", 3),
        ("अपनने", "अपने", 9),
    ]
    assert result["corrections"][0]["codepoint"] == "U+094D"
    assert result["page"]["heading_candidates"][0]["text"] == "अन्य"
    assert result["unaligned_blocks"] == []


def test_input_page_and_genuine_doubles_and_latin_are_untouched() -> None:
    page = raw_page("सुनने AAB")
    original = copy.deepcopy(page)
    overprinted = [("A", 50.0), ("A", 50.0), ("B", 55.0)]  # same origin, but Latin
    result = rd.repair_page(page, FakePage([[SUNNE + [(" ", 30.0)] + overprinted]]))
    assert result["page"]["blocks"][0]["text"] == "सुनने AAB\n"
    assert result["corrections"] == []
    assert page == original  # the raw page is never modified
    assert result["page"]["text"] == original["text"]  # page text (raw_ref basis) unchanged


def test_glyph_stream_with_embedded_newline_still_aligns() -> None:
    line_one = ANYA + [("\n", 26.0)]
    page = raw_page("अन््य\nअपनने")
    result = rd.repair_page(page, FakePage([[line_one, APNE]]))
    assert result["page"]["blocks"][0]["text"] == "अन्य\nअपने\n"


def test_unaligned_devanagari_block_is_reported_not_guessed() -> None:
    page = raw_page("अन््य", "Plain English")
    result = rd.repair_page(page, FakePage([[glyphs("कुछ और")], [glyphs("Plain English")]]))
    assert result["page"]["blocks"][0]["text"] == "अन््य\n"
    assert result["unaligned_blocks"] == [0]  # English-only blocks are not reported


def test_repair_is_deterministic_and_idempotent() -> None:
    raw = {"document": {"source_id": "S", "pdf_sha256": "a" * 64}, "pages": [raw_page("अपनने")]}
    pdf = [FakePage([[APNE]])]
    first = rd.repair_document(raw, pdf)
    assert first == rd.repair_document(raw, pdf)
    assert first["log"]["corrections_total"] == 1 and first["log"]["rule"] == "D-044"
    assert first["log"]["pages"][0]["printed_page_label"] == "21"
    # Re-applying to already repaired text (now drawn without duplicates) changes nothing.
    again = rd.repair_document(first["view"], [FakePage([[glyphs("अपने")]])])
    assert again["view"] == first["view"] and again["log"]["corrections_total"] == 0


def test_remaining_repeated_vowel_signs_are_listed_for_review() -> None:
    found = rd.repeated_signs("उन्होोंने ने होंगे")
    assert [(f["sign"], f["word"]) for f in found] == [("ो", "उन्होोंने")]
    assert rd.repeated_signs("अन्य होंगे") == []


def test_other_residue_is_flagged_not_corrected() -> None:
    flags = rd.other_review_flags("मूल्यांांकन ख्ययाति अध्ययन")
    assert [(f["kind"], f["word"]) for f in flags] == [
        ("repeated_sign_pair", "मूल्यांांकन"),
        ("suspect_consonant_repeat_after_virama", "ख्ययाति"),
        ("suspect_consonant_repeat_after_virama", "अध्ययन"),  # genuine word: suspect only
    ]
    assert [f["kind"] for f in rd.other_review_flags("व्यंयंग्यकार")] == ["suspect_syllable_repeat"]
    missing = rd.other_review_flags("कक्ाओं व्यक्\u200dततियों")
    assert [f["kind"] for f in missing] == [
        "missing_conjunct_consonant",
        "suspect_consonant_repeat_after_virama",
    ]
