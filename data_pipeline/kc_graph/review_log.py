"""Append-only, hash-chained review log, anchors and approval verification (D12, D13), M3.

`overrides/kc_review/review_log.jsonl`: one event per line (guidelines, section 4). The person
entering a review supplies only the reviewer fields (`contract.REVIEWER_FIELDS`); this module
adds the tool fields (`seq`, `event_id`, `recorded_at`, digests, versions, passage digests,
`basis`, chain hashes) and appends. Nothing here generates a reviewer, decision or rationale.

**Tamper-evident, not immutable storage.** The chain detects interior edits, deletions and
reordering; truncation and whole-log replacement are detected only against anchors kept in two
owner-designated custody locations outside the repository (`custody.json`, R2). The local
`anchors/` copy is a convenience, never custody.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.audit_chain import head_hash, seal, verify_chain
from data_pipeline.kc_graph import contract as c
from data_pipeline.kc_graph.digests import (
    edge_pedagogical_digest,
    full_digest,
    kc_pedagogical_digest,
)
from data_pipeline.kc_graph.findings import Finding, finding
from data_pipeline.kc_graph.people import Register
from data_pipeline.kc_graph.rows import EdgeRow, KcRow
from data_pipeline.kc_graph.sources import Resolution
from data_pipeline.teacher_validation import write_once

EVENT_REF_RE = re.compile(r"\bRR-(\d{4,})\b")
ANCHOR_RE = re.compile(r"^anchor-(\d+)\.json$")
LABEL = "review_log"


# --- reading and chain -------------------------------------------------------------------


def read_jsonl(path: Path, label: str) -> tuple[list[dict[str, Any]], list[Finding]]:
    if not path.exists():
        return [], []
    events, findings = [], []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            findings.append(
                finding("LOG_INVALID", f"line is not JSON: {exc.msg}", file=label, line=number)
            )
            value = {"_unreadable": line}
        events.append(value)
    return events, findings


def chain_findings(events: Sequence[dict[str, Any]], prefix: str, label: str) -> list[Finding]:
    return [
        finding("LOG_CHAIN_BROKEN", p.message, file=label, line=p.seq)
        for p in verify_chain(events, prefix)
    ]


def append(path: Path, event: dict[str, Any], prefix: str) -> dict[str, Any]:
    """Seal `event` after the existing log and append one line. Refuses a broken log."""
    events, problems = read_jsonl(path, "log")
    if problems or verify_chain(events, prefix):
        raise RuntimeError(f"{path.name} does not verify; refusing to append")
    sealed = seal(event, events, prefix)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(sealed, ensure_ascii=False, sort_keys=True) + "\n")
    return sealed


# --- anchors and custody -------------------------------------------------------------------


@dataclass(frozen=True)
class Custody:
    locations: tuple[tuple[str, Path], ...]  # (label, directory)


def load_custody(path: Path, project_root: Path = c.PROJECT_ROOT) -> tuple[Custody | None, str]:
    """The owner's custody configuration, or (None, why not)."""
    if not path.exists():
        return None, "no custody configuration (owner choice R2)"
    data = json.loads(path.read_text(encoding="utf-8"))
    locations = [
        (str(x.get("label", "")), Path(x.get("path", ""))) for x in data.get("locations", [])
    ]
    if len(locations) < 2 or len({p.resolve() for _, p in locations}) < 2:
        return None, "two distinct custody locations are required"
    for label, location in locations:
        if not location.is_absolute():
            return None, f"custody location {label!r} must be an absolute path"
        resolved = location.resolve()
        if resolved == project_root.resolve() or project_root.resolve() in resolved.parents:
            return None, f"custody location {label!r} is inside the repository"
    return Custody(tuple(locations)), ""


