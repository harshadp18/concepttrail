"""Prerequisite-graph validation, release gating, traversal and coverage (Phase 5, deterministic).

Pure logic: no database, no FastAPI, no LLM. Edges are stored relationally (`kc_edge`) and
analysed in process with NetworkX. The service never invents edges, never infers them from
chapter order and never releases an edge a human has not approved.

Rules checked (roadmap Phase 5 pass criteria):

- unique KC IDs and stable keys;
- every edge endpoint exists (no orphan endpoints), no self-edge, no duplicate edge;
- the **approved** graph is acyclic; cycles among proposals are reported as warnings so they are
  resolved before anyone approves them;
- every approved edge has a pedagogical `reason` (enforced by the schema) and at least one
  evidence reference, and both of its KCs are themselves approved and not retired;
- release is fail-closed: `released_edges` is empty unless the whole report has no errors.

Retired KCs (lifecycle, not review status) are never nodes of a `PrerequisiteGraph`. Coverage is
scope- and lifecycle-aware: foundation KCs are reported separately and never counted under a
class, and released class coverage counts only target, approved, active KCs with class levels.

Roots are never assumed to lie in any particular class: they are whatever KCs have no approved
prerequisite.
"""

from __future__ import annotations

import collections
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

import networkx as nx

from app.schemas.knowledge import CLASS_LEVELS, EdgeRecord, KcRecord

Severity = Literal["error", "warning"]
REVIEW_ORDER = ("needs_review", "in_review", "approved", "rejected")


class UnknownKc(KeyError):
    """A KC ID that is not in the released graph."""


class GraphNotReleasable(RuntimeError):
    """The report has errors, so no graph is released."""


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    message: str
    items: tuple[str, ...] = ()


@dataclass(frozen=True)
class GraphReport:
    issues: tuple[Issue, ...]
    released_edges: tuple[EdgeRecord, ...]
    coverage: dict[str, Any]

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors

    def codes(self, severity: Severity | None = None) -> list[str]:
        return sorted({i.code for i in self.issues if severity in (None, i.severity)})


def _dupes(values: Iterable[str]) -> list[str]:
    return sorted(v for v, n in collections.Counter(values).items() if n > 1)


def _cycles(edges: Iterable[EdgeRecord]) -> list[tuple[str, ...]]:
    """One representative cycle per strongly connected component with a cycle (deterministic)."""
    graph = nx.DiGraph()
    graph.add_edges_from(sorted(e.key for e in edges))
    found = []
    for component in sorted(sorted(c) for c in nx.strongly_connected_components(graph)):
        if len(component) < 2:
            continue
        sub = graph.subgraph(component)
        start = component[0]
        cycle = [u for u, _ in nx.find_cycle(sub, source=start)]
        found.append(tuple(cycle))
    return found


def validate_graph(kcs: Iterable[KcRecord], edges: Iterable[EdgeRecord]) -> GraphReport:
    kcs, edges = list(kcs), list(edges)
    issues: list[Issue] = []

    def add(code: str, severity: Severity, message: str, items: Iterable[str] = ()) -> None:
        issues.append(Issue(code, severity, message, tuple(items)))

    # Unique identity ------------------------------------------------------------------
    if dup := _dupes(k.kc_id for k in kcs):
        add("DUPLICATE_KC_ID", "error", "KC IDs must be unique", dup)
    if dup := _dupes(k.stable_key for k in kcs):
        add("DUPLICATE_STABLE_KEY", "error", "stable keys must be unique", dup)
    by_id: dict[str, KcRecord] = {}
    for kc in kcs:
        by_id.setdefault(kc.kc_id, kc)

    # Per-edge structure ---------------------------------------------------------------
    if dup := _dupes("->".join(e.key) for e in edges):
        add("DUPLICATE_EDGE", "error", "an edge appears more than once", dup)
    if selfs := sorted(
        {e.dependent_kc_id for e in edges if e.prerequisite_kc_id == e.dependent_kc_id}
    ):
        add("SELF_EDGE", "error", "a KC cannot be its own prerequisite", selfs)
    missing = sorted(
        {x for e in edges for x in e.key if x not in by_id},
    )
    if missing:
        add(
            "MISSING_ENDPOINT",
            "error",
            "edge endpoint is not a known KC (orphan endpoint)",
            missing,
        )

    # Cycles ---------------------------------------------------------------------------
    live = [
        e
        for e in edges
        if e.review_status != "rejected"
        and e.prerequisite_kc_id != e.dependent_kc_id
        and e.prerequisite_kc_id in by_id
        and e.dependent_kc_id in by_id
    ]
    approved_live = [e for e in live if e.review_status == "approved"]
    approved_cycles = _cycles(approved_live)
    for cycle in approved_cycles:
        add("CYCLE", "error", "the approved prerequisite graph must be acyclic", cycle)
    approved_cycle_sets = {frozenset(c) for c in approved_cycles}
    for cycle in _cycles(live):
        if not any(frozenset(cycle) <= s or s <= frozenset(cycle) for s in approved_cycle_sets):
            add(
                "CYCLE_IN_PROPOSALS",
                "warning",
                "proposed edges form a cycle; resolve it before approving them",
                cycle,
            )

    # Release gate for approved edges --------------------------------------------------
    for e in approved_live:
        label = "->".join(e.key)
        if not e.evidence_refs:
            add(
                "EDGE_WITHOUT_EVIDENCE",
                "error",
                "an approved edge needs evidence references",
                [label],
            )
        for end in e.key:
            status = by_id[end].review_status
            if by_id[end].lifecycle == "retired":
                add(
                    "EDGE_TOUCHES_RETIRED_KC",
                    "error",
                    "an approved edge uses a retired KC",
                    [label, end],
                )
            if status == "rejected":
                add(
                    "EDGE_TOUCHES_REJECTED_KC",
                    "error",
                    "an approved edge uses a rejected KC",
                    [label, end],
                )
            elif status != "approved":
                add(
                    "EDGE_ENDPOINT_KC_NOT_APPROVED",
                    "error",
                    "an approved edge needs approved KCs",
                    [label, end],
                )
    for e in edges:
        if e.review_status != "approved" and not e.evidence_refs:
            add(
                "PROPOSAL_WITHOUT_EVIDENCE",
                "warning",
                "proposal has no evidence references yet",
                ["->".join(e.key)],
            )

    report_ok = not any(i.severity == "error" for i in issues)
    released = tuple(sorted(approved_live, key=lambda e: e.key)) if report_ok else ()
    return GraphReport(tuple(_ordered(issues)), released, coverage_report(kcs, edges))


