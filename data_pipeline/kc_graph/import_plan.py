"""Import of a released snapshot into the existing `knowledge_component` and `kc_edge` tables (M6).

Three separate operations, never chained by one command:

1. `plan`: read-only. Compares the verified snapshot with the database and lists inserts,
   updates, no-ops and conflicts. Nothing is deleted, ever; database rows absent from the
   snapshot are reported as untouched.
2. `execute`: writes, only with an owner approval record bound to the snapshot digest and the
   plan digest. One transaction: it re-plans inside the transaction, aborts if the plan drifted
   or has conflicts, applies, reads back and verifies, and rolls back on any mismatch.
3. `reconcile`: read-only comparison after an import.

Fail-closed rules: a `stable_key` never changes for an existing `kc_id`; an existing approved
KC whose pedagogical columns differ at the same `content_version` is a conflict (the version
and review procedure must run first); a lower incoming version is a conflict. Only columns that
exist are written (contract section 9); everything else stays in the private sidecars.
`kc_curriculum_map` rows are not generated: no approved curriculum-mapping source exists yet.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import Connection, Engine, select, update

from app.db.models import KcEdge, KnowledgeComponent, Subject
from app.services.audit_chain import digest
from app.services.graph_snapshot import verify_snapshot
from data_pipeline.kc_graph.contract import KC_VERSION_RE
from data_pipeline.teacher_validation import write_once

KC_COLUMNS = (
    "kc_id",
    "subject_id",
    "stable_key",
    "name",
    "description",
    "kc_type",
    "difficulty_tier",
    "misconceptions",
    "review_status",
    "content_version",
)
EDGE_COLUMNS = ("prerequisite_kc_id", "dependent_kc_id", "strength", "reason", "review_status")
KC_PEDAGOGICAL_COLUMNS = ("subject_id", "description", "kc_type", "misconceptions")
APPROVAL_TYPE = "kc_graph_import_approval"


class ImportAborted(RuntimeError):
    pass


class Store(Protocol):
    def kcs(self, kc_ids: Iterable[str]) -> dict[str, dict[str, Any]]: ...
    def kc_ids_by_stable_key(self, keys: Iterable[str]) -> dict[str, str]: ...
    def edges(self, keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]: ...
    def subjects(self, subject_ids: Iterable[str]) -> set[str]: ...
    def insert_kc(self, row: dict[str, Any]) -> None: ...
    def update_kc(self, kc_id: str, values: dict[str, Any]) -> None: ...
    def insert_edge(self, row: dict[str, Any]) -> None: ...
    def update_edge(self, key: tuple[str, str], values: dict[str, Any]) -> None: ...


class SqlStore:
    """`Store` over an open SQLAlchemy connection; the caller owns the transaction."""

    def __init__(self, connection: Connection) -> None:
        self.conn = connection
        self.kc = KnowledgeComponent.__table__
        self.edge = KcEdge.__table__
        self.subject = Subject.__table__

    def kcs(self, kc_ids):
        rows = self.conn.execute(select(self.kc).where(self.kc.c.kc_id.in_(list(kc_ids))))
        return {r.kc_id: {c: getattr(r, c) for c in KC_COLUMNS} for r in rows}

    def kc_ids_by_stable_key(self, keys):
        rows = self.conn.execute(
            select(self.kc.c.stable_key, self.kc.c.kc_id).where(
                self.kc.c.stable_key.in_(list(keys))
            )
        )
        return {r.stable_key: r.kc_id for r in rows}

    def edges(self, keys):
        keys = list(keys)
        prereqs = {k[0] for k in keys}
        rows = self.conn.execute(
            select(self.edge).where(self.edge.c.prerequisite_kc_id.in_(list(prereqs)))
        )
        wanted = set(keys)
        out = {}
        for r in rows:
            key = (r.prerequisite_kc_id, r.dependent_kc_id)
            if key in wanted:
                out[key] = {c: getattr(r, c) for c in EDGE_COLUMNS}
        return out

    def subjects(self, subject_ids):
        rows = self.conn.execute(
            select(self.subject.c.subject_id).where(
                self.subject.c.subject_id.in_(list(subject_ids))
            )
        )
        return {r.subject_id for r in rows}

    def insert_kc(self, row):
        self.conn.execute(self.kc.insert().values(**row))

    def update_kc(self, kc_id, values):
        self.conn.execute(update(self.kc).where(self.kc.c.kc_id == kc_id).values(**values))

    def insert_edge(self, row):
        self.conn.execute(self.edge.insert().values(**row))

    def update_edge(self, key, values):
        self.conn.execute(
            update(self.edge)
            .where(self.edge.c.prerequisite_kc_id == key[0], self.edge.c.dependent_kc_id == key[1])
            .values(**values)
        )


@dataclass(frozen=True)
class Desired:
    kcs: dict[str, dict[str, Any]]
    edges: dict[tuple[str, str], dict[str, Any]]


def desired(snapshot: dict[str, Any]) -> Desired:
    content = snapshot["kc_content"]
    kcs = {
        k["kc_id"]: {
            "kc_id": k["kc_id"],
            "subject_id": k["subject_id"],
            "stable_key": k["stable_key"],
            "name": k["name"],
            "description": content[k["kc_id"]]["description"],
            "kc_type": k["kc_type"],
            "difficulty_tier": k["difficulty_tier"],
            "misconceptions": content[k["kc_id"]]["misconceptions"] or None,
            "review_status": "approved",
            "content_version": content[k["kc_id"]]["content_version"],
        }
        for k in snapshot["kcs"]
    }
    edges = {
        (e["prerequisite_kc_id"], e["dependent_kc_id"]): {
            "prerequisite_kc_id": e["prerequisite_kc_id"],
            "dependent_kc_id": e["dependent_kc_id"],
            "strength": e["strength"],
            "reason": e["reason"],
            "review_status": "approved",
        }
        for e in snapshot["edges"]
    }
    return Desired(kcs, edges)


def _version(value: Any) -> int | None:
    match = KC_VERSION_RE.match(str(value or ""))
    return int(match["n"]) if match else None


def plan(snapshot: dict[str, Any], store: Store, lifecycle_events: list[dict[str, Any]]) -> dict:
    """The import plan (read-only). Raises `ImportAborted` if the snapshot does not verify."""
    if problems := verify_snapshot(snapshot, lifecycle_events):
        raise ImportAborted("snapshot does not verify: " + "; ".join(p.code for p in problems))
    want = desired(snapshot)
    existing = store.kcs(want.kcs)
    by_key = store.kc_ids_by_stable_key(k["stable_key"] for k in want.kcs.values())
    subjects = store.subjects({k["subject_id"] for k in want.kcs.values()})
    actions: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for kc_id, row in sorted(want.kcs.items()):
        if row["subject_id"] not in subjects:
            conflicts.append({"kc_id": kc_id, "reason": "subject_id not in the subject table"})
            continue
        owner = by_key.get(row["stable_key"])
        if owner is not None and owner != kc_id:
            conflicts.append({"kc_id": kc_id, "reason": f"stable_key belongs to {owner}"})
            continue
        old = existing.get(kc_id)
        if old is None:
            actions.append(
                {"table": "knowledge_component", "op": "insert", "key": kc_id, "values": row}
            )
            continue
        changed = {c: row[c] for c in KC_COLUMNS if old.get(c) != row[c]}
        if not changed:
            actions.append({"table": "knowledge_component", "op": "noop", "key": kc_id})
            continue
        if "stable_key" in changed and old.get("stable_key") is not None:
            conflicts.append({"kc_id": kc_id, "reason": "stable_key differs; keys never change"})
            continue
        old_v, new_v = _version(old.get("content_version")), _version(row["content_version"])
        pedagogical = [c for c in KC_PEDAGOGICAL_COLUMNS if c in changed]
        if old_v is not None and new_v is not None and new_v < old_v:
            conflicts.append({"kc_id": kc_id, "reason": "incoming content_version is older"})
        elif pedagogical and old.get("review_status") == "approved" and old_v == new_v:
            conflicts.append(
                {
                    "kc_id": kc_id,
                    "reason": f"approved KC changed {pedagogical} at the "
                    "same content_version; run the version and review procedure",
                }
            )
        else:
            actions.append(
                {
                    "table": "knowledge_component",
                    "op": "update",
                    "key": kc_id,
                    "values": changed,
                    "previous": {c: old.get(c) for c in changed},
                }
            )
    old_edges = store.edges(want.edges)
    for key, row in sorted(want.edges.items()):
        old = old_edges.get(key)
        label = "->".join(key)
        if old is None:
            actions.append({"table": "kc_edge", "op": "insert", "key": label, "values": row})
            continue
        changed = {
            c: row[c] for c in ("strength", "reason", "review_status") if old.get(c) != row[c]
        }
        actions.append(
            {
                "table": "kc_edge",
                "op": "update" if changed else "noop",
                "key": label,
                **(
                    {"values": changed, "previous": {c: old.get(c) for c in changed}}
                    if changed
                    else {}
                ),
            }
        )
    body = {
        "plan_type": "kc_graph_import_plan",
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "snapshot_seq": snapshot["seq"],
        "actions": actions,
        "conflicts": conflicts,
        "counts": {
            op: sum(1 for a in actions if a["op"] == op) for op in ("insert", "update", "noop")
        },
        "deletes": 0,
        "not_generated": [
            "kc_curriculum_map: no approved curriculum-mapping source exists",
            "content_unit_kcs: no content units exist",
        ],
    }
    body["plan_sha256"] = digest(body)
    return body


def build_approval(
    snapshot_sha256: str, plan_sha256: str, statement: str, approved_on: str
) -> dict:
    if not statement.strip():
        raise ValueError("the owner's statement is required")
    return {
        "record_type": APPROVAL_TYPE,
        "approved_by": "owner",
        "approved_on": approved_on,
        "snapshot_sha256": snapshot_sha256,
        "plan_sha256": plan_sha256,
        "target": "concepttrail.knowledge_component, concepttrail.kc_edge",
        "statement": statement.strip(),
    }


def write_approval(directory: Path, record: dict[str, Any]) -> Path:
    name = f"import_approval_{record['approved_on']}_{record['plan_sha256'][:12]}.json"
    return write_once(directory / name, record)[0]


def _apply(store: Store, body: dict[str, Any]) -> None:
    for a in body["actions"]:
        if a["op"] == "noop":
            continue
        if a["table"] == "knowledge_component":
            (
                store.insert_kc(a["values"])
                if a["op"] == "insert"
                else store.update_kc(a["key"], a["values"])
            )
        else:
            key = tuple(a["key"].split("->"))
            (
                store.insert_edge(a["values"])
                if a["op"] == "insert"
                else store.update_edge(key, a["values"])
            )


def reconcile(snapshot: dict[str, Any], store: Store) -> dict[str, Any]:
    """Read-only: does the database hold exactly the snapshot's values for its records?"""
    want = desired(snapshot)
    have_kcs, have_edges = store.kcs(want.kcs), store.edges(want.edges)
    kc_diff = sorted(
        k
        for k, row in want.kcs.items()
        if {c: (have_kcs.get(k) or {}).get(c) for c in KC_COLUMNS} != row
    )
    edge_diff = sorted(
        "->".join(k)
        for k, row in want.edges.items()
        if {c: (have_edges.get(k) or {}).get(c) for c in EDGE_COLUMNS} != row
    )
    return {
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "kcs_checked": len(want.kcs),
        "edges_checked": len(want.edges),
        "kcs_differing": kc_diff,
        "edges_differing": edge_diff,
        "matches": not kc_diff and not edge_diff,
    }