def anchor_record(events: Sequence[dict[str, Any]], recorded_at: str) -> dict[str, Any]:
    if not events:
        raise ValueError("nothing to anchor")
    last = events[-1]
    return {
        "seq": last["seq"],
        "event_id": last["event_id"],
        "head_hash": last["event_hash"],
        "event_count": len(events),
        "recorded_at": recorded_at,
    }


def write_anchor(
    directories: Iterable[Path], record: dict[str, Any], stem: str = "anchor"
) -> list[Path]:
    """Write-once to every directory; an existing anchor is never overwritten."""
    return [write_once(d / f"{stem}-{record['seq']}.json", record)[0] for d in directories]


def read_anchors(directory: Path, stem: str = "anchor") -> list[dict[str, Any]]:
    pattern = re.compile(rf"^{stem}-(\d+)\.json$")
    if not directory.is_dir():
        return []
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(directory.iterdir())
        if pattern.match(p.name)
    ]


def anchor_findings(
    events: Sequence[dict[str, Any]], anchor_sets: dict[str, list[dict[str, Any]]], label: str
) -> list[Finding]:
    """Every anchor must match the log at its `seq`; a higher `seq` means truncation."""
    out = []
    for location, anchors in sorted(anchor_sets.items()):
        for anchor in anchors:
            seq = anchor.get("seq")
            if not isinstance(seq, int) or seq < 1:
                out.append(
                    finding("LOG_ANCHOR_MISMATCH", f"{location}: malformed anchor", file=label)
                )
            elif seq > len(events):
                out.append(
                    finding(
                        "LOG_ANCHOR_MISMATCH",
                        f"{location}: anchor at seq {seq} but "
                        f"the log has {len(events)} events (truncated or replaced)",
                        file=label,
                    )
                )
            elif events[seq - 1].get("event_hash") != anchor.get("head_hash") or events[
                seq - 1
            ].get("event_id") != anchor.get("event_id"):
                out.append(
                    finding(
                        "LOG_ANCHOR_MISMATCH",
                        f"{location}: the log differs from the anchor at seq {seq}",
                        file=label,
                    )
                )
    return out


def head_anchor_findings(
    events: Sequence[dict[str, Any]],
    custody: Custody | None,
    why: str,
    label: str,
    stem: str = "anchor",
) -> list[Finding]:
    """Release gate: the current head must be anchored in every custody location."""
    if not events:
        return []
    if custody is None:
        return [finding("CUSTODY_NOT_CONFIGURED", why, file=label)]
    out = []
    for location, directory in custody.locations:
        if not any(
            a.get("seq") == len(events) and a.get("head_hash") == head_hash(events)
            for a in read_anchors(directory, stem)
        ):
            out.append(
                finding(
                    "LOG_ANCHOR_MISSING",
                    f"custody location {location!r} has no anchor of the current head",
                    file=label,
                )
            )
    return out


# --- building events ---------------------------------------------------------------------


@dataclass
class State:
    """Current rows and resolutions the review log is checked against."""

    kcs: dict[str, KcRow]
    edges: dict[str, EdgeRow]
    resolutions: dict[str, Resolution]
    register: Register | None

    def kc_versions(self, kc_ids: Iterable[str]) -> dict[str, str]:
        return {k: self.kcs[k].content_version for k in kc_ids if k in self.kcs}

    def current(self, record_type: str, key: str) -> tuple[str, str, dict[str, str]] | None:
        """(full digest, pedagogical digest, versions) of a record as it is now."""
        if record_type == "kc" and key in self.kcs:
            kc = self.kcs[key]
            return full_digest(kc.cells), kc_pedagogical_digest(kc), self.kc_versions([key])
        if record_type == "edge" and key in self.edges:
            edge = self.edges[key]
            return (
                full_digest(edge.cells),
                edge_pedagogical_digest(edge),
                self.kc_versions([edge.prerequisite_kc_id, edge.dependent_kc_id]),
            )
        return None


