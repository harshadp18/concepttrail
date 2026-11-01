"""Run every loader stage and collect every finding (contract section 8). Read-only.

Stages: CSV parsing and row rules (M1), source resolution (M2), register, review log, anchors and
approvals (M3), lifecycle (M4), then the graph service (`validate_graph`) for duplicates,
endpoints, self-edges, cycles and release gating, and scope/lifecycle-aware coverage.

Validation is not approval and not release: a row that parses is never traversable on that
account. Release (`release.py`) additionally requires zero errors, a confirmed vocabulary, a
verified register and the review-log head anchored in both custody locations.
"""

from __future__ import annotations

import collections
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx
from pydantic import ValidationError

from app.schemas.knowledge import EdgeRecord, KcRecord
from app.services.audit_chain import head_hash, sha256_hex
from app.services.prerequisite_graph import GraphReport, coverage_report, validate_graph
from data_pipeline.kc_graph import contract as c
from data_pipeline.kc_graph import lifecycle, people, review_log, vocabulary
from data_pipeline.kc_graph.csv_io import read_csv
from data_pipeline.kc_graph.findings import Finding, errors, finding, sort_findings
from data_pipeline.kc_graph.keys import similar_pairs
from data_pipeline.kc_graph.rows import EdgeRow, KcRow, parse_edge, parse_kc
from data_pipeline.kc_graph.sources import Resolution, SourceIndex

# Service codes the loader reports itself, with better locations.
_SERVICE_SKIP = {"EDGE_TOUCHES_RETIRED_KC"}


@dataclass
class Inputs:
    kc_csv: Path = c.KC_CSV
    edge_csv: Path = c.EDGE_CSV
    vocabulary: Path | None = c.VOCABULARY_FILE
    review_dir: Path = c.REVIEW_DIR
    sources: SourceIndex | None = None
    allow_synthetic: bool = False
    curriculum_classes: Mapping[str, tuple[int, ...]] | None = None


@dataclass
class Result:
    findings: list[Finding]
    kcs: dict[str, KcRow]
    edges: dict[str, EdgeRow]
    vocab: vocabulary.Vocabulary
    register: people.Register | None
    review_events: list[dict[str, Any]]
    lifecycle_events: list[dict[str, Any]]
    retired: set[str]
    approving_ids: dict[str, list[str]]
    resolutions: dict[str, Resolution]
    graph: GraphReport
    inputs: dict[str, str]
    synthetic: bool
    release_blockers: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not errors(self.findings)


def _kc_record(kc: KcRow, retired: set[str]) -> KcRecord:
    values = dict(
        kc_id=kc.kc_id or f"ROW-{kc.line}",
        stable_key=kc.stable_key,
        subject_id=kc.subject_id,
        name=kc.name,
        kc_type=kc.kc_type or None,
        difficulty_tier=kc.difficulty_tier,
        review_status=kc.review_status if kc.review_status in c.REVIEW_STATUSES else "needs_review",
        class_levels=kc.declared_class_levels,
        scope=kc.scope if kc.scope in c.SCOPES else "target",
        lifecycle="retired" if kc.kc_id in retired else "active",
    )
    try:
        return KcRecord(**values)
    except ValidationError:  # already reported field by field; keep the node for edge checks
        values.update(
            stable_key=f"invalid-row-{kc.line}",
            subject_id=kc.subject_id or "unknown",
            name=kc.name or "(missing)",
        )
        return KcRecord(**values)


