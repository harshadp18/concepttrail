"""End-to-end student journey against the running backend, through public HTTP only.

    python -m scripts.demo_walkthrough                # read-only steps
    python -m scripts.demo_walkthrough --submit       # also submits answers (writes attempts)
    python -m scripts.demo_walkthrough --submit --explain --base-url http://127.0.0.1:8010

Uses the synthetic dev student from `.local/dev_auth_credentials.json` (never printed). Every
product step is an HTTP call. The script reads answer keys from the database (read-only) only to
choose one correct and one incorrect answer on purpose; scoring is done by the API.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import QuestionOption
from app.db.session import create_db_engine

CREDS = Path(__file__).resolve().parents[1] / ".local/dev_auth_credentials.json"


def step(n: int, label: str, value: object) -> None:
    print(f"{n:>2}. {label}: {json.dumps(value, ensure_ascii=False, default=str)[:420]}")


def answer_for(db: Session, question: dict, want_correct: bool) -> dict | None:
    options = db.scalars(
        select(QuestionOption).where(QuestionOption.question_id == question["question_id"])
    ).all()
    if question["answer_shape"] == "option_keys":
        correct = sorted(o.option_key for o in options if o.is_correct)
        wrong = [o.option_key for o in options if not o.is_correct][:1]
        return {"option_keys": correct if want_correct else wrong}
    pick = next((o for o in options if bool(o.is_correct) is want_correct), None)
    return {"option_key": pick.option_key} if pick else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.demo_walkthrough")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--submit", action="store_true", help="submit answers (writes attempts)")
    parser.add_argument("--explain", action="store_true", help="ask a grounded doubt (local model)")
    args = parser.parse_args(argv)
    creds = json.loads(CREDS.read_text(encoding="utf-8"))["student"]
    api = httpx.Client(base_url=args.base_url, timeout=300)
    login = api.post(
        "/api/v1/auth/login",
        json={"login_identifier": creds["login_identifier"], "credential": creds["pin"]},
    )
    if login.status_code != 200:
        print(f"login failed: {login.status_code}")
        return 1
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    step(
        1,
        "POST /auth/login",
        {"status": login.status_code, "expires_in": login.json()["expires_in"]},
    )
    me = api.get("/api/v1/me", headers=h).json()
    grade = me["enrolled_classrooms"][0]["grade_level"]
    step(2, "GET /me", {"roles": me["roles"], "grade": grade})
    curriculum = api.get("/api/v1/curriculum", headers=h).json()
    step(
        3,
        "GET /curriculum",
        [
            (c["grade_level"], c["subject"]["subject_id"], c["coverage"]["state"])
            for c in curriculum["curricula"]
        ],
    )
    chosen = None
    for c in curriculum["curricula"]:
        for item in c["items"]:
            topics = api.get(f"/api/v1/curriculum/items/{item['item_id']}/topics", headers=h)
            if topics.status_code == 200 and any(
                t["question_count"] for t in topics.json()["topics"]
            ):
                chosen = topics.json()
                break
        if chosen:
            break
    if chosen is None:
        print("no chapter with servable questions for this learner")
        return 1
    step(
        4,
        f"GET /curriculum/items/{chosen['item_id']}/topics",
        [(t["kc_id"], t["name"], t["question_count"]) for t in chosen["topics"]],
    )
    kc = next(t for t in chosen["topics"] if t["question_count"])
    questions = api.get(f"/api/v1/topics/{kc['kc_id']}/questions", headers=h).json()["questions"]
    step(
        5,
        f"GET /topics/{kc['kc_id']}/questions",
        [(q["item_type"], q["answer_shape"], q["stem"][:50]) for q in questions],
    )
    if args.submit:
        with Session(create_db_engine(read_only=True)) as db:
            plan = [(q, i == 0) for i, q in enumerate(questions[:3])]
            for q, want in plan:
                answer = answer_for(db, q, want)
                if answer is None:
                    continue
                r = api.post(
                    "/api/v1/attempts",
                    headers=h,
                    json={
                        "question_id": q["question_id"],
                        "question_version": q["version"],
                        "submitted_answer": answer,
                        "idempotency_key": f"walkthrough-{uuid.uuid4().hex}",
                    },
                )
                body = r.json()
                step(
                    6,
                    f"POST /attempts ({q['item_type']}, intended {'right' if want else 'wrong'})",
                    {
                        "status": r.status_code,
                        "scored_correct": body.get("scored_correct"),
                        "method": body.get("score_method"),
                        "bkt": body.get("bkt"),
                    },
                )
    progress = api.get("/api/v1/student/progress", headers=h).json()
    step(9, "GET /student/progress", progress["mastery_estimates"][:3])
    rec = api.get("/api/v1/student/recommendation", headers=h).json()
    step(10, "GET /student/recommendation", rec)
    if args.explain:
        doubt = api.post(
            "/api/v1/doubts",
            headers=h,
            json={"question": questions[0]["stem"], "kc_id": kc["kc_id"]},
        )
        body = doubt.json()
        step(
            11,
            "POST /doubts (grounded)",
            {
                "status": body.get("status"),
                "grounding": body.get("grounding"),
                "explanation": (body.get("explanation") or "")[:160],
                "citations": body.get("citations"),
            },
        )
        off = api.post(
            "/api/v1/doubts",
            headers=h,
            json={
                "question": "Explain the causes of the French Revolution in detail.",
                "subject_id": "mathematics",
            },
        )
        step(
            14,
            "POST /doubts (out of scope)",
            {"status": off.json().get("status"), "grounding": off.json().get("grounding")},
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
