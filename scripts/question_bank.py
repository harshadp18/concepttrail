"""Question-bank operations: generation pilot, validation and approved import.

    python -m scripts.question_bank pilot --count 10            # SYNTHETIC drafts via local Qwen
    python -m scripts.question_bank import FILE.json            # dry run of an approved import
    python -m scripts.question_bank import FILE.json --apply    # needs attributable reviews

`pilot` drafts synthetic practice items (no textbook evidence: the rights gate grants no
`local_llm_question_drafting` today), validates each deterministically and writes the drafts
and pass rate to `data_pipeline/data/logs/question_bank/` only. Nothing is approved and nothing
enters the database. `import` takes `[{"draft": QuestionDraft, "review": {"reviewer_user_id",
"decision", "rationale"}}]`; every review must name a real active teacher who is not the author.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.session import create_db_engine
from app.services.ai_generation import QuestionSpec, generate_question_draft
from app.services.llm import build_llm
from app.services.question_bank import (
    QuestionDraft,
    ReviewRefused,
    import_approved_question,
    validate_structure,
)
from data_pipeline.authorization import check_use
from scripts.seed_dev_auth import preflight

LOGS = Path(__file__).resolve().parents[1] / "data_pipeline/data/logs/question_bank"
PILOT_SPECS = [  # generic, owner-authored synthetic specs; no textbook text
    (6, "mathematics", "factors and multiples", "Find the highest common factor of two numbers"),
    (7, "mathematics", "fractions", "Add two fractions with unlike denominators"),
    (8, "mathematics", "linear equations", "Solve a linear equation in one variable"),
    (9, "science", "matter", "Classify a material as a pure substance or a mixture"),
    (10, "science", "electricity", "Apply Ohm's law to find current in a simple circuit"),
    (7, "english", "grammar", "Choose the verb form that agrees with its subject"),
    (8, "social_science", "civics", "Identify the purpose of a local government body"),
    (9, "social_science", "geography", "Read a value from a simple climate table"),
    (6, "science", "living things", "Name a characteristic shared by all living things"),
    (10, "mathematics", "probability", "Find the probability of a simple event"),
]


def pilot(count: int) -> int:
    llm = build_llm()
    identity = llm.identity()
    if not identity.available:
        print(f"model unavailable ({identity.detail}); nothing generated")
        return 1
    rows, passed = [], 0
    for i in range(count):
        cls, subject, topic, objective = PILOT_SPECS[i % len(PILOT_SPECS)]
        spec = QuestionSpec(cls, subject, topic, objective, difficulty=2 + i % 3, synthetic=True)
        draft, result = generate_question_draft(llm, spec, [], check_use)
        validation = validate_structure(draft) if draft else None
        passed += bool(validation and validation.ok)
        rows.append(
            {
                "spec": spec.__dict__,
                "status": result.status,
                "model_id": result.model_id,
                "draft": draft.model_dump(mode="json") if draft else None,
                "validation": validation.as_dict() if validation else None,
            }
        )
    LOGS.mkdir(parents=True, exist_ok=True)
    out = LOGS / f"synthetic_pilot_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(
        json.dumps(
            {
                "synthetic": True,
                "model": identity.model_id,
                "drafts": rows,
                "passed_validation": passed,
                "total": count,
                "approved": 0,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "total": count,
                "passed_validation": passed,
                "approved": 0,
                "written_to": str(out.relative_to(LOGS.parents[3])),
            }
        )
    )
    return 0


def import_file(path: Path, apply: bool) -> int:
    items = json.loads(path.read_text(encoding="utf-8"))
    engine = create_db_engine(read_only=not apply)
    if not preflight(engine).ok:
        print("refused: not the verified local development database")
        return 1
    results = []
    with Session(engine) as session:
        try:
            for item in items:
                draft = QuestionDraft.model_validate(item["draft"])
                results.append(import_approved_question(session, draft, item["review"]))
            if apply:
                session.commit()
            else:
                session.rollback()
        except (ReviewRefused, ValueError, KeyError) as exc:
            session.rollback()
            print(f"refused, nothing written: {exc}")
            return 1
    print(json.dumps({"mode": "apply" if apply else "dry_run", "results": results}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.question_bank")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("pilot")
    p.add_argument("--count", type=int, default=10)
    i = sub.add_parser("import")
    i.add_argument("file", type=Path)
    i.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "pilot":
        return pilot(args.count)
    return import_file(args.file, args.apply)


if __name__ == "__main__":
    sys.exit(main())
