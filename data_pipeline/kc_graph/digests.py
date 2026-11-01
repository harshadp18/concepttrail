"""Full record digest, pedagogical content digest and field classes P/S/C (D8, D13).

- **Full record digest**: SHA-256 of the canonical JSON of every column except `review_status`
  and `review_record_ids`, as the raw cell strings. Any edit changes it.
- **Pedagogical content digest**: SHA-256 of the P fields only, in a normalised form (parsed
  misconceptions, sorted evidence tokens), so a pure re-serialisation does not change it.
- **KC content version** (`content_version`): bumped only when the pedagogical digest changes.

`kc_id` and `stable_key` are identity, never edited after first approval.
"""

from __future__ import annotations

from typing import Any

from app.services.audit_chain import digest
from data_pipeline.kc_graph.rows import EdgeRow, KcRow

EXCLUDED_FROM_FULL = ("review_status", "review_record_ids")
IDENTITY = ("kc_id", "stable_key")
KC_FIELD_CLASS = {
    "subject_id": "P",
    "kc_type": "P",
    "learning_objective": "P",
    "misconceptions": "P",
    "scope": "P",
    "source_refs": "S",
    "difficulty_tier": "S",
    "declared_class_levels": "S",
    "aliases": "S",
    "name": "C",
    "origin": "C",
    "origin_ref": "C",
    "author_id": "C",
}
EDGE_FIELD_CLASS = {
    "prerequisite_kc_id": "P",
    "dependent_kc_id": "P",
    "dependency_basis": "P",
    "evidence_refs": "P",
    "reason": "S",
    "strength": "S",
    "origin": "C",
    "origin_ref": "C",
    "author_id": "C",
}


def full_digest(cells: dict[str, str]) -> str:
    return digest({k: v for k, v in cells.items() if k not in EXCLUDED_FROM_FULL})


def kc_pedagogical(kc: KcRow) -> dict[str, Any]:
    return {
        "subject_id": kc.subject_id,
        "kc_type": kc.kc_type,
        "learning_objective": kc.learning_objective,
        "misconceptions": [dict(sorted(m.items())) for m in kc.misconceptions],
        "scope": kc.scope,
    }


def edge_pedagogical(edge: EdgeRow) -> dict[str, Any]:
    return {
        "prerequisite_kc_id": edge.prerequisite_kc_id,
        "dependent_kc_id": edge.dependent_kc_id,
        "dependency_basis": edge.dependency_basis,
        "evidence_refs": sorted(t.raw for t in edge.evidence_refs),
    }


def kc_pedagogical_digest(kc: KcRow) -> str:
    return digest(kc_pedagogical(kc))


def edge_pedagogical_digest(edge: EdgeRow) -> str:
    return digest(edge_pedagogical(edge))


def changed_classes(old: dict[str, str], new: dict[str, str], classes: dict[str, str]) -> set[str]:
    """Which classes (P, S, C, identity) differ between two versions of the same row's cells."""
    out = set()
    for column in set(old) | set(new):
        if column in EXCLUDED_FROM_FULL or old.get(column) == new.get(column):
            continue
        out.add("identity" if column in IDENTITY else classes.get(column, "?"))
    return out