def build_event(entry: dict[str, Any], state: State, recorded_at: str, *, synthetic: bool) -> dict:
    """Validate a reviewer's entry and add the tool fields (not yet chained)."""
    if extra := sorted(set(entry) - set(c.REVIEWER_FIELDS)):
        raise ValueError(f"fields the reviewer may not set: {extra}")
    for name in (
        "event_type",
        "record_type",
        "record_key",
        "decision",
        "reviewer_id",
        "decided_on",
    ):
        if not entry.get(name):
            raise ValueError(f"{name} is required")
    if entry["event_type"] not in c.EVENT_TYPES or entry["decision"] not in c.DECISIONS:
        raise ValueError("unknown event_type or decision")
    current = state.current(entry["record_type"], entry["record_key"])
    if current is None:
        raise ValueError(f"no current {entry['record_type']} {entry['record_key']}")
    event = {k: entry[k] for k in c.REVIEWER_FIELDS if k in entry}
    event.setdefault("supersedes", [])
    assessments = []
    for item in entry.get("evidence_assessment", []):
        resolution = state.resolutions.get(item.get("token", ""))
        if resolution is None:
            raise ValueError(f"evidence token {item.get('token')!r} does not resolve")
        assessments.append(
            {
                **item,
                "source_sha256": resolution.source_sha256,
                "passage_sha256": resolution.passage_sha256,
            }
        )
    if assessments:
        event["evidence_assessment"] = assessments
    event.update(
        recorded_at=recorded_at,
        row_digest=current[0],
        pedagogical_digest=current[1],
        versions=current[2],
        basis=c.EVENT_BASIS,
    )
    if synthetic:
        event["synthetic"] = True
    problems = event_problems(event, state, seq=None)
    if problems:
        raise ValueError("; ".join(f"{code}: {message}" for code, message in problems))
    return event


def _subjects(state: State, record_type: str, key: str) -> set[str]:
    if record_type == "kc":
        return {state.kcs[key].subject_id} if key in state.kcs else set()
    edge = state.edges.get(key)
    if edge is None:
        return set()
    return {
        state.kcs[k].subject_id
        for k in (edge.prerequisite_kc_id, edge.dependent_kc_id)
        if k in state.kcs
    }


def _author(state: State, record_type: str, key: str) -> str:
    row = state.kcs.get(key) if record_type == "kc" else state.edges.get(key)
    return row.author_id if row is not None else ""


def event_problems(event: dict[str, Any], state: State, seq: int | None) -> list[tuple[str, str]]:
    """Problems with one event on its own (who, rationale, references), not freshness."""
    out = []
    kind, key, decision = event.get("record_type"), event.get("record_key"), event.get("decision")
    reviewer = event.get("reviewer_id", "")
    if event.get("basis") != c.EVENT_BASIS:
        out.append(
            (
                "REVIEW_NOT_INDIVIDUAL",
                "not an individual review (an owner attestation or "
                "blanket record can never approve)",
            )
        )
    if state.register is None:
        out.append(("REVIEWER_UNKNOWN", "no verified register to check the reviewer against"))
    else:
        subjects = _subjects(state, kind, key)
        problem = state.register.reviewer_problem(reviewer, subjects)
        if problem and problem[0] == "REVIEWER_NOT_QUALIFIED" and len(subjects) > 1:
            person = state.register.people[reviewer]
            if (
                person.active
                and person.roles & set(c.REVIEWER_ROLES)
                and person.subjects & subjects
            ):
                problem = None  # cross-subject: the reviewer pair must cover both (checked later)
        if problem:
            out.append(problem)
    if reviewer and reviewer == _author(state, kind, key):
        out.append(("REVIEWER_NOT_INDEPENDENT", f"{reviewer} authored this record"))
    etype = event.get("event_type")
    needs_rationale = (
        decision != "approved"
        or kind == "edge"
        or etype in ("reaffirmation", "clerical_confirmation", "adjudication")
    )
    if needs_rationale and not str(event.get("rationale", "")).strip():
        out.append(("RATIONALE_MISSING", "a written rationale is required"))
    edge = state.edges.get(key) if kind == "edge" else None
    if (
        edge is not None
        and edge.dependency_basis == "expert_judgement"
        and decision == "approved"
        and etype in ("review", "reaffirmation")
        and not str(event.get("expert_rationale", "")).strip()
    ):
        out.append(("RATIONALE_MISSING", "an expert_judgement approval needs an expert rationale"))
    if etype == "clerical_confirmation" and event.get("clerical_class") not in c.CLERICAL_CLASSES:
        out.append(("REVIEW_MISMATCH", f"clerical_class must be one of {c.CLERICAL_CLASSES}"))
    if decision == "approved" and etype in ("review", "reaffirmation"):
        items = c.KC_CHECKLIST if kind == "kc" else c.EDGE_CHECKLIST
        checklist = event.get("checklist") or {}
        if not all(checklist.get(item) is True for item in items):
            out.append(("CHECKLIST_INCOMPLETE", "every checklist item must be confirmed true"))
    if seq is not None:
        cited = [
            int(m)
            for m in EVENT_REF_RE.findall(
                " ".join(str(event.get(f, "")) for f in ("rationale", "expert_rationale"))
            )
        ]
        cited += [int(s[3:]) for s in event.get("supersedes", []) if c.EVENT_ID_RE.match(str(s))]
        if any(n >= seq for n in cited):
            out.append(("EVENT_CITES_FUTURE", "an event may cite only earlier events"))
    return out


