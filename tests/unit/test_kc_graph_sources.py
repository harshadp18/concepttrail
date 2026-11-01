"""M2: source-reference resolution against the inventory, artifacts and rights overlay."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from kc_graph_fixtures import pkg_fixture  # noqa: F401  (registers the `pkg` fixture)

from data_pipeline.authorization import Decision
from data_pipeline.kc_graph import synthetic
from data_pipeline.kc_graph.rows import parse_token
from data_pipeline.kc_graph.sources import ARTIFACT_DIR, INVENTORY, build_index

PIN = "a1b2c3d4e5f6"


def resolve(index, raw: str):
    resolution, findings = index.resolve(
        parse_token(raw), label="edge_csv", record="r", column="evidence_refs"
    )
    return resolution, {f.code for f in findings}


def test_valid_token_resolves_to_full_provenance() -> None:
    index = synthetic.source_index()
    resolution, found = resolve(index, f"src:SRC-C07-MAT-EXMP1-01@5:para2#{PIN}")
    assert found == set() and resolution.page == 5 and resolution.para == 2
    assert (
        resolution.source_sha256 == synthetic.SYNTHETIC_SHA and len(resolution.passage_sha256) == 64
    )
    assert resolution.revision == "synthetic" and resolution.academic_session == "2026-27"


@pytest.mark.parametrize(
    "raw, change, code",
    [
        (f"src:SRC-C07-MAT-OTHER-01@1#{PIN}", {}, "SOURCE_UNKNOWN"),
        (f"src:SRC-C07-MAT-EXMP1-01@1#{'0' * 12}", {}, "SOURCE_PIN_MISMATCH"),
        (f"src:SRC-C07-MAT-EXMP1-01@8#{PIN}", {}, "PAGE_OUT_OF_RANGE"),
        (f"src:SRC-C07-MAT-EXMP1-01@1:para3#{PIN}", {}, "PARAGRAPH_OUT_OF_RANGE"),
        (f"src:SRC-C07-MAT-EXMP1-01@1#{PIN}", {"accepted": False}, "SOURCE_NOT_ACCEPTED"),
        (f"src:SRC-C07-MAT-EXMP1-01@1#{PIN}", {"rights_permitted": False}, "SOURCE_RIGHTS_BLOCKED"),
        (f"src:SRC-C07-MAT-EXMP1-01@1#{PIN}", {"artifact": None}, "SOURCE_ARTIFACT_MISSING"),
        (f"src:SRC-C07-MAT-EXMP1-01@1#{PIN}", {"artifact_sha256": "f" * 64}, "SOURCE_PIN_MISMATCH"),
        (f"src:SRC-C07-MAT-EXMP1-01@1#{PIN}", {"pdf_status": "mismatch"}, "SOURCE_PIN_MISMATCH"),
    ],
)
def test_resolution_failures_are_precise(raw: str, change: dict, code: str) -> None:
    index = synthetic.source_index()
    doc = index.documents["SRC-C07-MAT-EXMP1-01"]
    index.documents[doc.source_id] = replace(doc, **change)
    assert resolve(index, raw) == (None, {code})


def test_unusable_page_text_cannot_hold_a_passage_locator() -> None:
    index = synthetic.source_index()
    doc = index.documents["SRC-C07-MAT-EXMP1-01"]
    pages = list(doc.pages)
    pages[1] = (True, pages[1][1])
    index.documents[doc.source_id] = replace(doc, pages=tuple(pages))
    assert resolve(index, f"src:SRC-C07-MAT-EXMP1-01@1:para0#{PIN}")[1] == {"SOURCE_TEXT_UNUSABLE"}
    assert resolve(index, f"src:SRC-C07-MAT-EXMP1-01@1#{PIN}")[1] == set()  # page-level is fine


def test_unresolved_sources_are_reported_by_the_loader(pkg) -> None:
    pkg.inputs.sources = None
    assert "SOURCE_INDEX_UNAVAILABLE" in pkg.codes("error")


def test_index_build_from_inventory_artifact_and_rights(tmp_path: Path) -> None:
    sha = hashlib.sha256(b"pdf bytes").hexdigest()
    inventory = tmp_path / "inventory.csv"
    inventory.write_text(
        "source_id,sha256,resource_title,publication_or_revision,academic_session,validation_status\n"
        f"SRC-C09-MAT-TEST1-01,{sha},T,Rev,2026-27,passed\n",
        encoding="utf-8",
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    pdf = tmp_path / "t.pdf"
    pdf.write_bytes(b"pdf bytes")
    (artifacts / "x.normalized.json").write_text(
        json.dumps(
            {
                "document": {
                    "source_id": "SRC-C09-MAT-TEST1-01",
                    "pdf_sha256": sha,
                    "pdf_path": "t.pdf",
                },
                "pages": [{"page_index": 0, "paragraphs": [{"text": "p"}], "text_unusable": False}],
            }
        )
    )

    def allow(source_id, sha256, use, records):
        assert use == "local_text_normalization"
        return Decision(use, True, "test")

    index = build_index(inventory, artifacts, tmp_path, check=allow)
    doc = index.documents["SRC-C09-MAT-TEST1-01"]
    assert doc.page_count == 1 and doc.pdf_status == "verified" and doc.rights_permitted
    assert doc.pages[0][1][0] == hashlib.sha256(b"p").hexdigest()

    def deny(*args):
        return Decision("x", False, "no record")

    index = build_index(inventory, artifacts, tmp_path, check=deny)
    token = f"src:SRC-C09-MAT-TEST1-01@0#{sha[:12]}"
    assert resolve(index, token)[1] == {"SOURCE_RIGHTS_BLOCKED"}


@pytest.mark.skipif(not INVENTORY.exists() or not ARTIFACT_DIR.exists(), reason="no local data")
def test_real_pilot_documents_resolve_read_only() -> None:
    """Every extracted artifact resolves page 0; other inventory rows have no artifact."""
    index = build_index()
    with_artifacts = [d for d in index.documents.values() if d.artifact]
    assert len(with_artifacts) >= 10  # the 10 Phase 4 pilot documents plus later extractions
    for doc in with_artifacts:
        resolution, found = resolve(index, f"src:{doc.source_id}@0#{doc.sha256[:12]}")
        assert found == set(), (doc.source_id, found)
    other = next(d for d in index.documents.values() if not d.artifact)
    assert resolve(index, f"src:{other.source_id}@0#{other.sha256[:12]}")[1] in (
        {"SOURCE_ARTIFACT_MISSING"},
        {"SOURCE_RIGHTS_BLOCKED"},
    )
