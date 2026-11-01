# ruff: noqa: E501  (report text is prose)
"""Synthetic retrieval REGRESSION suite (not a human relevance benchmark).

    python -m evaluation.retrieval_regression      # needs the local embedding model

Cases are built deterministically from the knowledge-component metadata of the indexed chapters
(KC name + objective as the query; any page of the KC's chapter counts as a hit) plus hand-written
off-corpus and vague queries. All labels are `ai_generated_unverified`: the KC metadata was
AI-drafted, so a hit here means "retrieval still finds the chapter this metadata came from", useful
for catching regressions after re-indexing or model changes. It is never reported as retrieval
accuracy and never feeds a human-quality metric.

Checks: chapter hit@1/@5 at three scope widths (class+subject filter, subject only, no filter),
by language and subject; abstention probes (best score below the 0.35 retrieval floor) for
off-corpus and vague queries, reported as observed behaviour; scope leakage (every returned page
inside the filter).
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from evaluation.stats import rate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".local/evaluation/reports"
FLOOR = 0.35
_DEVANAGARI = re.compile("[ऀ-ॿ]")

# Hand-written probes (AI-authored, unverified). Off-corpus: topics no indexed chapter covers.
OFF_CORPUS = [
    ("How does a black hole emit Hawking radiation?", "science", 10),
    ("What are the rules of baseball?", "english", 9),
    ("Explain the stock market crash of 1929 in America.", "social_science", 8),
    ("Solve a differential equation using Laplace transforms.", "mathematics", 10),
    ("How do I bake sourdough bread?", "science", 7),
    ("जापान की राजधानी में मेट्रो कैसे चलती है?", "hindi", 8),
]
VAGUE = [
    ("explain this", None, None),
    ("what is the answer", None, None),
    ("chapter", None, None),
    ("उत्तर बताइए", None, None),
]


def cases(session: Session) -> list[dict]:
    from app.db.models import (
        ContentUnit,
        CurriculumItem,
        CurriculumVersion,
        EmbeddingChunk,
        KcCurriculumMap,
        KnowledgeComponent,
    )

    indexed_items = {
        i
        for (i,) in session.execute(
            select(ContentUnit.item_id)
            .join(EmbeddingChunk, EmbeddingChunk.content_unit_id == ContentUnit.content_unit_id)
            .distinct()
        )
    }
    out = []
    for kc, item, level in session.execute(
        select(KnowledgeComponent, CurriculumItem, CurriculumVersion.class_level)
        .join(KcCurriculumMap, KcCurriculumMap.kc_id == KnowledgeComponent.kc_id)
        .join(CurriculumItem, CurriculumItem.item_id == KcCurriculumMap.item_id)
        .join(
            CurriculumVersion,
            CurriculumVersion.curriculum_version_id == CurriculumItem.curriculum_version_id,
        )
        .order_by(KnowledgeComponent.kc_id)
    ):
        if item.item_id not in indexed_items:
            continue
        query = f"{kc.name}. {kc.description or ''}".strip()
        out.append(
            {
                "case_id": f"rr-{kc.kc_id}",
                "query": query,
                "class_level": level,
                "subject_id": kc.subject_id,
                "language": "hi" if _DEVANAGARI.search(query) else "en",
                "expected_item": item.item_id,
                "kind": "chapter_hit",
                "label_provenance": "ai_generated_unverified",
            }
        )
    for i, (query, subject, level) in enumerate(OFF_CORPUS):
        out.append(
            {
                "case_id": f"rr-off-{i}",
                "query": query,
                "class_level": level,
                "subject_id": subject,
                "language": "hi" if _DEVANAGARI.search(query) else "en",
                "expected_item": None,
                "kind": "off_corpus",
                "label_provenance": "ai_generated_unverified",
            }
        )
    for i, (query, subject, level) in enumerate(VAGUE):
        out.append(
            {
                "case_id": f"rr-vague-{i}",
                "query": query,
                "class_level": level,
                "subject_id": subject,
                "language": "hi" if _DEVANAGARI.search(query) else "en",
                "expected_item": None,
                "kind": "vague",
                "label_provenance": "ai_generated_unverified",
            }
        )
    return out


def run(session: Session) -> dict:
    from app.db.models import CurriculumItem, CurriculumVersion, EmbeddingChunk, SourceDocument
    from app.services.embeddings import OllamaEmbedder
    from app.services.rag import RetrievalFilter, retrieve_evidence

    embedder = OllamaEmbedder("bge-m3")
    model_id = embedder.describe().model_id
    generation = session.scalar(select(func.min(EmbeddingChunk.index_generation)))
    all_cases = cases(session)
    vectors = embedder.embed([c["query"] for c in all_cases])
    level_of = dict(
        session.execute(
            select(CurriculumItem.item_id, CurriculumVersion.class_level).join(
                CurriculumVersion,
                CurriculumVersion.curriculum_version_id == CurriculumItem.curriculum_version_id,
            )
        ).all()
    )
    subject_of = dict(
        session.execute(select(SourceDocument.source_id, SourceDocument.subject_id)).all()
    )

    def search(vec, level, subject, k=5, floor=FLOOR):
        return retrieve_evidence(
            session,
            vec,
            embedding_model_id=model_id,
            index_generation=generation,
            filters=RetrievalFilter(class_level=level, subject_id=subject),
            mode="internal",
            k=k,
            min_score=floor,
        )

    scopes = {
        "class_and_subject": lambda c: (c["class_level"], c["subject_id"]),
        "subject_only": lambda c: (None, c["subject_id"]),
        "no_filter": lambda c: (None, None),
    }
    hits = {s: defaultdict(lambda: {"h1": 0, "h5": 0, "n": 0}) for s in scopes}
    leaks = checked = 0
    probes = []
    for case, vec in zip(all_cases, vectors, strict=True):
        if case["kind"] == "chapter_hit":
            for scope, args in scopes.items():
                level, subject = args(case)
                found = search(vec, level, subject)
                items = [e.item_id for e in found]
                for cell in ("all", f"lang:{case['language']}", f"subject:{case['subject_id']}"):
                    h = hits[scope][cell]
                    h["n"] += 1
                    h["h1"] += bool(items[:1]) and items[0] == case["expected_item"]
                    h["h5"] += case["expected_item"] in items
                for e in found:
                    checked += 1
                    leaks += bool(level is not None and level_of.get(e.item_id) != level) or bool(
                        subject is not None and subject_of.get(e.source_id) != subject
                    )
        else:
            top = search(vec, case["class_level"], case["subject_id"], k=1, floor=0.0)
            best = top[0].score if top else None
            probes.append(
                {
                    "case_id": case["case_id"],
                    "kind": case["kind"],
                    "language": case["language"],
                    "best_score": None if best is None else round(best, 4),
                    "below_floor": best is None or best < FLOOR,
                }
            )
    summary = {
        scope: {
            cell: {"hit_at_1": rate(v["h1"], v["n"]), "hit_at_5": rate(v["h5"], v["n"])}
            for cell, v in sorted(cells.items())
        }
        for scope, cells in hits.items()
    }
    by_kind = defaultdict(list)
    for p in probes:
        by_kind[p["kind"]].append(p["below_floor"])
    return {
        "kind": "SYNTHETIC retrieval regression (ai_generated_unverified labels; not a human relevance benchmark)",
        "embedding_model": model_id,
        "index_generation": generation,
        "floor": FLOOR,
        "cases": {
            k: sum(1 for c in all_cases if c["kind"] == k)
            for k in ("chapter_hit", "off_corpus", "vague")
        },
        "chapter_hit": summary,
        "scope_leakage": {"results_checked": checked, "leaks": leaks},
        "abstention_probes": {k: rate(sum(v), len(v), 1) for k, v in by_kind.items()},
        "probe_details": probes,
        "interpretation": "Hit rates measure whether the chapter that produced the KC metadata is retrieved; with a class+subject filter most combinations hold a single chapter, so that scope is nearly trivial. Probes below the floor would lead the doubt service to abstain; probes above it rely on the model's own sufficiency check.",
    }


def markdown(r: dict) -> str:
    lines = [
        "# Synthetic retrieval regression",
        "",
        f"**{r['kind']}.** Model {r['embedding_model']}, generation {r['index_generation']}, floor {r['floor']}. Cases {r['cases']}.",
        "",
        "| scope | cell | hit@1 | hit@5 |",
        "|---|---|---|---|",
    ]

    def fmt(c):
        return (
            f"{c['rate']:.1%} (n={c['n']})"
            if c["status"] == "measured"
            else f"{c['status']} (n={c['n']})"
        )

    for scope, cells in r["chapter_hit"].items():
        for cell, v in cells.items():
            lines.append(f"| {scope} | {cell} | {fmt(v['hit_at_1'])} | {fmt(v['hit_at_5'])} |")
    lines += [
        "",
        f"Scope leakage: {r['scope_leakage']['leaks']} of {r['scope_leakage']['results_checked']} returned pages outside the filter.",
        "",
        "Abstention probes (best score below the floor):",
    ]
    for k, v in r["abstention_probes"].items():
        lines.append(f"- {k}: {v['count']}/{v['n']}")
    for p in r["probe_details"]:
        lines.append(f"  - {p['case_id']} ({p['language']}): best score {p['best_score']}")
    lines += ["", r["interpretation"], ""]
    return "\n".join(lines)


def main() -> int:
    from app.db.session import create_db_engine

    with Session(create_db_engine(read_only=True)) as session:
        report = run(session)
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (OUT / f"retrieval_regression_{stamp}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )
    (OUT / f"retrieval_regression_{stamp}.md").write_text(markdown(report))
    print(markdown(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
