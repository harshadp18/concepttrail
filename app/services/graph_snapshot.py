"""Released prerequisite-graph snapshots: verification and fail-closed loading (Phase 5, D15).

Runtime consumers never traverse raw KC and edge rows. They load a snapshot written by a passing
`data_pipeline.kc_graph` release and verify it here against the current lifecycle log. Any
problem means **no graph**: `load_released_graph` returns None and the caller serves no
remediation graph and escalates to the teacher. It never falls back to unfiltered rows.

Pure logic: no database, FastAPI or provider imports. How the snapshot file reaches a remote
runtime is an open owner choice (R1); this module only verifies what it is given.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.schemas.knowledge import EdgeRecord, KcRecord
from app.services.audit_chain import digest, head_hash, verify_chain
from app.services.prerequisite_graph import PrerequisiteGraph, validate_graph

SNAPSHOT_FORMAT = "concepttrail-kc-graph-snapshot-v1"
LIFECYCLE_ID_PREFIX = "LC-"
DIGEST_FIELD = "snapshot_sha256"


@dataclass(frozen=True)
class SnapshotProblem:
    code: str
    message: str
    items: tuple[str, ...] = ()


def snapshot_digest(snapshot: dict[str, Any]) -> str:
    return digest({k: v for k, v in snapshot.items() if k != DIGEST_FIELD})


def retired_state(lifecycle_events: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """KC ID -> the retire event currently in force (a later reinstate clears it)."""
    state: dict[str, dict[str, Any]] = {}
    for event in lifecycle_events:
        if event.get("action") == "retire":
            state[event["kc_id"]] = event
        elif event.get("action") == "reinstate":
            state.pop(event.get("kc_id"), None)
    return state


def verify_snapshot(
    snapshot: dict[str, Any], lifecycle_events: Sequence[dict[str, Any]]
) -> list[SnapshotProblem]:
    """Every reason the snapshot must not be used; empty means it may be loaded."""
    problems: list[SnapshotProblem] = []

    def add(code: str, message: str, items: Sequence[str] = ()) -> None:
        problems.append(SnapshotProblem(code, message, tuple(items)))

    if snapshot.get("format") != SNAPSHOT_FORMAT:
        add("SNAPSHOT_INVALID", "unknown snapshot format")
        return problems
    if snapshot.get(DIGEST_FIELD) != snapshot_digest(snapshot):
        add("SNAPSHOT_DIGEST_MISMATCH", "the snapshot digest does not verify")
        return problems
    if chain := verify_chain(lifecycle_events, LIFECYCLE_ID_PREFIX):
        add("LOG_CHAIN_BROKEN", "the lifecycle log chain is broken", [p.message for p in chain])
        return problems
    if snapshot.get("lifecycle_log_head") != head_hash(lifecycle_events):
        add(
            "SNAPSHOT_LIFECYCLE_MISMATCH",
            "the snapshot was released against a different lifecycle log head",
        )
    try:
        kcs = [KcRecord(**k) for k in snapshot["kcs"]]
        edges = [EdgeRecord(**e) for e in snapshot["edges"]]
    except (KeyError, TypeError, ValueError) as exc:
        add("SNAPSHOT_INVALID", f"snapshot records do not validate: {exc.__class__.__name__}")
        return problems

    in_force = retired_state(lifecycle_events)
    declared = {r["kc_id"]: r for r in snapshot.get("retired_kcs", [])}
    for kc_id, record in sorted(declared.items()):
        event = in_force.get(kc_id)
        if event is None or event.get("event_id") != record.get("lifecycle_event_id"):
            add("LIFECYCLE_MISSING", "no retirement record in force for an excluded KC", [kc_id])
        elif event.get("kc_row_digest") != record.get("kc_row_digest"):
            add("LIFECYCLE_STALE", "the retirement record's KC digest is stale", [kc_id])
    if missing := sorted(set(in_force) - set(declared)):
        add(
            "SNAPSHOT_LIFECYCLE_MISMATCH",
            "KCs retired in the lifecycle log are not excluded by the snapshot",
            missing,
        )

    retired = set(in_force) | set(declared)
    node_ids = {k.kc_id for k in kcs}
    if bad := sorted(
        {k.kc_id for k in kcs if k.kc_id in retired or k.lifecycle != "active"}
        | {x for e in edges for x in e.key if x in retired}
    ):
        add("RETIRED_KC_IN_PATH", "a retired KC appears in the traversable graph", bad)
    if bad := sorted(k.kc_id for k in kcs if k.review_status != "approved"):
        add("EDGE_ENDPOINT_KC_NOT_APPROVED", "a snapshot KC is not approved", bad)
    if bad := sorted("->".join(e.key) for e in edges if e.review_status != "approved"):
        add("SNAPSHOT_INVALID", "a snapshot edge is not approved", bad)
    if bad := sorted({x for e in edges for x in e.key if x not in node_ids}):
        add("MISSING_ENDPOINT", "a snapshot edge endpoint is not a snapshot KC", bad)
    report = validate_graph(kcs, edges)
    for issue in report.errors:
        add(issue.code, issue.message, issue.items)
    return problems


def load_released_graph(
    snapshot: dict[str, Any], lifecycle_events: Sequence[dict[str, Any]]
) -> PrerequisiteGraph | None:
    """The released graph, or None (no remediation graph; escalate to the teacher)."""
    if verify_snapshot(snapshot, lifecycle_events):
        return None
    kcs = [KcRecord(**k) for k in snapshot["kcs"]]
    edges = [EdgeRecord(**e) for e in snapshot["edges"]]
    return PrerequisiteGraph(kcs, validate_graph(kcs, edges))
