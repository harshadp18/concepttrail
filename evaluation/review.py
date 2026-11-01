"""Independent human review: build a blind review packet, ingest completed reviews, report.

    python -m evaluation.review make   --n 60 --seed 1     # -> .local/evaluation/review_packets/
    python -m evaluation.review ingest PACKET_DIR          # reads PACKET_DIR/completed/*.csv

The packet gives each reviewer the question WITHOUT the stored key and asks for their own answer
first. Stored keys stay in `key_sealed.json` (the reviewer never needs it). Reviews are only
valid evidence if the reviewer did not author or generate the item, answered before seeing the
key, and is competent in the subject (Hindi items: Hindi-fluent). A single reviewer disagreeing
with a key flags the item for adjudication; it does not prove the key wrong. Nothing is computed
for a cell with fewer than `stats.MIN_STRATUM` reviewed items, and no review is invented.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import KnowledgeComponent, Question, QuestionKc, QuestionOption
from app.db.session import create_db_engine
from evaluation.bank_metrics import question_rows
from evaluation.stats import MIN_STRATUM, cohen_kappa, rate

ROOT = Path(__file__).resolve().parents[1]
PACKETS = ROOT / ".local/evaluation/review_packets"
RATING_FIELDS = ("kc_alignment", "age_language_fit", "distractor_quality")
YES_NO = ("yes", "no")
REVIEWER_COLUMNS = [
    "reviewer_id",
    "blind_answer",
    "ambiguous",
    "kc_alignment",
    "age_language_fit",
    "distractor_quality",
    "explanation_correct",
    "passage_dependent",
    "decision",
    "comments",
]
SHOWN_COLUMNS = [
    "item_id",
    "class_level",
    "subject_id",
    "language",
    "chapter_title",
    "item_type",
    "answer_format",
    "kc_name",
    "kc_objective",
    "stem",
    "options",
    "explanation_shown",
]
FORMATS = {
    "single_choice": "one option key, e.g. C",
    "true_false": "True or False",
    "multiple_select": "all correct option keys separated by ';', e.g. A;C",
}


def stored_key(item_type: str, options: list[QuestionOption], expected: dict | None) -> str | None:
    correct = sorted(o.option_key for o in options if o.is_correct)
    if item_type == "single_choice":
        return correct[0] if len(correct) == 1 else None
    if item_type == "multiple_select":
        return ";".join(correct) if correct else None
    if item_type == "true_false":
        value = (expected or {}).get("value")
        return None if not isinstance(value, bool) else ("True" if value else "False")
    return None


def normalise_answer(item_type: str, text: str) -> str:
    text = (text or "").strip()
    if item_type == "multiple_select":
        return ";".join(
            sorted({p.strip().upper() for p in text.replace(",", ";").split(";") if p.strip()})
        )
    if item_type == "true_false":
        return {"true": "True", "t": "True", "false": "False", "f": "False"}.get(
            text.casefold(), text
        )
    return text.upper()


def stratified_sample(rows: list[dict], n: int, seed: int) -> list[dict]:
    """Balanced by subject first, then spread over (class, item type) inside each subject."""
    rng = random.Random(seed)
    subjects: dict[str, dict[tuple, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        subjects[r["subject_id"]][(r["class_level"], r["item_type"])].append(r)
    cursors = {}
    for subject, strata in subjects.items():
        for group in strata.values():
            rng.shuffle(group)
        order = sorted(strata)
        rng.shuffle(order)
        cursors[subject] = {"order": order, "i": 0, "strata": strata}
    chosen: list[dict] = []
    subject_order = sorted(subjects)
    while len(chosen) < n and any(any(g for g in subjects[s].values()) for s in subject_order):
        for subject in subject_order:
            c = cursors[subject]
            for _ in range(len(c["order"])):  # next non-empty stratum for this subject
                key = c["order"][c["i"] % len(c["order"])]
                c["i"] += 1
                if c["strata"][key]:
                    chosen.append(c["strata"][key].pop())
                    break
            if len(chosen) >= n:
                break
    return sorted(chosen, key=lambda r: r["question_id"])


def make_packet(session: Session, n: int, seed: int, out: Path | None = None) -> Path:
    rows = [r for r in question_rows(session) if r["deliverable"]]
    sample = stratified_sample(rows, n, seed)
    packet = out or PACKETS / f"packet_{datetime.now(UTC):%Y%m%dT%H%M%SZ}_n{len(sample)}_s{seed}"
    (packet / "completed").mkdir(parents=True, exist_ok=True)
    kcs = {k.kc_id: k for k in session.scalars(select(KnowledgeComponent))}
    keys, shown = {}, []
    for r in sample:
        q = session.get(Question, r["question_id"])
        options = sorted(
            session.scalars(
                select(QuestionOption).where(QuestionOption.question_id == q.question_id)
            ),
            key=lambda o: o.option_key,
        )
        kc = kcs.get(
            session.scalar(select(QuestionKc.kc_id).where(QuestionKc.question_id == q.question_id))
        )
        keys[q.question_id] = {
            "item_type": q.item_type,
            "stored_key": stored_key(q.item_type, options, q.expected_answer),
            "class_level": r["class_level"],
            "subject_id": r["subject_id"],
            "language": r["language"],
            "chapter": r["chapter"],
        }
        shown.append(
            {
                "item_id": q.question_id,
                "class_level": r["class_level"],
                "subject_id": r["subject_id"],
                "language": r["language"],
                "chapter_title": r["chapter_title"],
                "item_type": q.item_type,
                "answer_format": FORMATS[q.item_type],
                "kc_name": kc.name if kc else "",
                "kc_objective": kc.description if kc else "",
                "stem": q.stem,
                "options": " | ".join(f"{o.option_key}: {o.option_text}" for o in options),
                "explanation_shown": "",
            }
        )
    with (packet / "items.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHOWN_COLUMNS + REVIEWER_COLUMNS)
        writer.writeheader()
        writer.writerows(shown)
    (packet / "key_sealed.json").write_text(
        json.dumps(keys, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (packet / "PROTOCOL.txt").write_text(
        "Independent review protocol\n"
        "1. Do not open key_sealed.json. Answer each item yourself first (blind_answer).\n"
        "2. ambiguous: yes if more than one option is defensible or context is missing.\n"
        "3. kc_alignment / age_language_fit / distractor_quality: 1 poor, 2 acceptable, 3 good.\n"
        "4. passage_dependent: yes if the stem needs text the student cannot see.\n"
        "5. decision: accept, revise or reject. Add comments for anything not accept.\n"
        "6. Save a copy as completed/<your_reviewer_id>.csv. Use a pseudonymous reviewer_id.\n"
        "7. You must not be the author or generator of these items. Hindi items: Hindi reader.\n"
        "Content here is AI-generated development material awaiting exactly this review.\n",
        encoding="utf-8",
    )
    return packet


def read_reviews(packet: Path) -> tuple[list[dict], list[str]]:
    reviews, errors = [], []
    for path in sorted((packet / "completed").glob("*.csv")):
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for number, row in enumerate(csv.DictReader(handle), start=2):
                if (
                    not (row.get("blind_answer") or "").strip()
                    and not (row.get("decision") or "").strip()
                ):
                    continue  # unreviewed row
                problem = None
                if not (row.get("reviewer_id") or "").strip():
                    problem = "missing reviewer_id"
                elif (row.get("ambiguous") or "").strip().lower() not in YES_NO:
                    problem = "ambiguous must be yes/no"
                elif (row.get("decision") or "").strip().lower() not in (
                    "accept",
                    "revise",
                    "reject",
                ):
                    problem = "decision must be accept/revise/reject"
                elif any((row.get(f) or "").strip() not in ("1", "2", "3") for f in RATING_FIELDS):
                    problem = "ratings must be 1, 2 or 3"
                if problem:
                    errors.append(f"{path.name}:{number}: {problem}")
                else:
                    reviews.append({**row, "_file": path.name})
    return reviews, errors


def report(packet: Path) -> dict[str, Any]:
    keys = json.loads((packet / "key_sealed.json").read_text(encoding="utf-8"))
    reviews, errors = read_reviews(packet)
    rows = []
    for r in reviews:
        meta = keys.get(r["item_id"])
        if meta is None:
            errors.append(f"{r['_file']}: unknown item {r['item_id']}")
            continue
        answer = normalise_answer(meta["item_type"], r["blind_answer"])
        rows.append(
            {
                **meta,
                "item_id": r["item_id"],
                "reviewer": r["reviewer_id"].strip(),
                "agrees": bool(meta["stored_key"]) and answer == meta["stored_key"],
                "ambiguous": r["ambiguous"].strip().lower() == "yes",
                "accept": r["decision"].strip().lower() == "accept",
                "reject": r["decision"].strip().lower() == "reject",
                "passage_dependent": (r.get("passage_dependent") or "").strip().lower() == "yes",
                "expl_wrong": (r.get("explanation_correct") or "").strip().lower() == "no",
                **{f: int(r[f]) for f in RATING_FIELDS},
            }
        )
    if not rows:
        return {
            "status": "not_measured",
            "reason": "no completed human reviews found",
            "completed_files": len(list((packet / "completed").glob("*.csv"))),
            "errors": errors,
        }

    def cells(pred) -> dict:
        out: dict[str, Any] = {"overall": rate(sum(pred(r) for r in rows), len(rows))}
        for dim in ("class_level", "subject_id", "language", "item_type", "chapter"):
            groups: dict[str, list[dict]] = defaultdict(list)
            for r in rows:
                groups[str(r[dim])].append(r)
            out[dim] = {k: rate(sum(pred(r) for r in g), len(g)) for k, g in sorted(groups.items())}
        return out

    by_item: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_item[r["item_id"]].append(r)
    both = {i: g for i, g in by_item.items() if len({x["reviewer"] for x in g}) >= 2}
    pair = [(g[0], g[1]) for g in both.values()]
    return {
        "status": "measured",
        "review_records": len(rows),
        "items_reviewed": len(by_item),
        "reviewers": sorted({r["reviewer"] for r in rows}),
        "scale_note": f"pilot scale: cells under {MIN_STRATUM} items are insufficient_data",
        "blind_answer_agrees_with_stored_key": cells(lambda r: r["agrees"]),
        "disputed_key_note": "a disagreement flags the item for adjudication by a second reviewer",
        "ambiguous": cells(lambda r: r["ambiguous"]),
        "passage_dependent": cells(lambda r: r["passage_dependent"]),
        "explanation_marked_wrong": cells(lambda r: r["expl_wrong"]),
        "decision_accept": cells(lambda r: r["accept"]),
        "decision_reject": cells(lambda r: r["reject"]),
        "mean_ratings": {f: round(sum(r[f] for r in rows) / len(rows), 3) for f in RATING_FIELDS},
        "inter_rater": {
            "items_with_two_reviewers": len(pair),
            "kappa_decision": cohen_kappa(
                ["accept" if a["accept"] else "other" for a, _ in pair],
                ["accept" if b["accept"] else "other" for _, b in pair],
            )
            if len(pair) >= MIN_STRATUM
            else "insufficient_data",
            "kappa_blind_answer_vs_key": cohen_kappa(
                [str(a["agrees"]) for a, _ in pair], [str(b["agrees"]) for _, b in pair]
            )
            if len(pair) >= MIN_STRATUM
            else "insufficient_data",
        },
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.review")
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("make")
    make.add_argument("--n", type=int, default=60)
    make.add_argument("--seed", type=int, default=1)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("packet", type=Path)
    args = parser.parse_args(argv)
    if args.command == "make":
        with Session(create_db_engine(read_only=True)) as session:
            print(make_packet(session, args.n, args.seed))
        return 0
    print(json.dumps(report(args.packet), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
