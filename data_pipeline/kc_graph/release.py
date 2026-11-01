"""Release: the explicitly released graph snapshot and its manifest (D15, contract 12), M4.

Written only when validation has zero errors and every release blocker is clear. Writes
`final/kc_graph/released_graph_<seq>.json` and `release_manifest_<seq>.json`, both write-once.
It never touches the database. Runtime consumers verify the snapshot with
`app.services.graph_snapshot.load_released_graph` and fail closed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.graph_snapshot import (
    DIGEST_FIELD,
    SNAPSHOT_FORMAT,
    retired_state,
    snapshot_digest,
)
from data_pipeline.kc_graph.contract import LOADER_VERSION
from data_pipeline.kc_graph.digests import full_digest
from data_pipeline.kc_graph.validate import Result
from data_pipeline.teacher_validation import write_once


class ReleaseRefused(RuntimeError):
    pass


def build_snapshot(result: Result, seq: int) -> dict[str, Any]:
    active_approved = {
        k: kc
        for k, kc in result.kcs.items()
        if kc.review_status == "approved" and k not in result.retired
    }
    kcs = [
        {
            "kc_id": k,
            "stable_key": kc.stable_key,
            "subject_id": kc.subject_id,
            "name": kc.name,
            "kc_type": kc.kc_type,
            "difficulty_tier": kc.difficulty_tier,
            "review_status": "approved",
            "class_levels": list(kc.declared_class_levels),
            "scope": kc.scope,
            "lifecycle": "active",
        }
        for k, kc in sorted(active_approved.items())
    ]
    edges = [
        {
            "prerequisite_kc_id": e.prerequisite_kc_id,
            "dependent_kc_id": e.dependent_kc_id,
            "reason": e.reason,
            "strength": e.strength,
            "evidence_refs": list(e.evidence_refs),
            "review_status": "approved",
        }
        for e in result.graph.released_edges
        if e.prerequisite_kc_id in active_approved and e.dependent_kc_id in active_approved
    ]
    in_force = retired_state(result.lifecycle_events)
    retired = [
        {
            "kc_id": k,
            "lifecycle_event_id": in_force[k]["event_id"],
            "kc_row_digest": full_digest(result.kcs[k].cells),
        }
        for k in sorted(result.retired)
        if k in result.kcs
    ]
    snapshot = {
        "format": SNAPSHOT_FORMAT,
        "seq": seq,
        "loader_version": LOADER_VERSION,
        "kcs": kcs,
        "edges": edges,
        "retired_kcs": retired,
        # Database-only content for the import plan (D3: learning_objective -> description).
        "kc_content": {
            k: {
                "description": kc.learning_objective,
                "misconceptions": list(kc.misconceptions),
                "content_version": kc.content_version,
            }
            for k, kc in sorted(active_approved.items())
        },
        "vocabulary": result.vocab.manifest(),
        "review_log_head": result.inputs["review_log_head"],
        "lifecycle_log_head": result.inputs["lifecycle_log_head"],
        "inputs": result.inputs,
        "source_pins": sorted(
            {r.source_id + "#" + r.source_sha256 for r in result.resolutions.values()}
        ),
        "synthetic": result.synthetic,
    }
    snapshot[DIGEST_FIELD] = snapshot_digest(snapshot)
    return snapshot


def next_seq(final_dir: Path) -> int:
    return len(list(final_dir.glob("released_graph_*.json"))) + 1


def release(result: Result, final_dir: Path, *, allow_synthetic_output: bool = False) -> Path:
    """Write the snapshot and manifest, or raise `ReleaseRefused` with every blocker."""
    blockers = [
        b
        for b in result.release_blockers
        if not (allow_synthetic_output and b.startswith("SYNTHETIC_DATA"))
    ]
    if blockers:
        raise ReleaseRefused("; ".join(blockers))
    seq = next_seq(final_dir)
    snapshot = build_snapshot(result, seq)
    path, _ = write_once(final_dir / f"released_graph_{seq}.json", snapshot)
    manifest = {
        "manifest_type": "kc_graph_release",
        "seq": seq,
        "snapshot": path.name,
        DIGEST_FIELD: snapshot[DIGEST_FIELD],
        "review_log_head": snapshot["review_log_head"],
        "lifecycle_log_head": snapshot["lifecycle_log_head"],
        "vocabulary": snapshot["vocabulary"],
        "inputs": result.inputs,
        "kcs": len(snapshot["kcs"]),
        "edges": len(snapshot["edges"]),
        "database_written": False,
    }
    write_once(final_dir / f"release_manifest_{seq}.json", manifest)
    return path


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
