"""Chapter inventory, selection and extraction of only the missing chapters.

Selection: for each class-subject combination present in the accepted inventory, chapters in
chapter-number order; a chapter with an existing usable normalised artifact is preferred, and a
chapter whose extraction yields no usable text (for example a legacy-font Hindi PDF) is skipped
for the next one. Extraction reuses `run_extraction_pilot.process_document` unchanged (rights
gate, PDF integrity, page provenance); nothing already extracted is redone.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from data_pipeline import run_extraction_pilot as pilot
from data_pipeline.stages import ocr_pages

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "resources/teammate_csv/processed/cleaned/curriculum_inventory.cleaned.csv"
ARTIFACTS = ROOT / "data_pipeline/data/processed/textbook_json"
_CHAPTER_NO = re.compile(r"(\d+)")


def accepted_rows() -> list[dict[str, str]]:
    with INVENTORY.open(encoding="utf-8", newline="") as handle:
        return [r for r in csv.DictReader(handle) if r["validation_status"] == "passed"]


def artifact_for(source_id: str, sha256: str) -> Path | None:
    for path in sorted(ARTIFACTS.glob(f"{source_id}__*.normalized.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["document"].get("pdf_sha256") == sha256:
            return path
    return None


def usable(path: Path, min_pages: int = 2) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("text_unusable"):
        return False
    good = [p for p in data["pages"] if not p.get("text_unusable") and len(p.get("text", "")) > 200]
    return len(good) >= min_pages


def chapter_number(row: dict[str, str]) -> int:
    match = _CHAPTER_NO.search(row["chapter_or_unit_code"] or "")
    return int(match.group(1)) if match else 999


def inventory() -> dict[tuple[int, str], list[dict[str, Any]]]:
    combos: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in accepted_rows():
        if row["item_type"] != "chapter_pdf":
            continue
        path = artifact_for(row["source_id"], row["sha256"])
        combos[(int(row["class_level"]), row["subject_id"])].append(
            {"row": row, "artifact": path, "chapter_no": chapter_number(row)}
        )
    for items in combos.values():
        items.sort(key=lambda x: (x["artifact"] is None, x["chapter_no"], x["row"]["source_id"]))
    return dict(sorted(combos.items()))


def extract(row: dict[str, str]) -> tuple[Path | None, str]:
    """Run the existing extraction for one accepted chapter; returns (artifact, status)."""
    inputs = pilot.load_inputs()
    result = pilot.process_document(
        {"source_id": row["source_id"], "slot": "demo"}, inputs, ocr_pages.detect_tesseract()
    )
    if result["status"] != "processed":
        return None, f"{result['status']}:{result.get('reason')}"
    return Path(result["normalized_path"]), "processed"


def select(per_combo: int = 1, max_tries: int = 3) -> list[dict[str, Any]]:
    """Choose up to `per_combo` usable chapters per class-subject, extracting if needed."""
    chosen = []
    for (cls, subject), items in inventory().items():
        picked, tries = 0, 0
        for item in items:
            if picked >= per_combo or tries >= max_tries + per_combo:
                break
            row, path, status = item["row"], item["artifact"], "existing"
            if path is None:
                tries += 1
                path, status = extract(row)
            if path is not None and usable(path):
                chosen.append(
                    {
                        "class_level": cls,
                        "subject_id": subject,
                        "source_id": row["source_id"],
                        "inventory_id": row["inventory_id"],
                        "chapter": row["chapter_title"],
                        "artifact": path.name,
                        "extraction": status,
                    }
                )
                picked += 1
            elif path is not None:
                tries += 1
        if picked < per_combo:
            chosen.append(
                {
                    "class_level": cls,
                    "subject_id": subject,
                    "source_id": None,
                    "reason": "no usable chapter text after extraction attempts",
                }
            )
    return chosen