# --- verifying records ---------------------------------------------------------------------


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split()).casefold()


def verify_records(
    events: Sequence[dict[str, Any]], state: State, *, allow_synthetic: bool
) -> tuple[list[Finding], dict[str, list[str]]]:
    """Findings for every record's review state; and record -> its current approving events."""
    findings: list[Finding] = []
    approving_ids: dict[str, list[str]] = {}
    by_id = {e.get("event_id"): e for e in events if isinstance(e, dict)}
    superseded = {s for e in events for s in e.get("supersedes", []) or []}
    for e in events:
        if not isinstance(e, dict) or "_unreadable" in e:
            continue
        if e.get("synthetic") and not allow_synthetic:
            findings.append(
                finding(
                    "SYNTHETIC_DATA",
                    "a synthetic event in a real log",
                    file=LABEL,
                    record=str(e.get("event_id")),
                )
            )
        bad = [
            k
            for k in ("event_type", "decision", "record_type")
            if e.get(k)
            not in {
                "event_type": c.EVENT_TYPES,
                "decision": c.DECISIONS,
                "record_type": ("kc", "edge"),
            }[k]
        ]
        if bad:
            findings.append(
                finding("LOG_INVALID", f"invalid {bad}", file=LABEL, record=str(e.get("event_id")))
            )
    records: list[tuple[str, str, Any]] = [("kc", k, r) for k, r in sorted(state.kcs.items())]
    records += [("edge", k, r) for k, r in sorted(state.edges.items())]
    for kind, key, row in records:
        label = "kc_csv" if kind == "kc" else "edge_csv"

        def add(code: str, message: str, _label=label, _key=key, _row=row) -> None:
            findings.append(
                finding(
                    code,
                    message,
                    file=_label,
                    line=_row.line,
                    record=_key,
                    field="review_record_ids",
                )
            )

        cited = []
        for rid in row.review_record_ids:
            event = by_id.get(rid)
            if event is None:
                add("REVIEW_RECORD_MISSING", f"{rid} is not in the review log")
            elif event.get("record_type") != kind or event.get("record_key") != key:
                add("REVIEW_MISMATCH", f"{rid} is about a different record")
            else:
                cited.append(event)
        for event in cited:
            for code, message in event_problems(event, state, seq=event.get("seq")):
                add(code, f"{event['event_id']}: {message}")
        if row.review_status == "rejected":
            if not any(
                e["decision"] == "rejected" and e["event_id"] not in superseded for e in cited
            ):
                add("REVIEW_MISMATCH", "a rejected row must cite a rejecting event")
            continue
        if row.review_status != "approved":
            continue
        ids, problems = _approval(kind, key, row, cited, events, superseded, state)
        for code, message in problems:
            add(code, message)
        if not any(c.CODES[code][0] == "error" for code, _ in problems):
            approving_ids[key] = ids
        elif row.origin == "ai_drafted" and not ids:
            add(
                "AI_SELF_APPROVAL",
                "a model-drafted row is approved without current human approving events",
            )
    return findings, approving_ids