def execute(
    snapshot: dict[str, Any],
    approved_plan: dict[str, Any],
    approval: dict[str, Any],
    engine: Engine,
    lifecycle_events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply the approved plan in one transaction; raise `ImportAborted` (rolled back) otherwise."""
    if approval.get("record_type") != APPROVAL_TYPE or approval.get("approved_by") != "owner":
        raise ImportAborted("no owner import approval")
    if approval.get("snapshot_sha256") != snapshot.get("snapshot_sha256"):
        raise ImportAborted("the approval is for a different snapshot")
    if approval.get("plan_sha256") != approved_plan.get("plan_sha256"):
        raise ImportAborted("the approval is for a different plan")
    if approved_plan.get("conflicts"):
        raise ImportAborted("the plan has conflicts")
    with engine.begin() as connection:  # rolls back on any exception
        store = SqlStore(connection)
        fresh = plan(snapshot, store, lifecycle_events)
        if fresh["plan_sha256"] != approved_plan["plan_sha256"]:
            raise ImportAborted("the database changed since the plan was approved")
        _apply(store, fresh)
        check = reconcile(snapshot, store)
        if not check["matches"]:
            raise ImportAborted(f"post-import verification failed: {json.dumps(check)}")
    return {
        "audit_type": "kc_graph_import",
        "executed_at": datetime.now(UTC).isoformat(),
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "plan_sha256": fresh["plan_sha256"],
        "counts": fresh["counts"],
        "deletes": 0,
        "verification": check,
    }
