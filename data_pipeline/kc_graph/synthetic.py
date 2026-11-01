# ruff: noqa: E501  (the sample CSV rows are verbatim copies of the contract document)
"""A complete SYNTHETIC package for tests and the synthetic dry run. Never real data.

It uses the contract's own sample CSV rows (tests check they are identical to the contract
document), a synthetic source document `SRC-C07-MAT-EXMP1-01` (no textbook behind it), a
register marked `"synthetic": true`, and review events written through the real tool path and
marked `"synthetic": true`. A real run refuses all of it (`SYNTHETIC_DATA`), and a synthetic
approval is never a human approval.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from data_pipeline.kc_graph import contract as c
from data_pipeline.kc_graph import people, review_log, validate
from data_pipeline.kc_graph.sources import SourceDocument, SourceIndex
from data_pipeline.kc_graph.vocabulary import PROVISIONAL_VOCABULARY

SYNTHETIC_SOURCE = "SRC-C07-MAT-EXMP1-01"
SYNTHETIC_SHA = "a1b2c3d4e5f6" + hashlib.sha256(b"synthetic source").hexdigest()[12:]
RECORDED_AT = "2026-01-01T00:00:00Z"

KC_SAMPLE = """\
kc_id,stable_key,subject_id,name,learning_objective,kc_type,difficulty_tier,misconceptions,source_refs,declared_class_levels,content_version,origin,origin_ref,review_status,review_record_ids,aliases,scope,author_id
KC-MAT-00001,mathematics.fractions.equivalent-fractions.recognise,mathematics,Recognise equivalent fractions,Identify whether two fractions represent the same quantity.,concept,1,"[{""id"":""m1"",""text"":""Believes a larger denominator always means a larger fraction""}]",src:SRC-C07-MAT-EXMP1-01@3#a1b2c3d4e5f6,6;7,kc-v1,human_authored,,approved,RR-0001,,target,RV-001
KC-MAT-00002,mathematics.fractions.add-unlike-denominators.compute,mathematics,Add fractions with unlike denominators,Add two fractions by rewriting them over a common denominator.,procedure,2,"[{""id"":""m1"",""text"":""Adds the numerators and the denominators separately""}]",src:SRC-C07-MAT-EXMP1-01@5#a1b2c3d4e5f6,7,kc-v1,human_authored,,approved,RR-0002,mathematics.fractions.fraction-addition,target,RV-001
KC-MAT-00003,mathematics.fractions.mixed-numbers.construct,mathematics,Convert between improper fractions and mixed numbers,Rewrite an improper fraction as a mixed number and back.,procedure,2,,src:SRC-C07-MAT-EXMP1-01@6#a1b2c3d4e5f6,7,kc-v1,ai_drafted,GEN-EXAMPLE-01,needs_review,,,target,
KC-MAT-00004,mathematics.number-sense.equal-sharing.recognise,mathematics,Recognise equal sharing,Identify whether a whole has been shared into equal parts.,concept,1,,src:SRC-C07-MAT-EXMP1-01@2#a1b2c3d4e5f6,,kc-v1,human_authored,,approved,RR-0003,,foundation,RV-001
"""
EDGE_SAMPLE = """\
prerequisite_kc_id,dependent_kc_id,dependency_basis,reason,strength,evidence_refs,origin,origin_ref,review_status,review_record_ids,author_id
KC-MAT-00001,KC-MAT-00002,uses_concept,Finding a common denominator means rewriting each fraction as an equivalent fraction.,3,src:SRC-C07-MAT-EXMP1-01@5:para2#a1b2c3d4e5f6,human_authored,,approved,RR-0004;RR-0005,RV-001
KC-MAT-00004,KC-MAT-00001,uses_concept,Comparing fractions as the same quantity builds on equal sharing of a whole.,2,src:SRC-C07-MAT-EXMP1-01@3:para1#a1b2c3d4e5f6,human_authored,,approved,RR-0006;RR-0007,RV-001
KC-MAT-00002,KC-MAT-00003,uses_procedure,Converting a sum to a mixed number follows the addition step.,2,,ai_drafted,GEN-EXAMPLE-01,needs_review,,
"""

REGISTER = {
    "version": "synthetic-1",
    "synthetic": True,
    "people": [
        {
            "code": "RV-001",
            "roles": ["author"],
            "subjects": ["mathematics"],
            "qualification_basis": "synthetic test person",
            "active": True,
        },
        {
            "code": "RV-002",
            "roles": ["reviewer"],
            "subjects": ["mathematics"],
            "qualification_basis": "synthetic test person",
            "active": True,
        },
        {
            "code": "RV-003",
            "roles": ["reviewer"],
            "subjects": ["mathematics"],
            "qualification_basis": "synthetic test person",
            "active": True,
        },
        {
            "code": "RV-004",
            "roles": ["senior_reviewer"],
            "subjects": ["mathematics"],
            "qualification_basis": "synthetic test person",
            "active": True,
        },
    ],
}


def source_index() -> SourceIndex:
    pages = tuple(
        (
            False,
            tuple(
                hashlib.sha256(f"synthetic page {p} para {n}".encode()).hexdigest()
                for n in range(3)
            ),
        )
        for p in range(8)
    )
    doc = SourceDocument(
        source_id=SYNTHETIC_SOURCE,
        sha256=SYNTHETIC_SHA,
        title="Synthetic example (no textbook)",
        revision="synthetic",
        academic_session="2026-27",
        accepted=True,
        rights_permitted=True,
        rights_reason="synthetic",
        artifact="synthetic",
        artifact_sha256=SYNTHETIC_SHA,
        page_count=len(pages),
        pages=pages,
        pdf_status=None,
    )
    return SourceIndex([doc], synthetic=True)


def _check(items: tuple[str, ...]) -> dict[str, bool]:
    return dict.fromkeys(items, True)


def _kc_review(kc_id: str, reviewer: str) -> dict[str, Any]:
    return {
        "event_type": "review",
        "record_type": "kc",
        "record_key": kc_id,
        "decision": "approved",
        "reviewer_id": reviewer,
        "decided_on": "2026-01-01",
        "rationale": f"Synthetic test review of {kc_id} by {reviewer}.",
        "checklist": _check(c.KC_CHECKLIST),
    }


def _edge_review(key: str, token: str, reviewer: str) -> dict[str, Any]:
    return {
        "event_type": "review",
        "record_type": "edge",
        "record_key": key,
        "decision": "approved",
        "reviewer_id": reviewer,
        "decided_on": "2026-01-01",
        "rationale": f"Synthetic test: {reviewer} judged that {key} is a real dependency.",
        "evidence_assessment": [
            {"token": token, "supports": True, "note": f"Synthetic passage note by {reviewer}."}
        ],
        "checklist": _check(c.EDGE_CHECKLIST),
    }


def build(root: Path) -> validate.Inputs:
    """Write the synthetic package under `root` and return the inputs to validate it."""
    curated, review = root / "curated", root / "kc_review"
    curated.mkdir(parents=True, exist_ok=True)
    review.mkdir(parents=True, exist_ok=True)
    (curated / "kc_components.csv").write_text(KC_SAMPLE, encoding="utf-8")
    (curated / "prerequisites.csv").write_text(EDGE_SAMPLE, encoding="utf-8")
    vocab = {
        **PROVISIONAL_VOCABULARY,
        "version": "synthetic-1",
        "status": "owner_confirmed",
        "synthetic": True,
        "change_log": ["synthetic test vocabulary; not owner-confirmed"],
    }
    (curated / "kc_vocabularies.json").write_text(json.dumps(vocab, indent=2), encoding="utf-8")
    register_path = review / c.REGISTER_FILE.name
    register_path.write_text(json.dumps(REGISTER, indent=2), encoding="utf-8")
    record = people.build_verification(
        register_path, "SYNTHETIC test verification; not a real owner statement", "2026-01-01"
    )
    people.write_verification(review, record)
    custody = [root / "custody_a", root / "custody_b"]
    (review / c.CUSTODY_FILE.name).write_text(
        json.dumps(
            {
                "synthetic": True,
                "locations": [
                    {"label": "synthetic-a", "path": str(custody[0].resolve())},
                    {"label": "synthetic-b", "path": str(custody[1].resolve())},
                ],
            }
        ),
        encoding="utf-8",
    )
    inputs = validate.Inputs(
        kc_csv=curated / "kc_components.csv",
        edge_csv=curated / "prerequisites.csv",
        vocabulary=curated / "kc_vocabularies.json",
        review_dir=review,
        sources=source_index(),
        allow_synthetic=True,
    )
    write_reviews(
        inputs,
        [
            _kc_review("KC-MAT-00001", "RV-002"),
            _kc_review("KC-MAT-00002", "RV-002"),
            _kc_review("KC-MAT-00004", "RV-003"),
            _edge_review(
                "KC-MAT-00001->KC-MAT-00002",
                "src:SRC-C07-MAT-EXMP1-01@5:para2#a1b2c3d4e5f6",
                "RV-002",
            ),
            _edge_review(
                "KC-MAT-00001->KC-MAT-00002",
                "src:SRC-C07-MAT-EXMP1-01@5:para2#a1b2c3d4e5f6",
                "RV-003",
            ),
            _edge_review(
                "KC-MAT-00004->KC-MAT-00001",
                "src:SRC-C07-MAT-EXMP1-01@3:para1#a1b2c3d4e5f6",
                "RV-002",
            ),
            _edge_review(
                "KC-MAT-00004->KC-MAT-00001",
                "src:SRC-C07-MAT-EXMP1-01@3:para1#a1b2c3d4e5f6",
                "RV-003",
            ),
        ],
    )
    anchor(inputs, custody)
    return inputs


def write_reviews(inputs: validate.Inputs, entries: list[dict[str, Any]]) -> list[dict]:
    """Append entries through the real tool path (build_event + append)."""
    written = []
    for entry in entries:
        result = validate.run(inputs)
        state = review_log.State(result.kcs, result.edges, result.resolutions, result.register)
        event = review_log.build_event(entry, state, RECORDED_AT, synthetic=True)
        written.append(
            review_log.append(inputs.review_dir / c.REVIEW_LOG.name, event, c.REVIEW_ID_PREFIX)
        )
    return written


def anchor(inputs: validate.Inputs, custody: list[Path]) -> None:
    for name, stem in ((c.REVIEW_LOG.name, "anchor"), (c.LIFECYCLE_LOG.name, "lifecycle-anchor")):
        events, _ = review_log.read_jsonl(inputs.review_dir / name, name)
        if events:
            record = review_log.anchor_record(events, RECORDED_AT)
            review_log.write_anchor([inputs.review_dir / "anchors", *custody], record, stem)
