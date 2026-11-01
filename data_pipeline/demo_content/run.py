"""`python -m data_pipeline.demo_content.run <stage>`: generate, assemble, import.

    generate [--selection FILE] [--max-kcs N]   local Qwen batches (resumable)
    topup                                       v3 single-answer questions for thin KCs
    assemble                                    deterministic dataset + validation report
    import [--apply]                            dry run by default; one transaction

Generation is breadth-first: KCs and in-chapter edges for every chapter, then cross-chapter
edges per subject, then questions round-robin across chapters, so an interrupted run still
covers every available class-subject combination. Rerunning skips completed batches.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from app.services.embeddings import EmbeddingError, OllamaEmbedder
from data_pipeline.demo_content import assemble, generate
from data_pipeline.demo_content.generate import WORK

SELECTION = WORK / "selection_1.json"
DATASET = WORK / "demo_dataset.json"
LOG = WORK / "generation.log"


def log(message: str) -> None:
    line = f"{datetime.now(UTC):%H:%M:%S} {message}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def chapters(selection: Path) -> list[dict]:
    return [c for c in json.loads(selection.read_text()) if c.get("source_id")]


def _sha(chapter: dict) -> str:
    return generate.load_artifact(chapter["artifact"])["document"]["pdf_sha256"]


def all_kcs(chs: list[dict], max_kcs: int) -> dict[str, list[dict]]:
    out = {}
    for ch in chs:
        kcs, _ = assemble.chapter_kcs(ch)
        out[ch["source_id"]] = kcs[:max_kcs]
    registry = assemble.allocate_ids([k for v in out.values() for k in v])
    for kcs in out.values():
        for kc in kcs:
            kc["kc_id"] = registry[kc["stable_key"]]
    return out


def stage_generate(selection: Path, max_kcs: int) -> int:
    llm = generate.generation_llm()
    if not llm.identity().available:
        log("local model unavailable; nothing generated (no cloud fallback)")
        return 1
    chs = chapters(selection)
    for ch in chs:
        generate.draft_kcs(llm, ch, log)
    kcs = all_kcs(chs, max_kcs)
    for ch in chs:
        context = (
            f"Class {ch['class_level']} {ch['subject_id']}, chapter '{ch['chapter']}'. "
            "All knowledge components below come from this chapter."
        )
        generate.draft_edges(
            llm, ch["source_id"], _sha(ch), kcs[ch["source_id"]], "chapter", context, log
        )
    by_subject: dict[str, list[dict]] = defaultdict(list)
    for ch in chs:
        by_subject[ch["subject_id"]].append(ch)
    for subject, subject_chs in sorted(by_subject.items()):
        if len(subject_chs) < 2:
            continue
        pool = [k for c in subject_chs for k in kcs[c["source_id"]]]
        anchor = max(subject_chs, key=lambda c: c["class_level"])
        context = (
            f"{subject}: knowledge components from different classes (class in brackets). "
            "Propose only edges ACROSS chapters where an earlier-class skill is genuinely "
            "used by a later-class skill."
        )
        generate.draft_edges(
            llm, anchor["source_id"], _sha(anchor), pool, f"subject-{subject}", context, log
        )
    queue = []
    for rank in range(max_kcs):  # round-robin across chapters
        for ch in chs:
            if rank < len(kcs[ch["source_id"]]):
                queue.append((ch, kcs[ch["source_id"]][rank]))
    for ch, kc in queue:
        generate.draft_questions(llm, ch, kc, log)
    log("generation pass complete")
    return 0


TOPUP_TARGET = 4


def current_questions() -> dict[str, list[str]]:
    """Stems per KC already in the database (read-only engine)."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.models import Question, QuestionKc
    from app.db.session import create_db_engine

    out: dict[str, list[str]] = defaultdict(list)
    with Session(create_db_engine(read_only=True)) as db:
        for kc_id, stem in db.execute(
            select(QuestionKc.kc_id, Question.stem).join(
                Question, Question.question_id == QuestionKc.question_id
            )
        ):
            out[kc_id].append(stem or "")
    return out


def stage_topup(selection: Path, max_kcs: int, target: int = TOPUP_TARGET) -> int:
    """v3 single-answer questions for KCs below `target`, fewest questions first."""
    llm = generate.generation_llm()
    if not llm.identity().available:
        log("local model unavailable; nothing generated (no cloud fallback)")
        return 1
    chs = chapters(selection)
    kcs = all_kcs(chs, max_kcs)
    existing = current_questions()
    queue = []
    for ch in chs:
        for kc in kcs[ch["source_id"]]:
            have = len(existing.get(kc["kc_id"], []))
            if have < target:
                queue.append((have, ch["class_level"], ch, kc))
    queue.sort(key=lambda q: (q[0], q[1], q[3]["kc_id"]))
    log(f"topup: {len(queue)} KCs below {target} questions")
    for have, _cls, ch, kc in queue:
        generate.draft_topup_questions(
            llm, ch, kc, existing.get(kc["kc_id"], []), target - have, log
        )
    log("topup pass complete")
    return 0