def _approval(
    kind: str,
    key: str,
    row: Any,
    cited: list[dict[str, Any]],
    events: Sequence[dict[str, Any]],
    superseded: set[str],
    state: State,
) -> tuple[list[str], list[tuple[str, str]]]:
    problems: list[tuple[str, str]] = []
    full, pedagogical, versions = state.current(kind, key)  # type: ignore[misc]
    live = [e for e in cited if e["event_id"] not in superseded]
    for e in live:
        if e["decision"] != "approved":
            problems.append(("REVIEW_MISMATCH", f"{e['event_id']} is not an approval"))
    approvals = [
        e for e in live if e["event_type"] in c.APPROVING_TYPES and e["decision"] == "approved"
    ]
    clericals = [
        e
        for e in live
        if e["event_type"] == "clerical_confirmation" and e["decision"] == "approved"
    ]
    # wording-only links: old pedagogical digest -> current, by enough distinct reviewers
    linked = {pedagogical}
    by_old: dict[str, set[str]] = {}
    for e in clericals:
        if e.get("clerical_class") == "wording_only" and e["pedagogical_digest"] == pedagogical:
            by_old.setdefault(e.get("old_pedagogical_digest", ""), set()).add(e["reviewer_id"])
    linked |= {old for old, who in by_old.items() if len(who) >= c.WORDING_ONLY_QUORUM}
    for e in clericals:
        if e.get("clerical_class") == "clerical" and not any(
            a["seq"] < e["seq"] and a["pedagogical_digest"] == e["pedagogical_digest"]
            for a in approvals
        ):
            problems.append(
                (
                    "CLERICAL_EVENT_ON_SUBSTANTIVE_CHANGE",
                    f"{e['event_id']} confirms a change to pedagogical content",
                )
            )
    current_events = []
    for e in approvals:
        same_content = e["pedagogical_digest"] in linked
        same_versions = e.get("versions") == versions
        same_row = e["row_digest"] == full or any(
            x["seq"] > e["seq"]
            and x["row_digest"] == full
            and x["pedagogical_digest"] == pedagogical
            for x in clericals
        )
        if same_content and same_versions and same_row:
            current_events.append(e)
            continue
        if (
            kind == "kc"
            and not same_content
            and e.get("versions", {}).get(key) == row.content_version
        ):
            problems.append(
                (
                    "VERSION_NOT_BUMPED",
                    f"pedagogical content changed since "
                    f"{e['event_id']} but content_version is still {row.content_version}",
                )
            )
        elif kind == "kc" and same_content and not same_versions:
            problems.append(
                (
                    "VERSION_BUMPED_WITHOUT_CHANGE",
                    "content_version changed without a pedagogical change",
                )
            )
        problems.append(
            (
                "REVIEW_STALE",
                f"{e['event_id']} no longer matches the record "
                "(content, endpoint versions or a clerical change without confirmation)",
            )
        )
    # conflicts: an unsuperseded negative decision on the current content
    for e in events:
        if (
            isinstance(e, dict)
            and e.get("record_type") == kind
            and e.get("record_key") == key
            and e.get("decision") in ("rejected", "revision_required")
            and e.get("event_id") not in superseded
            and e.get("pedagogical_digest") in linked
        ):
            problems.append(
                (
                    "REVIEW_CONFLICT",
                    f"{e['event_id']} ({e['decision']}) on the current "
                    "content is unresolved; adjudicate",
                )
            )
    for e in current_events:
        if e["event_type"] == "adjudication":
            replaced = [
                x for x in events if isinstance(x, dict) and x.get("event_id") in e["supersedes"]
            ]
            if e["reviewer_id"] in {x.get("reviewer_id") for x in replaced}:
                problems.append(
                    (
                        "REVIEWER_NOT_INDEPENDENT",
                        "the adjudicator was one of the conflicting reviewers",
                    )
                )
    reviewers = [e["reviewer_id"] for e in current_events]
    if len(set(reviewers)) != len(reviewers):
        problems.append(("REVIEWER_NOT_INDEPENDENT", "one reviewer approved more than once"))
    quorum = c.KC_REVIEW_QUORUM if kind == "kc" else c.EDGE_REVIEW_QUORUM
    if len(set(reviewers)) < quorum:
        problems.append(
            (
                "QUORUM_NOT_MET",
                f"{len(set(reviewers))} current independent approvals; {quorum} required",
            )
        )
    if kind == "edge":
        problems += _edge_checks(key, row, current_events, state)
    return [e["event_id"] for e in sorted(current_events, key=lambda e: e["seq"])], problems


