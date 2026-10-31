"""Inspection-pack page selection (no rendering)."""

from __future__ import annotations

from data_pipeline import inspection_pack as pack


def page(index: int, text: str = "x" * 50, ocr: dict | None = None, candidate: bool = False):
    return {
        "page_index": index,
        "text": text,
        "text_length": len(text),
        "classification": {
            "class": "scanned" if candidate else "mixed_text_image",
            "ocr_candidate": candidate,
        },
        "ocr": ocr or {"status": "not_required"},
    }


def test_every_ocr_page_and_top_virama_pages_are_chosen() -> None:
    raw = {
        "pages": [
            page(0),
            page(1, ocr={"status": "completed"}, candidate=True),
            page(2, ocr={"status": "low_confidence"}, candidate=True),
            page(3, "अन््य " * 5),
            page(4, "अन््य " * 9),
            page(5, "अन््य"),
            page(6, "अन््य " * 2),
        ]
    }
    picks = pack.choose_pages(raw)
    assert picks[1] == ["ocr_page:completed"] and picks[2] == ["ocr_page:low_confidence"]
    virama = {i: w for i, ws in picks.items() for w in ws if w.startswith("doubled_virama")}
    assert virama == {4: "doubled_virama:9", 3: "doubled_virama:5", 6: "doubled_virama:2"}


def test_ocr_examples_ignore_near_empty_pages() -> None:
    def ocr(conf: float, words: int) -> dict:
        return {"status": "completed", "mean_confidence": conf, "word_count": words}

    raws = [
        {
            "document": {"source_id": "A"},
            "pages": [
                page(0, ocr=ocr(99.0, 1)),
                page(1, ocr=ocr(40.0, 30)),
                page(2, ocr=ocr(90.0, 200)),
            ],
        },
        {"document": {"source_id": "B"}, "pages": [page(0, ocr=ocr(70.0, 80))]},
    ]
    labels = pack.ocr_extremes(raws)
    assert ("A", 0) not in labels  # one word at 99% is not a good example
    assert labels[("A", 1)] == "ocr_example_poor" and labels[("A", 2)] == "ocr_example_good"


def test_decisions_summary_lists_each_document() -> None:
    text = pack.decisions_markdown(
        [
            {
                "source_document_id": "SRC-X",
                "topic_value_status": "not_found",
                "topic_count": 0,
                "objective_value_status": "requires_human_review",
                "objective_counts_by_origin": {"textbook_explicit": 0},
                "reasons": {"topic_title": "none", "learning_objective": "teacher needed"},
            }
        ]
    )
    assert "| `SRC-X` | not_found | 0 | none | requires_human_review | - | teacher needed |" in text
