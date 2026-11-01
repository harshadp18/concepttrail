"""Compare locally installed embedding models on the real pilot corpus (read-only, local only).

Corpus: chunks of the 222 pilot `content_unit` pages (indexing permitted by the rights gate).
Queries: the 51 Phase 4 objectives. A page is relevant to an objective when it belongs to the
objective's chapter and contains one of the objective's evidence terms verbatim (the Phase 4
grounding rule), so relevance comes from the data, not from judgement. Metrics: page-level
recall@5 and MRR@10 over all chunks of all 10 documents, by language, plus dimension and
latency. Nothing is written to the database.

    python -m evaluation.embedding_model_eval bge-m3 qwen3-embedding:0.6b
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ContentUnit
from app.db.session import create_db_engine
from app.services.embeddings import OllamaEmbedder
from app.services.rag import chunk_content_unit

ROOT = Path(__file__).resolve().parents[1]
OBJECTIVES = (
    ROOT / "data_pipeline/data/overrides/metadata_enrichment/ai_generated_learning_objectives.json"
)
OUT = ROOT / "data_pipeline/data/logs/embedding_eval"


def corpus() -> tuple[list[tuple[str, str, str]], dict[str, str]]:
    """[(chunk_text, source_id, page_key)], page_key -> page text."""
    chunks, pages = [], {}
    with Session(create_db_engine(read_only=True)) as session:
        for unit in session.scalars(select(ContentUnit).order_by(ContentUnit.content_unit_id)):
            if unit.extraction_status == "text_unusable" or not unit.content_text:
                continue
            pages[unit.content_unit_id] = unit.content_text
            for c in chunk_content_unit(unit.content_unit_id, unit.content_text, "eval"):
                chunks.append((c.text, unit.source_id, unit.content_unit_id))
    return chunks, pages


def queries(pages: dict[str, str]) -> list[dict]:
    data = json.loads(OBJECTIVES.read_text(encoding="utf-8"))
    out = []
    for chapter in data["chapters"]:
        for o in chapter["objectives"]:
            relevant = {
                k
                for k, text in pages.items()
                if k.startswith(chapter["source_id"])
                and any(t.casefold() in text.casefold() for t in o["evidence_terms"])
            }
            if relevant:
                out.append(
                    {
                        "text": o["text"],
                        "language": chapter.get("language", "en"),
                        "source_id": chapter["source_id"],
                        "relevant": relevant,
                    }
                )
    return out


def evaluate(model: str, chunks, qs) -> dict:
    embedder = OllamaEmbedder(model)
    described = embedder.describe()
    started = time.monotonic()
    doc = np.array(embedder.embed([c[0] for c in chunks]), dtype=np.float32)
    doc_seconds = time.monotonic() - started
    q = np.array(embedder.embed([x["text"] for x in qs]), dtype=np.float32)
    doc /= np.linalg.norm(doc, axis=1, keepdims=True)
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    scores = q @ doc.T
    by_lang: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for i, item in enumerate(qs):
        ranked_pages: list[str] = []
        for j in np.argsort(-scores[i]):
            page = chunks[j][2]
            if page not in ranked_pages:
                ranked_pages.append(page)
            if len(ranked_pages) == 10:
                break
        hit5 = float(any(p in item["relevant"] for p in ranked_pages[:5]))
        rr = next((1 / (r + 1) for r, p in enumerate(ranked_pages) if p in item["relevant"]), 0.0)
        by_lang[item["language"]].append((hit5, rr))
        by_lang["all"].append((hit5, rr))
    return {
        "model_id": described.model_id,
        "dimension": described.dimension,
        "chunks": len(chunks),
        "queries": len(qs),
        "embed_seconds_corpus": round(doc_seconds, 2),
        "chunks_per_second": round(len(chunks) / doc_seconds, 1),
        "metrics": {
            lang: {
                "n": len(v),
                "recall_at_5": round(sum(h for h, _ in v) / len(v), 3),
                "mrr_at_10": round(sum(r for _, r in v) / len(v), 3),
            }
            for lang, v in sorted(by_lang.items())
        },
    }


def main(models: list[str]) -> int:
    chunks, pages = corpus()
    qs = queries(pages)
    results = {
        "ran_at": datetime.now(UTC).isoformat(),
        "models": [evaluate(m, chunks, qs) for m in models],
        "note": "objectives are AI-generated grounded drafts; relevance = verbatim evidence term "
        "on a page of the same chapter",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"embedding_eval_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["bge-m3", "qwen3-embedding:0.6b"]))