def _edge_record(edge: EdgeRow, approving: list[str]) -> EdgeRecord:
    evidence = tuple(t.raw for t in edge.evidence_refs) + tuple(f"rev:{i}" for i in approving)
    values = dict(
        prerequisite_kc_id=edge.prerequisite_kc_id or f"ROW-{edge.line}-P",
        dependent_kc_id=edge.dependent_kc_id or f"ROW-{edge.line}-D",
        reason=edge.reason or "(missing)",
        strength=edge.strength,
        evidence_refs=evidence,
        review_status=edge.review_status
        if edge.review_status in c.REVIEW_STATUSES
        else "needs_review",
    )
    return EdgeRecord(**values)


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(c.PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name


def run(inputs: Inputs) -> Result:
    findings: list[Finding] = []
    vocab, notes = vocabulary.load(inputs.vocabulary)
    findings += notes
    vocab = vocab or vocabulary.provisional()  # parse anyway; VOCABULARY_INVALID blocks release
    if vocab.synthetic and not inputs.allow_synthetic:
        findings.append(
            finding(
                "SYNTHETIC_DATA",
                "a synthetic vocabulary cannot be used for a real run",
                file="vocabulary",
            )
        )

    # M1: files and rows --------------------------------------------------------------------
    kc_rows, f1, kc_bytes = read_csv(inputs.kc_csv, c.KC_HEADER, "kc_csv")
    edge_rows, f2, edge_bytes = read_csv(inputs.edge_csv, c.EDGE_HEADER, "edge_csv")
    findings += f1 + f2
    all_kcs: list[KcRow] = []
    for row in kc_rows:
        kc, f = parse_kc(row, vocab)
        all_kcs.append(kc)
        findings += f
    all_edges: list[EdgeRow] = []
    for row in edge_rows:
        edge, f = parse_edge(row, vocab)
        all_edges.append(edge)
        findings += f
    kcs: dict[str, KcRow] = {}
    for kc in all_kcs:
        kcs.setdefault(kc.kc_id, kc)
    edges: dict[str, EdgeRow] = {}
    for edge in all_edges:
        edges.setdefault(edge.key, edge)
    findings += _cross_row_checks(all_kcs, edges, kcs)

    # M2: sources --------------------------------------------------------------------------
    resolutions: dict[str, Resolution] = {}
    tokens = [(k.line, k.kc_id, "kc_csv", "source_refs", t) for k in all_kcs for t in k.source_refs]
    tokens += [
        (e.line, e.key, "edge_csv", "evidence_refs", t) for e in all_edges for t in e.evidence_refs
    ]
    if tokens and inputs.sources is None:
        findings.append(
            finding(
                "SOURCE_INDEX_UNAVAILABLE", "source references were not resolved", file="sources"
            )
        )
    elif inputs.sources is not None:
        for line, record, label, column, token in tokens:
            resolution, f = inputs.sources.resolve(
                token, label=label, record=record, column=column, line=line
            )
            findings += f
            if resolution is not None:
                resolutions[token.raw] = resolution
        findings += inputs.sources.document_findings(t[4].source_id for t in tokens)

    # M3: register and review log -------------------------------------------------------------
    review_path = inputs.review_dir / c.REVIEW_LOG.name
    review_events, f = review_log.read_jsonl(review_path, "review_log")
    findings += f
    decided = any(r.review_status in c.DECIDED_STATUSES for r in [*all_kcs, *all_edges])
    register_path = inputs.review_dir / c.REGISTER_FILE.name
    register = None
    if decided or review_events or register_path.exists():
        register, f = people.load(register_path, allow_synthetic=inputs.allow_synthetic)
        findings += f
    if register is not None:
        for row in [*all_kcs, *all_edges]:
            if row.author_id and row.author_id not in register.people:
                record = getattr(row, "kc_id", None) or row.key  # type: ignore[union-attr]
                label = "kc_csv" if isinstance(row, KcRow) else "edge_csv"
                findings.append(
                    finding(
                        "AUTHOR_UNKNOWN",
                        f"{row.author_id} is not registered",
                        file=label,
                        line=row.line,
                        record=record,
                        field="author_id",
                    )
                )
    findings += review_log.chain_findings(review_events, c.REVIEW_ID_PREFIX, "review_log")
    custody, _why = review_log.load_custody(inputs.review_dir / c.CUSTODY_FILE.name)
    anchor_sets = {"local": review_log.read_anchors(inputs.review_dir / c.ANCHOR_DIR.name)}
    if custody is not None:
        anchor_sets.update({label: review_log.read_anchors(d) for label, d in custody.locations})
    findings += review_log.anchor_findings(review_events, anchor_sets, "review_log")
    state = review_log.State(kcs, edges, resolutions, register)
    f, approving = review_log.verify_records(
        review_events, state, allow_synthetic=inputs.allow_synthetic
    )
    findings += f

    # M4: lifecycle -------------------------------------------------------------------------
    lifecycle_path = inputs.review_dir / c.LIFECYCLE_LOG.name
    lifecycle_events, f = review_log.read_jsonl(lifecycle_path, lifecycle.LABEL)
    findings += f
    findings += review_log.chain_findings(lifecycle_events, c.LIFECYCLE_ID_PREFIX, lifecycle.LABEL)
    lc_anchors = {
        "local": review_log.read_anchors(inputs.review_dir / c.ANCHOR_DIR.name, "lifecycle-anchor")
    }
    if custody is not None:
        lc_anchors.update(
            {
                label: review_log.read_anchors(d, "lifecycle-anchor")
                for label, d in custody.locations
            }
        )
    findings += review_log.anchor_findings(lifecycle_events, lc_anchors, lifecycle.LABEL)
    retired, f = lifecycle.verify(lifecycle_events, kcs, edges, register)
    findings += f

    # Graph service (reused) --------------------------------------------------------------------
    kc_records = [_kc_record(k, retired) for k in all_kcs]
    edge_records = [_edge_record(e, approving.get(e.key, [])) for e in all_edges]
    graph = validate_graph(kc_records, edge_records)
    coverage = coverage_report(kc_records, edge_records, inputs.curriculum_classes)
    graph = GraphReport(graph.issues, graph.released_edges, coverage)
    for issue in graph.issues:
        if issue.code not in _SERVICE_SKIP:
            findings.append(
                finding(issue.code, issue.message, file="graph", record=";".join(issue.items))
            )
    findings += _graph_warnings(kcs, edges, retired)
    if inputs.curriculum_classes is not None:
        for kc_ids in (
            s["class_mapping_mismatches"] or []
            for s in coverage["released_class_coverage"].values()
        ):
            for kc_id in kc_ids:
                findings.append(
                    finding(
                        "CLASS_MAPPING_MISMATCH",
                        "declared classes differ from mapped classes",
                        file="kc_csv",
                        line=kcs[kc_id].line,
                        record=kc_id,
                        field="declared_class_levels",
                    )
                )

    synthetic = bool(
        inputs.allow_synthetic
        and (
            (register is not None and register.synthetic)
            or vocab.synthetic
            or (inputs.sources is not None and inputs.sources.synthetic)
        )
    )
    result = Result(
        findings=sort_findings(findings),
        kcs=kcs,
        edges=edges,
        vocab=vocab,
        register=register,
        review_events=review_events,
        lifecycle_events=lifecycle_events,
        retired=retired,
        approving_ids=approving,
        resolutions=resolutions,
        graph=graph,
        inputs={
            "kc_csv": _display(inputs.kc_csv),
            "kc_csv_sha256": sha256_hex(kc_bytes),
            "edge_csv": _display(inputs.edge_csv),
            "edge_csv_sha256": sha256_hex(edge_bytes),
            "review_log_head": head_hash(review_events),
            "review_log_events": str(len(review_events)),
            "lifecycle_log_head": head_hash(lifecycle_events),
            "lifecycle_log_events": str(len(lifecycle_events)),
            "register_sha256": register.sha256 if register else "",
            "register_verification": (register.verification or "") if register else "",
        },
        synthetic=synthetic,
    )
    result.release_blockers = release_blockers(result, inputs.review_dir)
    return result


def release_blockers(result: Result, review_dir: Path) -> list[str]:
    """Why a release would be refused right now (empty means it would proceed)."""
    out = []
    if not result.ok:
        out.append(f"{len(errors(result.findings))} validation errors")
    if not result.vocab.confirmed:
        out.append("VOCABULARY_NOT_CONFIRMED: the owner has not confirmed the vocabulary file (R3)")
    if result.review_events:
        custody, why = review_log.load_custody(review_dir / c.CUSTODY_FILE.name)
        for f in review_log.head_anchor_findings(result.review_events, custody, why, "review_log"):
            out.append(f"{f.code}: {f.message}")
        for f in review_log.head_anchor_findings(
            result.lifecycle_events, custody, why, "lifecycle_log", "lifecycle-anchor"
        ):
            out.append(f"{f.code}: {f.message}")
    if result.synthetic:
        out.append("SYNTHETIC_DATA: synthetic inputs can be dry-run but never released for use")
    if not any(k.review_status == "approved" for k in result.kcs.values()):
        out.append("nothing approved to release")
    return out


def _cross_row_checks(
    all_kcs: list[KcRow], edges: dict[str, EdgeRow], kcs: dict[str, KcRow]
) -> list[Finding]:
    out = []
    keys = {k.stable_key for k in all_kcs if k.stable_key}
    alias_owner: dict[str, list[KcRow]] = collections.defaultdict(list)
    for kc in all_kcs:
        for alias in kc.aliases:
            alias_owner[alias].append(kc)
    for alias, owners in sorted(alias_owner.items()):
        if len(owners) > 1:
            for kc in owners:
                out.append(
                    finding(
                        "DUPLICATE_ALIAS",
                        f"alias {alias!r} is used more than once",
                        file="kc_csv",
                        line=kc.line,
                        record=kc.kc_id,
                        field="aliases",
                    )
                )
        if alias in keys:
            for kc in owners:
                out.append(
                    finding(
                        "ALIAS_COLLIDES_WITH_KEY",
                        f"alias {alias!r} equals a stable key",
                        file="kc_csv",
                        line=kc.line,
                        record=kc.kc_id,
                        field="aliases",
                    )
                )
    by_key = {k.stable_key: k for k in all_kcs}
    for a, b in similar_pairs(keys):
        out.append(
            finding(
                "SIMILAR_KEY",
                f"{a} and {b} look alike; record why they differ",
                file="kc_csv",
                line=by_key[b].line,
                record=by_key[b].kc_id,
                field="stable_key",
            )
        )
    names: dict[tuple[str, str], list[KcRow]] = collections.defaultdict(list)
    for kc in all_kcs:
        if kc.name:
            names[(kc.subject_id, kc.name.casefold())].append(kc)
    for group in names.values():
        if len(group) > 1:
            for kc in group[1:]:
                out.append(
                    finding(
                        "DUPLICATE_NAME",
                        f"same name as {group[0].kc_id}",
                        file="kc_csv",
                        line=kc.line,
                        record=kc.kc_id,
                        field="name",
                    )
                )
    for key, edge in sorted(edges.items()):
        p, d = kcs.get(edge.prerequisite_kc_id), kcs.get(edge.dependent_kc_id)
        if p is None or d is None:
            continue
        if d.scope == "foundation" and p.scope == "target":
            out.append(
                finding(
                    "FOUNDATION_DEPENDS_ON_TARGET",
                    "a foundation KC cannot depend on a Class 6-10 KC; check the direction",
                    file="edge_csv",
                    line=edge.line,
                    record=key,
                )
            )
        if p.subject_id != d.subject_id:
            out.append(
                finding(
                    "CROSS_SUBJECT_EDGE",
                    "the endpoints are in different subjects",
                    file="edge_csv",
                    line=edge.line,
                    record=key,
                )
            )
        if (
            p.declared_class_levels
            and d.declared_class_levels
            and min(p.declared_class_levels) > max(d.declared_class_levels)
        ):
            out.append(
                finding(
                    "EDGE_AGAINST_CLASS_ORDER",
                    "the prerequisite is declared only for "
                    "later classes than the dependent; check the direction",
                    file="edge_csv",
                    line=edge.line,
                    record=key,
                )
            )
    return out


def _graph_warnings(
    kcs: dict[str, KcRow], edges: dict[str, EdgeRow], retired: set[str]
) -> list[Finding]:
    out = []
    touched = {x for e in edges.values() for x in (e.prerequisite_kc_id, e.dependent_kc_id)}
    for kc_id, kc in sorted(kcs.items()):
        if kc_id in retired:
            continue
        if kc_id not in touched:
            out.append(
                finding(
                    "KC_WITHOUT_EDGES",
                    "no prerequisite edge touches this KC",
                    file="kc_csv",
                    line=kc.line,
                    record=kc_id,
                )
            )
        if kc.scope == "foundation" and not any(
            e.prerequisite_kc_id == kc_id
            and kcs.get(e.dependent_kc_id) is not None
            and kcs[e.dependent_kc_id].scope == "target"
            for e in edges.values()
        ):
            out.append(
                finding(
                    "FOUNDATION_WITHOUT_TARGET_EDGE",
                    "a foundation KC that no Class 6-10 KC depends on",
                    file="kc_csv",
                    line=kc.line,
                    record=kc_id,
                )
            )
    approved = nx.DiGraph()
    approved.add_edges_from(
        (e.prerequisite_kc_id, e.dependent_kc_id)
        for e in edges.values()
        if e.review_status == "approved"
    )
    if nx.is_directed_acyclic_graph(approved):
        reduced = nx.transitive_reduction(approved)
        for u, v in sorted(set(approved.edges) - set(reduced.edges)):
            key = f"{u}->{v}"
            out.append(
                finding(
                    "REDUNDANT_EDGE",
                    "already implied by a longer approved path",
                    file="edge_csv",
                    line=edges[key].line,
                    record=key,
                )
            )
    return out