def _ordered(issues: list[Issue]) -> list[Issue]:
    return sorted(issues, key=lambda i: (i.severity != "error", i.code, i.items, i.message))


# --- coverage --------------------------------------------------------------------------


def coverage_report(
    kcs: Iterable[KcRecord],
    edges: Iterable[EdgeRecord],
    curriculum_classes: Mapping[str, Iterable[int]] | None = None,
) -> dict[str, Any]:
    """Coverage by subject and class level, computed from the records as given (no judgement).

    `class_levels` on a record is the *declared* applicability. `curriculum_classes`, when given,
    is the class applicability from approved curriculum mappings (`kc_curriculum_map`); a
    declaration is never treated as a mapping, and without mappings the mapped figures are None.
    """
    by_id: dict[str, KcRecord] = {}
    for kc in kcs:
        by_id.setdefault(kc.kc_id, kc)
    edges = list(edges)
    active = {k for k, kc in by_id.items() if kc.lifecycle == "active"}
    approved = [
        e
        for e in edges
        if e.review_status == "approved"
        and e.prerequisite_kc_id in by_id
        and e.dependent_kc_id in by_id
    ]
    with_approved_edge = {x for e in approved for x in e.key}
    has_prerequisite = {e.dependent_kc_id for e in approved}
    mapped = (
        None
        if curriculum_classes is None
        else {k: frozenset(v) for k, v in curriculum_classes.items()}
    )
    subjects: dict[str, dict[str, Any]] = {}
    released: dict[str, dict[str, Any]] = {}
    for subject in sorted({k.subject_id for k in by_id.values()}):
        members = sorted(
            (k for k in by_id.values() if k.subject_id == subject), key=lambda k: k.kc_id
        )
        ids = {k.kc_id for k in members}
        live_target = [k for k in members if k.kc_id in active and k.scope == "target"]
        status_counts = collections.Counter(
            e.review_status for e in edges if e.dependent_kc_id in ids
        )
        subjects[subject] = {
            "kcs": len(members),
            "kcs_by_review_status": dict(
                sorted(collections.Counter(k.review_status for k in members).items())
            ),
            "kcs_by_class": {
                str(c): sum(1 for k in live_target if c in k.class_levels) for c in CLASS_LEVELS
            },
            "kcs_without_class_mapping": [k.kc_id for k in live_target if not k.class_levels],
            "foundation_kcs": [
                k.kc_id for k in members if k.scope == "foundation" and k.kc_id in active
            ],
            "retired_kcs": [k.kc_id for k in members if k.kc_id not in active],
            "edges_by_review_status": {s: status_counts.get(s, 0) for s in REVIEW_ORDER},
            "kcs_without_approved_edges": [
                k.kc_id for k in members if k.kc_id in active and k.kc_id not in with_approved_edge
            ],
            "roots": [
                k.kc_id for k in members if k.kc_id in active and k.kc_id not in has_prerequisite
            ],
        }
        released[subject] = _released_subject(members, active, mapped)
    cross = sum(
        1
        for e in approved
        if by_id[e.prerequisite_kc_id].subject_id != by_id[e.dependent_kc_id].subject_id
    )
    roots_by_class = {
        str(c): sorted(
            k.kc_id
            for k in by_id.values()
            if c in k.class_levels
            and k.kc_id in active
            and k.scope == "target"
            and k.kc_id not in has_prerequisite
        )
        for c in CLASS_LEVELS
    }
    foundation = sorted(
        k.kc_id for k in by_id.values() if k.scope == "foundation" and k.kc_id in active
    )
    foundation_set = set(foundation)
    return {
        "kc_count": len(by_id),
        "edge_count": len(edges),
        "approved_edge_count": len(approved),
        "cross_subject_approved_edges": cross,
        "subjects": subjects,
        "roots_by_class": roots_by_class,
        "class_basis": "declared" if mapped is None else "declared_and_mapped",
        "released_class_coverage": released,
        "foundation": {
            "count": len(foundation),
            "kc_ids": foundation,
            "roots": [k for k in foundation if k not in has_prerequisite],
            "edges_into_target": sorted(
                "->".join(e.key)
                for e in approved
                if e.prerequisite_kc_id in foundation_set
                and by_id[e.dependent_kc_id].scope == "target"
            ),
        },
    }


