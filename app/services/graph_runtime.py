"""Runtime access to the released prerequisite graph (reuses `graph_snapshot` and the engine).

The only graph a learner-facing service may traverse is the latest released snapshot that
verifies against the current lifecycle log. Otherwise the result is `GraphUnavailable` with a
reason (no snapshot released, or verification failed) and callers must not recommend from KCs.
No approved KC or edge is ever created here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT
from app.core.content_release import demo_enabled, servable_review_statuses
from app.db.models import (
    CurriculumItem,
    CurriculumVersion,
    KcCurriculumMap,
    KcEdge,
    KnowledgeComponent,
)
from app.schemas.knowledge import EdgeRecord, KcRecord
from app.services.graph_snapshot import load_released_graph, verify_snapshot
from app.services.prerequisite_graph import PrerequisiteGraph, UnknownKc, validate_graph

FINAL_DIR = PROJECT_ROOT / "data_pipeline/data/final/kc_graph"
LIFECYCLE_LOG = PROJECT_ROOT / "data_pipeline/data/overrides/kc_review/lifecycle_log.jsonl"
_SNAPSHOT = re.compile(r"^released_graph_(\d+)\.json$")


@dataclass(frozen=True)
class GraphUnavailable:
    reason: str
    detail: tuple[str, ...] = ()
    available: bool = False


@dataclass(frozen=True)
class ReleasedGraph:
    graph: PrerequisiteGraph
    seq: int
    snapshot_sha256: str
    kcs: dict[str, dict[str, Any]]
    available: bool = True
    kind: str = "production"  # "demo": AI-generated demo graph, never a production release

    @property
    def version(self) -> str:
        if self.kind == "demo":
            return f"demo_graph@{self.snapshot_sha256[:12]}"
        return f"released_graph_{self.seq}@{self.snapshot_sha256[:12]}"


def _lifecycle(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def get_released_graph(
    final_dir: Path = FINAL_DIR, lifecycle_log: Path = LIFECYCLE_LOG
) -> ReleasedGraph | GraphUnavailable:
    snapshots = (
        sorted(
            (int(m.group(1)), p)
            for p in final_dir.glob("released_graph_*.json")
            if (m := _SNAPSHOT.match(p.name))
        )
        if final_dir.is_dir()
        else []
    )
    if not snapshots:
        return GraphUnavailable("graph_not_released")
    seq, path = snapshots[-1]
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        events = _lifecycle(lifecycle_log)
    except (OSError, json.JSONDecodeError):
        return GraphUnavailable("snapshot_unreadable")
    problems = verify_snapshot(snapshot, events)
    graph = None if problems else load_released_graph(snapshot, events)
    if graph is None:
        return GraphUnavailable(
            "snapshot_failed_verification", tuple(sorted({p.code for p in problems}))
        )
    return ReleasedGraph(
        graph, seq, snapshot["snapshot_sha256"], {k["kc_id"]: k for k in snapshot["kcs"]}
    )


def get_prerequisites(
    released: ReleasedGraph | GraphUnavailable, kc_id: str, *, direct: bool = False
) -> list[str] | GraphUnavailable:
    if not isinstance(released, ReleasedGraph):
        return released
    try:
        return (
            released.graph.direct_prerequisites(kc_id)
            if direct
            else released.graph.prerequisites(kc_id)
        )
    except UnknownKc:
        return GraphUnavailable("kc_not_in_released_graph", (kc_id,))


@dataclass(frozen=True)
class PathCheck:
    valid: bool
    problems: tuple[str, ...]


def validate_learning_path(
    released: ReleasedGraph | GraphUnavailable, path: list[str]
) -> PathCheck | GraphUnavailable:
    """A path is valid when every KC is released and each KC's direct prerequisites appear
    earlier in the path or are listed in `path` order before it (no KC before its prerequisite)."""
    if not isinstance(released, ReleasedGraph):
        return released
    problems = []
    position = {k: i for i, k in enumerate(path)}
    if len(position) != len(path):
        problems.append("path repeats a KC")
    for index, kc_id in enumerate(path):
        if kc_id not in released.kcs:
            problems.append(f"{kc_id} is not in the released graph")
            continue
        for pre in released.graph.direct_prerequisites(kc_id):
            if pre in position and position[pre] > index:
                problems.append(f"{kc_id} comes before its prerequisite {pre}")
    return PathCheck(not problems, tuple(problems))


def get_demo_graph(session: Session) -> ReleasedGraph | GraphUnavailable:
    """The AI-generated DEMO graph from `demo_release`/approved rows; demo mode only.

    It is checked by the same engine (unique IDs, endpoints, self-edges, acyclicity) and is
    labelled `demo_graph@...`. It never reads or replaces a production snapshot.
    """
    if not demo_enabled():
        return GraphUnavailable("demo_mode_disabled")
    statuses = servable_review_statuses()
    rows = session.scalars(
        select(KnowledgeComponent).where(KnowledgeComponent.review_status.in_(statuses))
    ).all()
    classes: dict[str, set[int]] = {}
    for kc_id, level in session.execute(
        select(KcCurriculumMap.kc_id, CurriculumVersion.class_level)
        .join(CurriculumItem, CurriculumItem.item_id == KcCurriculumMap.item_id)
        .join(
            CurriculumVersion,
            CurriculumVersion.curriculum_version_id == CurriculumItem.curriculum_version_id,
        )
        .where(KcCurriculumMap.review_status.in_(statuses))
    ):
        if level is not None:
            classes.setdefault(kc_id, set()).add(int(level))
    kcs = [
        KcRecord(
            kc_id=k.kc_id,
            stable_key=k.stable_key or k.kc_id.lower(),
            subject_id=k.subject_id or "unknown",
            name=k.name or k.kc_id,
            kc_type=k.kc_type,
            difficulty_tier=k.difficulty_tier,
            review_status="approved",
            class_levels=tuple(sorted(classes.get(k.kc_id, ()))),
        )
        for k in rows
    ]
    ids = {k.kc_id for k in kcs}
    edges = [
        EdgeRecord(
            prerequisite_kc_id=e.prerequisite_kc_id,
            dependent_kc_id=e.dependent_kc_id,
            reason=e.reason or "demo",
            strength=e.strength,
            evidence_refs=("demo",),
            review_status="approved",
        )
        for e in session.scalars(select(KcEdge).where(KcEdge.review_status.in_(statuses)))
        if e.prerequisite_kc_id in ids and e.dependent_kc_id in ids
    ]
    if not kcs:
        return GraphUnavailable("demo_graph_empty")
    report = validate_graph(kcs, edges)
    if not report.ok:
        return GraphUnavailable("demo_graph_invalid", tuple(report.codes("error")))
    digest = hashlib.sha256(
        json.dumps([sorted(ids), sorted(e.key for e in edges)]).encode()
    ).hexdigest()
    return ReleasedGraph(
        PrerequisiteGraph(kcs, report),
        0,
        digest,
        {k.kc_id: k.model_dump() for k in kcs},
        kind="demo",
    )


def get_runtime_graph(session: Session) -> ReleasedGraph | GraphUnavailable:
    """Production: the verified released snapshot only. Demo mode: the demo graph."""
    return get_demo_graph(session) if demo_enabled() else get_released_graph()
