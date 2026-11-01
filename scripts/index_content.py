"""Chunk and embed eligible content units into `embedding_chunk` (one index generation).

    python -m scripts.index_content                       # dry run: chunks planned, no writes
    python -m scripts.index_content --apply               # chunk + embed in one transaction
    python -m scripts.index_content --apply --model bge-m3 --generation ig-dev-1-bge-m3

Rights: `indexing_retrieval` per source and exact bytes (`data_pipeline.authorization`). The
embedding model is local (Ollama); its identity (name + digest) is stored with every vector and
a generation never mixes models. Idempotent: chunk IDs are deterministic and only vectors that
are missing are computed. Nothing is deleted. Refuses unless the target is the verified local
development database.
"""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import EmbeddingChunk
from app.db.session import create_db_engine
from app.services.embeddings import EmbeddingError, OllamaEmbedder
from app.services.rag import embed_chunks, generation_model, ingest_eligible_content
from data_pipeline.authorization import check_use
from scripts.seed_dev_auth import preflight

DEFAULT_MODEL = "bge-m3"
DEFAULT_GENERATION = "ig-dev-1-bge-m3"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.index_content")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--generation", default=DEFAULT_GENERATION)
    args = parser.parse_args(argv)
    engine = create_db_engine(read_only=not args.apply)
    pre = preflight(engine)
    if not pre.ok:
        print(f"refused: {pre.problems}")
        return 1
    with Session(engine) as session:
        try:
            report = ingest_eligible_content(session, args.generation, check_use, write=args.apply)
            existing_model = generation_model(session, args.generation)
            embedded = 0
            if args.apply:
                embedder = OllamaEmbedder(args.model, get_settings().ollama_base_url)
                embedded = embed_chunks(session, embedder, args.generation)
                session.commit()
            else:
                session.rollback()
        except (EmbeddingError, ValueError) as exc:
            session.rollback()
            print(f"refused, nothing written: {type(exc).__name__}: {exc}")
            return 1
    with Session(create_db_engine(read_only=True)) as check:
        stored = check.scalar(
            select(func.count())
            .select_from(EmbeddingChunk)
            .where(EmbeddingChunk.index_generation == args.generation)
        )
        with_vectors = check.scalar(
            select(func.count())
            .select_from(EmbeddingChunk)
            .where(
                EmbeddingChunk.index_generation == args.generation,
                EmbeddingChunk.embedding.is_not(None),
            )
        )
        model_id = generation_model(check, args.generation)
    reasons: dict[str, int] = {}
    for reason in report.excluded.values():
        reasons[reason] = reasons.get(reason, 0) + 1
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry_run",
                "generation": args.generation,
                "eligible_units": report.eligible_units,
                "chunks_created": report.chunks_created,
                "chunks_already_present": report.chunks_existing,
                "excluded_by_reason": reasons,
                "vectors_computed": embedded,
                "previous_model": existing_model,
                "stored_chunks": stored,
                "stored_with_vectors": with_vectors,
                "model_id": model_id,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
