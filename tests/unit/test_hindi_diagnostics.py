"""Doubled-virama diagnostics: previews only, never applied to pipeline text (D-040)."""

from __future__ import annotations

from data_pipeline import hindi_diagnostics as hd


class FakePage:
    """Minimal stand-in for a PyMuPDF page: one line of (character, x-origin) glyphs."""

    def __init__(self, glyphs: list[tuple[str, float]]) -> None:
        self.glyphs = glyphs

    def get_text(self, kind: str) -> dict:
        assert kind == "rawdict"
        chars = [{"c": c, "origin": (x, 100.0)} for c, x in self.glyphs]
        return {"blocks": [{"lines": [{"spans": [{"font": "ABC+Kokila", "chars": chars}]}]}]}


def glyphs(*parts: tuple[str, float]) -> list[tuple[str, float]]:
    return list(parts)


# "अन््य" as the font emits it: the virama glyph maps to two code points at one origin.
DOUBLED_VIRAMA_WORD = glyphs(("अ", 0), ("न", 5), ("्", 9), ("्", 9), ("य", 10))


def test_preview_d040_collapses_only_doubled_virama() -> None:
    assert hd.preview_d040("अन््य कार््य") == ("अन्य कार्य", 2)
    assert hd.preview_d040("अन्य") == ("अन्य", 0)
    assert hd.preview_d040("क्््ष")[0] == "क्ष"


def test_same_position_duplicates_drop_only_same_origin_devanagari() -> None:
    text, dropped = hd.same_position_duplicates(FakePage(DOUBLED_VIRAMA_WORD))
    assert text == "अन्य"
    assert dropped == {"्": 1}
    # A genuinely doubled letter is two glyphs at different positions: kept.
    text, dropped = hd.same_position_duplicates(
        FakePage(glyphs(("म", 0), ("म", 6), ("त", 12), ("ा", 16)))
    )
    assert text == "ममता" and not dropped


def test_proposed_scope_never_touches_latin_or_spaces() -> None:
    overprinted = glyphs(("A", 0), ("A", 0), (" ", 6), (" ", 6), ("b", 9))
    assert hd.same_position_duplicates(FakePage(overprinted))[0] == "AA  b"
    unscoped, dropped = hd.same_position_duplicates(FakePage(overprinted), devanagari_only=False)
    assert unscoped == "A b" and sum(dropped.values()) == 2


def test_glyph_aware_word_pairs_and_residual_signs() -> None:
    page = FakePage(DOUBLED_VIRAMA_WORD + [(" ", 14), ("न", 18), ("न", 18), ("े", 22)])
    assert hd.glyph_aware_word_pairs(page) == [("अन््य", "अन्य"), ("नने", "ने")]
    assert hd.REPEATED_SIGN.findall("होों") == ["ो"]
    assert not hd.REPEATED_SIGN.findall("होंगे")


def test_glyph_diagnosis_counts_same_position_viramas_by_font() -> None:
    result = hd.glyph_diagnosis(FakePage(DOUBLED_VIRAMA_WORD))
    assert result == {"same_glyph_position": 1, "distinct_positions": 0, "fonts": {"Kokila": 1}}


def test_compare_with_ocr_counts_forms_seen() -> None:
    result = hd.compare_with_ocr("अन््य कार््य शब्द", "अन्य काय शब्द")
    assert result["native_words_with_doubled_virama"] == 2
    assert result["ocr_reads_single_virama_form"] == 1
    assert result["ocr_reads_doubled_form"] == 0
    assert result["neither_form_in_ocr"] == 1
    assert result["doubled_virama_in_ocr_text"] == 0
    assert (
        result["similarity_ocr_vs_native_after_d040_preview"] > result["similarity_ocr_vs_native"]
    )


def test_diagnostics_never_claim_the_rule_was_applied() -> None:
    assert (
        hd.markdown(
            {
                "diagnostic_version": "x",
                "summary": {},
                "documents": [],
                "proposed_rule_scope_survey": [],
            }
        ).count("applied: **no**")
        == 1
    )