def _released_subject(
    members: list[KcRecord], active: set[str], mapped: dict[str, frozenset[int]] | None
) -> dict[str, Any]:
    """Released class coverage: target, approved, active KCs with declared classes only."""
    counted = [
        k
        for k in members
        if k.scope == "target"
        and k.review_status == "approved"
        and k.kc_id in active
        and k.class_levels
    ]
    classes: dict[str, dict[str, int | None]] = {}
    for c in CLASS_LEVELS:
        declared = [k for k in counted if c in k.class_levels]
        in_map = None if mapped is None else [k for k in declared if c in mapped.get(k.kc_id, ())]
        classes[str(c)] = {
            "declared_kcs": len(declared),
            "mapped_kcs": None if in_map is None else len(in_map),
            "declared_not_mapped": None if in_map is None else len(declared) - len(in_map),
        }
    target = [k for k in members if k.scope == "target"]
    return {
        "counted_kcs": len(counted),
        "foundation_kcs": sum(1 for k in members if k.scope == "foundation" and k.kc_id in active),
        "classes": classes,
        "classes_without_coverage": [
            str(c) for c in CLASS_LEVELS if classes[str(c)]["declared_kcs"] == 0
        ],
        "excluded": {
            "retired": [k.kc_id for k in target if k.kc_id not in active],
            "not_approved": [
                k.kc_id for k in target if k.kc_id in active and k.review_status != "approved"
            ],
            "no_class": [
                k.kc_id
                for k in target
                if k.kc_id in active and k.review_status == "approved" and not k.class_levels
            ],
        },
        "class_mapping_mismatches": (
            None
            if mapped is None
            else [
                k.kc_id
                for k in counted
                if k.kc_id in mapped and set(k.class_levels) != set(mapped[k.kc_id])
            ]
        ),
    }


# --- released graph --------------------------------------------------------------------


class PrerequisiteGraph:
    """Read-only view of a *released* graph. Built only from a report with no errors.

    Retired KCs are never nodes. Runtime consumers should build it from a verified released
    snapshot (`app.services.graph_snapshot.load_released_graph`), never from raw rows.
    """

    def __init__(self, kcs: Iterable[KcRecord], report: GraphReport) -> None:
        if not report.ok:
            raise GraphNotReleasable("; ".join(report.codes("error")))
        self._kcs = {k.kc_id: k for k in kcs if k.lifecycle == "active"}
        self._graph: nx.DiGraph = nx.DiGraph()
        self._graph.add_nodes_from(sorted(self._kcs))
        self._graph.add_edges_from(e.key for e in report.released_edges)

    def _check(self, kc_id: str) -> None:
        if kc_id not in self._graph:
            raise UnknownKc(kc_id)

    def prerequisites(self, kc_id: str, max_depth: int | None = None) -> list[str]:
        """All KCs that must come before `kc_id` (transitive), nearest first, then by ID."""
        self._check(kc_id)
        depth = nx.single_source_shortest_path_length(
            self._graph.reverse(copy=False), kc_id, cutoff=max_depth
        )
        return sorted((k for k in depth if k != kc_id), key=lambda k: (depth[k], k))

    def dependents(self, kc_id: str, max_depth: int | None = None) -> list[str]:
        self._check(kc_id)
        depth = nx.single_source_shortest_path_length(self._graph, kc_id, cutoff=max_depth)
        return sorted((k for k in depth if k != kc_id), key=lambda k: (depth[k], k))

    def direct_prerequisites(self, kc_id: str) -> list[str]:
        self._check(kc_id)
        return sorted(self._graph.predecessors(kc_id))

    def roots(self) -> list[str]:
        """KCs with no approved prerequisite. No class is assumed to hold them."""
        return sorted(n for n in self._graph if self._graph.in_degree(n) == 0)

    def layers(self) -> list[list[str]]:
        """Deterministic learning order: each layer depends only on earlier layers."""
        return [sorted(layer) for layer in nx.topological_generations(self._graph)]
