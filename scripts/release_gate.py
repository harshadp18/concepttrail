"""Production release gates (read-only). Exit 0 only when every gate passes.

    python -m scripts.release_gate [--env-file PATH]

Gates: application (production settings validate), content (human-approved or published content
exists, nothing AI-generated is marked approved without a recorded human review), graph (a
verified released snapshot exists), BKT (an active configuration is not marked provisional or
uncalibrated), RAG (an index generation is configured and has chunks over approved content with
indexing and display rights). Demo content never satisfies a gate. The script changes nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import ConfigurationError, load_settings


def gate(ok: bool, detail: str) -> dict:
    return {"pass": ok, "detail": detail}


def application_gate(env_file: Path | None) -> tuple[dict, object | None]:
    try:
        settings = load_settings(_env_file=env_file) if env_file else load_settings()
    except ConfigurationError as exc:
        return gate(False, str(exc).splitlines()[0] + " (see validation messages)"), None
    if settings.app_env != "production":
        return gate(False, f"APP_ENV is {settings.app_env}, not production"), settings
    return gate(True, "production settings validate"), settings


def database_gates(session: Session, settings) -> dict:
    from app.db.models import (
        BktConfigVersion,
        ContentUnit,
        EmbeddingChunk,
        KnowledgeComponent,
        Question,
        SourceDocument,
    )

    approved_q = session.scalar(
        select(func.count()).select_from(Question).where(Question.review_status == "approved")
    )
    approved_kc = session.scalar(
        select(func.count())
        .select_from(KnowledgeComponent)
        .where(KnowledgeComponent.review_status == "approved")
    )
    unreviewed_approved = 0
    for q in session.scalars(select(Question).where(Question.review_status == "approved")):
        v = q.verification or {}
        prov = v.get("provenance") or {}
        if prov.get("origin") == "ai_drafted" and not v.get("reviews"):
            unreviewed_approved += 1
    demo = session.scalar(
        select(func.count()).select_from(Question).where(Question.review_status == "demo_release")
    )
    content = gate(
        bool(approved_q) and bool(approved_kc) and unreviewed_approved == 0,
        f"approved questions={approved_q}, approved KCs={approved_kc}, AI-drafted approved "
        f"without a recorded review={unreviewed_approved}, demo-only questions={demo} (ignored)",
    )
    configs = session.scalars(select(BktConfigVersion)).all()
    calibrated = [
        c.bkt_config_version
        for c in configs
        if not any(w in (c.notes or "").upper() for w in ("PROVISIONAL", "UNCALIBRATED"))
    ]
    bkt = gate(
        bool(calibrated),
        f"configs={[c.bkt_config_version for c in configs]}; non-provisional={calibrated}",
    )
    index = getattr(settings, "rag_index_generation", None) if settings else None
    chunks = 0
    if index:
        chunks = session.scalar(
            select(func.count())
            .select_from(EmbeddingChunk)
            .join(ContentUnit, ContentUnit.content_unit_id == EmbeddingChunk.content_unit_id)
            .join(SourceDocument, SourceDocument.source_id == ContentUnit.source_id)
            .where(
                EmbeddingChunk.index_generation == index,
                ContentUnit.review_status == "approved",
                SourceDocument.permitted_uses.contains(["indexing_retrieval"]),
                SourceDocument.permitted_uses.contains(["student_facing_display"]),
            )
        )
    rag = gate(bool(chunks), f"index_generation={index!r}; chunks over approved content={chunks}")
    coverage = coverage_gate(session)
    rights = rights_gate(session)
    return {
        "content": content,
        "coverage": coverage,
        "source_rights": rights,
        "bkt": bkt,
        "rag": rag,
    }


def coverage_gate(session: Session) -> dict:
    """Every class-subject combination (6-10 x 5 subjects) needs a published chapter with an
    approved KC mapping. Demo or synthetic content never counts."""
    from app.db.models import CurriculumItem, CurriculumVersion, KcCurriculumMap, KnowledgeComponent

    rows = session.execute(
        select(CurriculumVersion.class_level, CurriculumItem.subject_id)
        .join(
            CurriculumItem,
            CurriculumItem.curriculum_version_id == CurriculumVersion.curriculum_version_id,
        )
        .join(KcCurriculumMap, KcCurriculumMap.item_id == CurriculumItem.item_id)
        .join(KnowledgeComponent, KnowledgeComponent.kc_id == KcCurriculumMap.kc_id)
        .where(
            CurriculumItem.status == "published",
            CurriculumVersion.status == "published",
            KcCurriculumMap.review_status == "approved",
            KnowledgeComponent.review_status == "approved",
        )
        .distinct()
    ).all()
    covered = {(int(c), s) for c, s in rows if c is not None}
    required = {
        (c, s)
        for c in range(6, 11)
        for s in ("english", "hindi", "mathematics", "science", "social_science")
    }
    missing = sorted(required - covered)
    return gate(
        not missing, f"verified combinations {len(covered & required)}/25; missing {len(missing)}"
    )


def rights_gate(session: Session) -> dict:
    """Approved questions may cite only sources whose record grants student-facing display."""
    from app.db.models import Question, SourceDocument

    uses = {
        s.source_id: set(s.permitted_uses or []) for s in session.scalars(select(SourceDocument))
    }
    approved = list(session.scalars(select(Question).where(Question.review_status == "approved")))
    bad = [
        q.question_id
        for q in approved
        for ref in (q.source_refs or [])
        if "student_facing_display" not in uses.get(ref.get("source_id"), set())
    ]
    return gate(
        bool(approved) and not bad,
        f"approved questions={len(approved)}; citing sources without display rights={len(bad)}",
    )


def graph_gate() -> dict:
    from app.services.graph_runtime import ReleasedGraph, get_released_graph

    released = get_released_graph()
    if isinstance(released, ReleasedGraph):
        return gate(True, f"{released.version}")
    return gate(False, f"{released.reason} {list(released.detail)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.release_gate")
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args(argv)
    app_gate, settings = application_gate(args.env_file)
    from app.db.session import create_db_engine

    with Session(create_db_engine(read_only=True)) as session:
        gates = {
            "application": app_gate,
            **database_gates(session, settings),
            "graph": graph_gate(),
        }
    print(json.dumps(gates, indent=2))
    failed = [name for name, g in gates.items() if not g["pass"]]
    print("RELEASE GATES: " + ("PASS" if not failed else f"FAIL ({', '.join(failed)})"))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
