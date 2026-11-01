"""KC lifecycle log: non-destructive retirement and reinstatement (D15, guidelines 8), M4.

Lifecycle (`active`/`retired`) is separate from review status: a retired KC stays `approved`.
`overrides/kc_review/lifecycle_log.jsonl` is hash-chained exactly like the review log (`LC-`
IDs) and anchored as `lifecycle-anchor-<seq>.json`. Nothing is deleted: no KC row, no edge row,
no `student_kc_state` row. There is no automatic mastery transfer (a Phase 9 policy decision).

The authoriser enters `kc_id`, `action`, `authorised_by`, `reason`, `effective_at`,
`replacement_kc_ids`, `edge_resolution` and `learner_history_note`; the tool adds
`kc_row_digest`, `recorded_at` and the chain fields.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.services.graph_snapshot import retired_state
from data_pipeline.kc_graph import contract as c
from data_pipeline.kc_graph.digests import full_digest
from data_pipeline.kc_graph.findings import Finding, finding
from data_pipeline.kc_graph.people import Register
from data_pipeline.kc_graph.rows import EdgeRow, KcRow

LABEL = "lifecycle_log"
ENTRY_FIELDS = (
    "kc_id",
    "action",
    "authorised_by",
    "reason",
    "effective_at",
    "replacement_kc_ids",
    "edge_resolution",
    "learner_history_note",
)
ACTIONS = ("retire", "reinstate")
RESOLUTIONS = ("rejected", "superseded")


def touching(kc_id: str, edges: dict[str, EdgeRow]) -> list[str]:
    return sorted(k for k, e in edges.items() if kc_id in (e.prerequisite_kc_id, e.dependent_kc_id))


def entry_problems(
    entry: dict[str, Any],
    kcs: dict[str, KcRow],
    edges: dict[str, EdgeRow],
    register: Register | None,
) -> list[tuple[str, str]]:
    """Problems with a lifecycle event against the current rows and register."""
    out = []
    kc_id = entry.get("kc_id", "")
    if entry.get("action") not in ACTIONS:
        out.append(("LIFECYCLE_INVALID", f"action must be one of {ACTIONS}"))
    if kc_id not in kcs:
        out.append(("LIFECYCLE_INVALID", f"{kc_id!r} is not a current KC"))
    for name in ("reason", "effective_at", "authorised_by"):
        if not str(entry.get(name, "")).strip():
            out.append(("LIFECYCLE_INVALID", f"{name} is required"))
    who = entry.get("authorised_by", "")
    person = register.people.get(who) if register else None
    if (
        person is None
        or who not in register.verified_codes
        or not person.active  # type: ignore[union-attr]
        or not person.roles & set(c.LIFECYCLE_AUTHORISER_ROLES)
    ):
        out.append(("LIFECYCLE_UNAUTHORISED", f"{who!r} is not a verified senior reviewer"))
    if entry.get("action") != "retire":
        return out
    if not str(entry.get("learner_history_note", "")).strip():
        out.append(("LIFECYCLE_INVALID", "learner_history_note is required for a retirement"))
    for replacement in entry.get("replacement_kc_ids", []) or []:
        if replacement == kc_id or replacement not in kcs:
            out.append(("LIFECYCLE_INVALID", f"replacement {replacement!r} is not another KC"))
    resolved = {r.get("edge"): r for r in entry.get("edge_resolution", []) or []}
    for key in touching(kc_id, edges):
        edge = edges[key]
        r = resolved.get(key)
        if r is None:
            if edge.review_status == "approved":
                out.append(("LIFECYCLE_EDGE_UNRESOLVED", f"approved edge {key} has no resolution"))
            continue
        if r.get("resolution") == "rejected" and edge.review_status != "rejected":
            out.append(
                ("LIFECYCLE_EDGE_UNRESOLVED", f"edge {key} is recorded as rejected but is not")
            )
        if r.get("resolution") not in RESOLUTIONS:
            out.append(
                ("LIFECYCLE_INVALID", f"edge {key}: resolution must be one of {RESOLUTIONS}")
            )
        elif r["resolution"] == "superseded" and r.get("replacement_edge") not in edges:
            out.append(
                (
                    "LIFECYCLE_EDGE_UNRESOLVED",
                    f"edge {key}: the replacement edge "
                    f"{r.get('replacement_edge')!r} does not exist",
                )
            )
    return out


def build_event(
    entry: dict[str, Any],
    kcs: dict[str, KcRow],
    edges: dict[str, EdgeRow],
    register: Register | None,
    recorded_at: str,
) -> dict[str, Any]:
    if extra := sorted(set(entry) - set(ENTRY_FIELDS)):
        raise ValueError(f"fields that may not be set: {extra}")
    if problems := entry_problems(entry, kcs, edges, register):
        raise ValueError("; ".join(f"{code}: {m}" for code, m in problems))
    event = {k: entry.get(k) for k in ENTRY_FIELDS}
    event["replacement_kc_ids"] = list(entry.get("replacement_kc_ids") or [])
    event["edge_resolution"] = list(entry.get("edge_resolution") or [])
    event.update(kc_row_digest=full_digest(kcs[entry["kc_id"]].cells), recorded_at=recorded_at)
    return event


def verify(
    events: Sequence[dict[str, Any]],
    kcs: dict[str, KcRow],
    edges: dict[str, EdgeRow],
    register: Register | None,
) -> tuple[set[str], list[Finding]]:
    """(retired KC IDs in force, findings) for the current rows."""
    findings: list[Finding] = []
    in_force = retired_state([e for e in events if isinstance(e, dict) and "kc_id" in e])
    for kc_id, event in sorted(in_force.items()):
        record = event.get("event_id", "")
        for code, message in entry_problems(event, kcs, edges, register):
            if code != "LIFECYCLE_UNAUTHORISED" or register is not None:
                findings.append(finding(code, message, file=LABEL, record=record))
        if kc_id in kcs and event.get("kc_row_digest") != full_digest(kcs[kc_id].cells):
            findings.append(
                finding(
                    "LIFECYCLE_STALE",
                    f"{kc_id} changed after its retirement record",
                    file=LABEL,
                    record=record,
                )
            )
        for key in touching(kc_id, edges):
            if edges[key].review_status == "approved":
                findings.append(
                    finding(
                        "EDGE_TOUCHES_RETIRED_KC",
                        f"approved edge uses retired {kc_id}",
                        file="edge_csv",
                        line=edges[key].line,
                        record=key,
                    )
                )
    return set(in_force), findings