def _edge_checks(
    key: str, edge: EdgeRow, approvals: list[dict[str, Any]], state: State
) -> list[tuple[str, str]]:
    problems = []
    texts = [_norm(e.get("rationale")) for e in approvals]
    experts = [_norm(e.get("expert_rationale")) for e in approvals if e.get("expert_rationale")]
    if len(set(texts)) != len(texts) or len(set(experts)) != len(experts):
        problems.append(
            ("RATIONALE_DUPLICATED", "approving rationales must be individually written")
        )
    subjects = _subjects(state, "edge", key)
    if state.register is not None and approvals:
        covered = set().union(
            *(
                state.register.people[e["reviewer_id"]].subjects
                for e in approvals
                if e["reviewer_id"] in state.register.people
            )
        )
        if not subjects <= covered:
            problems.append(
                (
                    "REVIEWER_NOT_QUALIFIED",
                    f"the approving reviewers do not cover both subjects {sorted(subjects)}",
                )
            )
        authors = {
            state.kcs[k].author_id
            for k in (edge.prerequisite_kc_id, edge.dependent_kc_id)
            if k in state.kcs
        }
        if authored := sorted({e["reviewer_id"] for e in approvals} & authors):
            problems.append(("REVIEWER_AUTHORED_ENDPOINT", f"{authored} authored an endpoint KC"))
    tokens = [t.raw for t in edge.evidence_refs]
    for e in approvals:
        if e["event_type"] == "adjudication":
            continue
        assessed = {a.get("token"): a for a in e.get("evidence_assessment", []) or []}
        if edge.dependency_basis.startswith("uses_"):
            if missing := [t for t in tokens if t not in assessed]:
                problems.append(
                    ("EVIDENCE_NOT_ASSESSED", f"{e['event_id']} did not assess {missing}")
                )
            if not any(
                a.get("supports") is True and str(a.get("note", "")).strip()
                for a in assessed.values()
            ):
                problems.append(
                    (
                        "EVIDENCE_NOT_SUPPORTING",
                        f"{e['event_id']} records no passage "
                        "where the dependent skill uses the prerequisite",
                    )
                )
        for token, a in sorted(assessed.items()):
            now = state.resolutions.get(token)
            if now is None or (now.source_sha256, now.passage_sha256) != (
                a.get("source_sha256"),
                a.get("passage_sha256"),
            ):
                problems.append(
                    (
                        "EVIDENCE_STALE",
                        f"{e['event_id']}: {token} no longer matches "
                        "the assessed source or passage",
                    )
                )
    return problems
