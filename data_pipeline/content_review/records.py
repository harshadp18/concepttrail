"""Loader for the PRIVATE content-review records.

The AI review findings, graph findings, gap-fill questions and the built patch are AI-drafted
content written against specific textbook chapters, so they live in the Git-ignored folder
`data_pipeline/data/overrides/content_review/` (docs/PUBLICATION_AND_REPRODUCIBILITY.md), not in
source modules. A public checkout does not have them: `available()` is then False and the patch
commands refuse with a clear message.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PRIVATE_DIR = ROOT / "data_pipeline/data/overrides/content_review"
RECORDS = PRIVATE_DIR / "review_records_v1.json"
PATCH = PRIVATE_DIR / "patch_v1.json"
CATALOGUE = (
    ROOT / "data_pipeline/data/overrides/metadata_enrichment/official_learning_outcomes.json"
)
FINDING_SETS = ("findings_c6", "findings_c7", "findings_c8", "findings_c9", "findings_c10")


class RecordsUnavailable(RuntimeError):
    pass


def available() -> bool:
    return RECORDS.exists()


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    if not RECORDS.exists():
        raise RecordsUnavailable(
            f"private review records not found: {RECORDS.relative_to(ROOT)} "
            "(supplied privately; see docs/PUBLICATION_AND_REPRODUCIBILITY.md)"
        )
    return json.loads(RECORDS.read_text(encoding="utf-8"))


def findings() -> list[dict]:
    data = load()["findings"]
    return [f for name in FINDING_SETS for f in data[name]]


def remove_edges() -> dict[tuple[str, str], str]:
    return {(a, b): r for a, b, r in load()["graph"]["remove_edges"]}


def escalate_edges() -> dict[tuple[str, str], str]:
    return {(a, b): r for a, b, r in load()["graph"]["escalate_edges"]}


def kc_findings() -> list[dict]:
    return load()["graph"]["kc_findings"]


def additions() -> list[dict]:
    return load()["additions"]


def outcome_kcs() -> list[dict]:
    return load()["outcome_kcs"]


def outcome_questions() -> list[dict]:
    return load()["outcome_questions"]