def stage_assemble(selection: Path, max_kcs: int) -> dict:
    chs = chapters(selection)
    kcs = all_kcs(chs, max_kcs)
    flat = [k for c in chs for k in kcs[c["source_id"]]]
    by_local = {k["local_id"]: k for k in flat}
    by_kc_id: dict[str, dict] = {}
    for kc in flat:  # one row per KC; a concept seen in two chapters keeps both mappings
        row = by_kc_id.setdefault(kc["kc_id"], {**kc, "inventory_ids": []})
        row["inventory_ids"] = sorted(set(row["inventory_ids"]) | {kc["inventory_id"]})
    proposals = []
    for path in sorted(WORK.glob("*/edges_*.json")):
        if path.name.endswith(".failed.json"):
            continue
        batch = json.loads(path.read_text(encoding="utf-8"))
        proposals += [(e, batch["batch"]) for e in batch["output"]["edges"]]
    edges, edge_rejects = assemble.accept_edges(proposals, by_local, [])
    graph_errors = assemble.check_graph(list(by_kc_id.values()), edges)
    candidates, question_rejects = [], []
    existing = current_questions()
    for ch in chs:
        sha = _sha(ch)
        for kc in kcs[ch["source_id"]]:
            for name in (
                f"questions_{kc['local_id']}.json",
                f"questions_topup_{kc['local_id']}.json",
            ):
                path = WORK / ch["source_id"] / name
                if not path.exists():
                    continue
                batch = json.loads(path.read_text(encoding="utf-8"))
                if batch.get("status") != "ok":
                    continue
                if batch.get("prompt_version") == generate.TOPUP_PROMPT_VERSION:
                    batch, rejects = assemble.topup_filters(batch, existing.get(kc["kc_id"], []))
                    question_rejects += [{"kc_id": kc["kc_id"], **r} for r in rejects]
                drafts, rejects = assemble.question_drafts(ch, kc, batch, sha)
                candidates += [(kc["kc_id"], d) for d in drafts]
                question_rejects += [{"kc_id": kc["kc_id"], **r} for r in rejects]
    kc_text = {k["kc_id"]: f"{k['name']}. {k['learning_objective']}" for k in flat}
    try:
        embedder = OllamaEmbedder("bge-m3")
        kept, off_topic = assemble.relevance_filter(kc_text, candidates, embedder.embed)
        relevance = embedder.describe().model_id
    except EmbeddingError:
        kept, off_topic, relevance = [d for _, d in candidates], [], "not_checked"
    question_rejects += off_topic
    questions = [d.model_dump(mode="json") for d in kept]
    dataset = {
        "generated_at": datetime.now(UTC).isoformat(),
        "release": "demo",
        "prompt_version": generate.PROMPT_VERSION,
        "chapters": chs,
        "kcs": sorted(by_kc_id.values(), key=lambda k: k["kc_id"]),
        "edges": edges,
        "questions": questions,
        "graph_errors": graph_errors,
        "rejected": {"edges": edge_rejects, "questions": question_rejects},
        "relevance_check": relevance,
    }
    assemble.write_json(DATASET, dataset)
    return dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m data_pipeline.demo_content.run")
    parser.add_argument("stage", choices=("generate", "topup", "assemble", "import"))
    parser.add_argument("--selection", type=Path, default=SELECTION)
    parser.add_argument("--max-kcs", type=int, default=6)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    WORK.mkdir(parents=True, exist_ok=True)
    if args.stage == "generate":
        return stage_generate(args.selection, args.max_kcs)
    if args.stage == "topup":
        return stage_topup(args.selection, args.max_kcs)
    if args.stage == "assemble":
        d = stage_assemble(args.selection, args.max_kcs)
        print(
            json.dumps(
                {
                    "chapters": len(d["chapters"]),
                    "kcs": len(d["kcs"]),
                    "edges": len(d["edges"]),
                    "questions": len(d["questions"]),
                    "graph_errors": d["graph_errors"],
                    "rejected_edges": len(d["rejected"]["edges"]),
                    "rejected_questions": len(d["rejected"]["questions"]),
                },
                indent=2,
            )
        )
        return 0 if not d["graph_errors"] else 1
    from data_pipeline.demo_content.importer import run_import

    return run_import(DATASET, apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
