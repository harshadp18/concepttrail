"""Deterministic validation and coverage reports, and the run manifest (M5).

The report contains no timestamps and no absolute paths, and every list is sorted, so two runs
of the same loader version on the same inputs write byte-identical files. The run manifest is
separate and does carry the time of the run. Dry runs write only to `logs/kc_graph/`.
"""

from __future__ import annotations

import collections
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.audit_chain import digest
from data_pipeline.kc_graph.contract import LOADER_VERSION
from data_pipeline.kc_graph.validate import Result


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def validation_report(result: Result) -> dict[str, Any]:
    counts = collections.Counter(f.code for f in result.findings)
    body = {
        "report_type": "kc_graph_validation",
        "loader_version": LOADER_VERSION,
        "synthetic": result.synthetic,
        "inputs": result.inputs,
        "vocabulary": result.vocab.manifest(),
        "records": {
            "kcs": len(result.kcs),
            "edges": len(result.edges),
            "kcs_by_status": dict(
                sorted(collections.Counter(k.review_status for k in result.kcs.values()).items())
            ),
            "edges_by_status": dict(
                sorted(collections.Counter(e.review_status for e in result.edges.values()).items())
            ),
            "retired_kcs": sorted(result.retired),
        },
        "summary": {
            "errors": sum(1 for f in result.findings if f.severity == "error"),
            "warnings": sum(1 for f in result.findings if f.severity == "warning"),
            "by_code": dict(sorted(counts.items())),
        },
        "findings": [f.as_dict() for f in result.findings],
        "verified_approvals": {k: v for k, v in sorted(result.approving_ids.items())},
        "release": {
            "eligible": not result.release_blockers,
            "blockers": result.release_blockers,
            "released_edges_if_released": sorted(
                f"{e.prerequisite_kc_id}->{e.dependent_kc_id}" for e in result.graph.released_edges
            ),
        },
        "source_pins": sorted(
            {
                (r.source_id, r.source_sha256, r.revision, r.academic_session)
                for r in result.resolutions.values()
            }
        ),
    }
    body["content_sha256"] = digest(body)
    return body


def coverage_document(result: Result) -> dict[str, Any]:
    body = {
        "report_type": "kc_graph_coverage",
        "loader_version": LOADER_VERSION,
        "synthetic": result.synthetic,
        "class_basis_note": "declared_class_levels is the author's declaration, not a curriculum "
        "mapping; mapped figures are null until approved kc_curriculum_map rows are supplied",
        "coverage": result.graph.coverage,
    }
    body["content_sha256"] = digest(body)
    return body


def write(directory: Path, name: str, body: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(dumps(body), encoding="utf-8")
    return path


def run_manifest(result: Result, outputs: dict[str, str], mode: str) -> dict[str, Any]:
    return {
        "manifest_type": "kc_graph_run",
        "loader_version": LOADER_VERSION,
        "mode": mode,
        "ran_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": result.inputs,
        "vocabulary": result.vocab.manifest(),
        "outputs": outputs,
        "errors": sum(1 for f in result.findings if f.severity == "error"),
        "database_written": False,
        "models_called": False,
    }
