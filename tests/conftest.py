"""Shared fixtures: the recorded schema baseline and a normalised ORM metadata snapshot.

The snapshot shape is defined in `app/db/schema_snapshot.py` and is shared by the ORM,
the recorded baseline, the live catalog and migration-built disposable databases.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Table

BASELINE_PATH = Path(__file__).parent / "fixtures" / "concepttrail_schema_baseline.json"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live_db: read-only catalog checks against the PostgreSQL database configured in .env",
    )
    config.addinivalue_line(
        "markers",
        "migration_db: Alembic lifecycle tests that create and drop throwaway databases on the"
        " disposable server named by CONCEPTTRAIL_MIGRATION_TEST_ADMIN_URL",
    )
    config.addinivalue_line(
        "markers",
        "real_inventory: read-only run of the CSV pipeline on the real teammate inventory and"
        " PDFs, writing outputs to a temporary directory",
    )


def load_baseline() -> dict[str, Any]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def schema_baseline() -> dict[str, Any]:
    return load_baseline()


@pytest.fixture(scope="session")
def orm_tables() -> dict[str, Table]:
    from app.db import models  # noqa: F401  (registers the mapped tables)
    from app.db.session import Base

    return {table.name: table for table in Base.metadata.sorted_tables}


@pytest.fixture(scope="session")
def orm_snapshot(orm_tables: dict[str, Table]) -> dict[str, Any]:
    from app.db.schema_snapshot import metadata_snapshot
    from app.db.session import Base

    return metadata_snapshot(Base.metadata)


class InventoryFixtures:
    """Synthetic inventory rows, CSV files and fake PDFs (no real textbook content)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.pdf_root = root / "pdfs"
        self.pdf_root.mkdir()

    def pdf(self, rel_path: str, payload: bytes | None = None) -> str:
        """Create a fake PDF and return its SHA-256."""
        import hashlib

        data = payload if payload is not None else b"%PDF-1.7\n% synthetic " + rel_path.encode()
        target = self.pdf_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def row(self, n: int = 1, **overrides: str) -> dict[str, str]:
        rel_path = overrides.pop("local_path", f"class 6/maths/book{n:03d}.pdf")
        row = {
            "inventory_id": f"CT-C06-MAT-{n:03d}",
            "class_level": "6",
            "board": "CBSE",
            "academic_session": "2026-27",
            "subject_id": "mathematics",
            "course_or_language": "Mathematics",
            "item_type": "chapter_pdf",
            "chapter_or_unit_code": f"Chapter {n}",
            "chapter_title": f"Patterns √2 × π ≤ ∞ — अध्याय {n}",
            "topic_title": "",
            "learning_objective": "",
            "resource_title": "गणित Ganita: Textbook for Grade 6",
            "source_id": f"SRC-C06-MAT-FEGP1-{n:02d}",
            "source_url": "",
            "publication_or_revision": "First Edition: 2025",
            "rights_status": "review_required",
            "permitted_processing": "permission_required",
            "permitted_indexing": "permission_required",
            "permitted_training": "not_permitted",
            "permitted_display": "permission_required",
            "permission_reference": "https://example.org/terms",
            "acquired_at": "",
            "sha256": "",
            "extraction_status": "not_started",
            "validation_status": "passed",
            "review_status": "needs_review",
            "index_status": "not_indexed",
            "last_verified_at": "2026-10-29",
            "notes": f"local_path: {rel_path} | Source: synthetic fixture",
        }
        if rel_path:  # the file always exists; a `sha256` override only changes the record
            path = self.pdf_root / rel_path
            row["sha256"] = self.pdf(rel_path) if not path.exists() else _sha(path)
        row.update(overrides)
        return row

    def write_csv(
        self,
        name: str,
        rows: list[dict[str, str]] | list[list[str]],
        header: tuple[str, ...] | None = None,
        *,
        bom: bool = True,
        newline: str = "\r\n",
    ) -> Path:
        import csv
        import io

        from data_pipeline.inventory_schema import CANONICAL_HEADER

        header = header or CANONICAL_HEADER
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator=newline)
        writer.writerow(header)
        for row in rows:
            writer.writerow([row.get(c, "") for c in header] if isinstance(row, dict) else row)
        path = self.root / "incoming" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + buffer.getvalue().encode("utf-8"))
        return path


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def inventory(tmp_path: Path) -> InventoryFixtures:
    return InventoryFixtures(tmp_path)


UNICODE_FONT = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
SYNTHETIC_PROSE = (
    "This synthetic paragraph exists only for automated tests and repeats ordinary words so"
    " that the extractor sees several long lines of prose on the page."
)


class PdfFactory:
    """Synthetic PDFs (generic sentences only; never textbook content)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _font(self, page: Any) -> str:
        if UNICODE_FONT.exists():
            page.insert_font(fontname="uni", fontfile=str(UNICODE_FONT))
            return "uni"
        return "helv"

    def build(self, name: str, pages: list[dict[str, Any]], **save: Any) -> Path:
        import pymupdf

        doc = pymupdf.open()
        for spec in pages:
            page = doc.new_page(width=595, height=842)
            font = self._font(page)
            y = 80
            if spec.get("heading"):
                page.insert_text((72, y), spec["heading"], fontname=font, fontsize=20)
                y += 40
            for line in spec.get("lines", []):
                page.insert_text((72, y), line, fontname=font, fontsize=11)
                y += 16
            for x, yy, text, size in spec.get("spans", []):
                page.insert_text((x, yy), text, fontname=font, fontsize=size)
            if spec.get("footer"):
                page.insert_text((290, 820), spec["footer"], fontname=font, fontsize=9)
            if spec.get("table"):
                self._table(page, font, spec["table"])
            if spec.get("image_coverage"):
                self._image(page, spec["image_coverage"])
        if any("label_start" in s for s in pages):
            doc.set_page_labels(
                [
                    {
                        "startpage": 0,
                        "prefix": "",
                        "style": "D",
                        "firstpagenum": pages[0]["label_start"],
                    }
                ]
            )
        path = self.root / name
        doc.save(path, **save)
        doc.close()
        return path

    def _table(self, page: Any, font: str, rows: list[list[str]]) -> None:
        x0, y0, cw, rh = 72, 400, 120, 24
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                rect = (x0 + c * cw, y0 + r * rh, x0 + (c + 1) * cw, y0 + (r + 1) * rh)
                page.draw_rect(rect, color=(0, 0, 0), width=1)
                page.insert_text((rect[0] + 4, rect[1] + 16), cell, fontname=font, fontsize=10)

    def _image(self, page: Any, coverage: float) -> None:
        import pymupdf

        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
        pix.set_rect(pix.irect, (200, 200, 200))
        height = 842 * coverage
        page.insert_image(pymupdf.Rect(0, 0, 595, height), pixmap=pix, overlay=False)

    def scanned(self, name: str) -> Path:
        """A page whose only content is a picture of text (no text layer)."""
        import pymupdf

        source = self.build(
            "_src_" + name, [{"heading": "Scanned heading", "lines": [SYNTHETIC_PROSE[:80]] * 5}]
        )
        with pymupdf.open(source) as src:
            pix = src[0].get_pixmap(dpi=72)
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, pixmap=pix)
        path = self.root / name
        doc.save(path)
        doc.close()
        return path


@pytest.fixture
def pdfs(tmp_path: Path) -> PdfFactory:
    return PdfFactory(tmp_path)
