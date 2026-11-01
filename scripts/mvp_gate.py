"""MVP backend readiness gate: an end-to-end check over public HTTP against a DEMO deployment.

    python -m scripts.mvp_gate --base-url http://127.0.0.1:8020 \\
        --database-url postgresql+psycopg://.../ct_demo [--with-llm]

It is separate from, and does not replace, the production release gate
(`python -m scripts.release_gate`), which stays strict. This gate answers one question: does the
backend work end to end on SYNTHETIC demo data so a frontend can be built against it? It proves
nothing about educational effectiveness, real learners or human review, and says so in its output.

Target: a backend started against a disposable demo database loaded by `scripts.demo_data`
(accounts come from `.local/demo_credentials.json`; secrets are never printed). The database URL
is used only to look up answer keys for the submission checks, read-only; scoring is done by the
API. A check that cannot run is reported as `not_run` with the reason, never as a pass; `--with-llm`
adds the live tutor check (needs a configured retrieval index and the local model).
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import QuestionOption

CREDS = Path(__file__).resolve().parents[1] / ".local" / "demo_credentials.json"
API = "/api/v1"


@dataclass
class Report:
    results: list[dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, status: str, detail: Any = "") -> None:
        self.results.append({"check": name, "status": status, "detail": detail})
        mark = {"pass": "PASS", "fail": "FAIL", "not_run": "NOT RUN"}[status]
        print(f"[{mark}] {name}" + (f" - {detail}" if detail and status != "pass" else ""))

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [r for r in self.results if r["status"] == "fail"]


class Gate:
    def __init__(self, base_url: str, database_url: str, with_llm: bool) -> None:
        self.http = httpx.Client(base_url=base_url, timeout=300)
        self.engine = create_engine(
            database_url, connect_args={"options": "-c search_path=concepttrail,public"}
        )
        self.with_llm = with_llm
        self.report = Report()
        self.creds = json.loads(CREDS.read_text())

    # --- helpers -----------------------------------------------------------------------
    def login(self, identifier: str) -> dict[str, str]:
        r = self.http.post(
            f"{API}/auth/login",
            json={"login_identifier": identifier, "credential": self.creds[identifier]},
        )
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def check(self, name: str, fn: Callable[[], Any]) -> Any:
        try:
            value = fn()
        except AssertionError as exc:
            self.report.add(name, "fail", str(exc) or "assertion failed")
        except Exception as exc:  # noqa: BLE001 - any failure is a failed check, with its type
            self.report.add(name, "fail", f"{type(exc).__name__}: {exc}")
        else:
            self.report.add(name, "pass")
            return value
        return None

    def answer(self, question: dict[str, Any], correct: bool) -> dict[str, Any]:
        with Session(self.engine) as s:
            options = list(
                s.scalars(
                    select(QuestionOption).where(
                        QuestionOption.question_id == question["question_id"]
                    )
                )
            )
        if question["answer_shape"] == "option_keys":
            keys = sorted(o.option_key for o in options if o.is_correct)
            return {"option_keys": keys if correct else keys[:1] + ["__none__"][:0] or ["A"]}
        pick = next(o for o in options if bool(o.is_correct) is correct)
        return {"option_key": pick.option_key}

    # --- the checks --------------------------------------------------------------------
    def run(self) -> Report:
        g = self.check
        g("health and readiness", self.health)
        student = "demo-l7-01"  # a strong learner with history
        practice = "demo-l7-04"  # the gate's own submissions go here (an 'inactive' profile)
        newcomer = "demo-l7-08"  # 'inactive' and never written to: the empty-state checks
        teacher_a, teacher_b = "demo.teacher.a@example.invalid", "demo.teacher.b@example.invalid"
        hs, hn, hp = self.login(student), self.login(newcomer), self.login(practice)
        ta, tb = self.login(teacher_a), self.login(teacher_b)
        me = self.http.get(f"{API}/me", headers=hs).json()

        g("student identity and server-derived scope", lambda: self.scope(hs, me))
        g(
            "catalog covers all five subjects; unavailable pairs are stated",
            lambda: self.catalog(hs),
        )
        chapter = g("chapter detail, topics and prerequisites", lambda: self.chapter(hs))
        g("questions hide answer keys", lambda: self.no_keys(hs, chapter))
        g(
            "deterministic scoring, idempotent replay, BKT update",
            lambda: self.attempts(hp, chapter),
        )
        g("progress, activity, weak areas and retry list", lambda: self.progress(hs, hn))
        g("recommendation is deterministic and explained", lambda: self.recommendation(hs))
        g("student cannot reach teacher or other-class data", lambda: self.student_denied(hs, me))
        classes = g("teacher classes, roster and learner progress", lambda: self.teacher(ta))
        g("teacher class isolation", lambda: self.isolation(ta, tb, classes))
        g("teacher review queue never allows approving demo content", lambda: self.review(ta))
        g(
            "interventions and notifications (proposed migrations applied)",
            lambda: self.extras(ta, tb, classes),
        )
        g("invalid input and unauthenticated access are refused", lambda: self.refusals(hs))
        if self.with_llm:
            g("grounded tutor answers or abstains with real citations", lambda: self.tutor(hs))
        else:
            self.report.add(
                "grounded tutor answers or abstains with real citations",
                "not_run",
                "pass --with-llm (needs RAG_INDEX_GENERATION and the local model)",
            )
        return self.report

    def health(self) -> None:
        assert self.http.get("/health").json() == {"status": "ok"}
        ready = self.http.get("/ready").json()
        assert ready["status"] == "ready", ready
        assert ready["content_release_mode"] == "demo", "this gate is for the demo deployment"

    def scope(self, h, me) -> None:
        assert me["roles"] == ["student"] and len(me["enrolled_classrooms"]) == 1
        assert me["enrolled_classrooms"][0]["grade_level"] == 7

    def catalog(self, h) -> None:
        body = self.http.get(f"{API}/catalog/classes", headers=h).json()
        assert body["grade_levels"] == [7] and len(body["subjects"]) == 5, body["subjects"]
        assert len(body["combinations"]) == 5
        assert {c["state"] for c in body["combinations"]} <= {
            "published",
            "demo_release",
            "not_available",
        }
        assert body["content_release"] == "demo"

    def chapter(self, h) -> dict[str, Any]:
        for c in self.http.get(f"{API}/curriculum", headers=h).json()["curricula"]:
            for item in c["items"]:
                detail = self.http.get(f"{API}/curriculum/items/{item['item_id']}", headers=h)
                assert detail.status_code == 200
                topics = [t for t in detail.json()["topics"] if t["question_count"] >= 2]
                if topics:
                    kc = topics[0]["kc_id"]
                    pre = self.http.get(f"{API}/topics/{kc}/prerequisites", headers=h)
                    assert pre.status_code == 200
                    if pre.json()["graph_available"]:
                        assert pre.json()["edge_provenance"] == "ai_proposed_demo"
                    return {"item_id": item["item_id"], "kc_id": kc}
        raise AssertionError("no chapter with servable questions in the demo class")

    def questions(self, h, kc_id):
        r = self.http.get(f"{API}/topics/{kc_id}/questions?limit=10", headers=h)
        assert r.status_code == 200
        return r.json()["questions"]

    def no_keys(self, h, chapter) -> None:
        questions = self.questions(h, chapter["kc_id"])
        assert questions
        text = json.dumps(questions)
        for forbidden in ("is_correct", "expected_answer", "explanation", "rubric"):
            assert forbidden not in text, f"{forbidden} leaked to the student"

    def attempts(self, h, chapter) -> None:
        question = self.questions(h, chapter["kc_id"])[0]
        key = f"mvp-gate-{uuid.uuid4().hex}"
        body = {
            "question_id": question["question_id"],
            "question_version": question["version"],
            "submitted_answer": self.answer(question, True),
            "idempotency_key": key,
        }
        first = self.http.post(f"{API}/attempts", headers=h, json=body)
        assert first.status_code in (200, 201), first.text
        assert first.json()["scored_correct"] is True and first.json()["bkt"]["updated"]
        replay = self.http.post(f"{API}/attempts", headers=h, json=body).json()
        assert replay["duplicate_replay"] is True
        assert replay["attempt_id"] == first.json()["attempt_id"]
        other = self.questions(h, chapter["kc_id"])[1]
        wrong = self.http.post(
            f"{API}/attempts",
            headers=h,
            json={
                "question_id": other["question_id"],
                "question_version": other["version"],
                "submitted_answer": self.answer(other, False),
                "idempotency_key": f"mvp-gate-{uuid.uuid4().hex}",
            },
        )
        assert wrong.json()["scored_correct"] is False and wrong.json()["score"] == 0
        bad = self.http.post(
            f"{API}/attempts",
            headers=h,
            json={
                **body,
                "idempotency_key": f"mvp-gate-{uuid.uuid4().hex}",
                "submitted_answer": {"option_key": "ZZZ"},
            },
        )
        assert bad.status_code == 422
        reuse = self.http.post(
            f"{API}/attempts",
            headers=h,
            json={
                **body,
                "question_id": other["question_id"],
                "question_version": other["version"],
            },
        )
        assert reuse.status_code == 409 or reuse.json().get("duplicate_replay") is False

    def progress(self, strong, newcomer) -> None:
        chapters = self.http.get(f"{API}/student/progress/chapters", headers=strong).json()
        assert chapters["subjects"] and chapters["thresholds_provisional"] is True
        assert any(c["topics_started"] for c in chapters["chapters"])
        empty = self.http.get(f"{API}/student/progress/chapters", headers=newcomer).json()
        assert all(c["accuracy"] is None for c in empty["chapters"] if not c["topics_started"])
        activity = self.http.get(f"{API}/student/activity?limit=5", headers=strong).json()
        assert activity["count"] >= 5 and len(activity["attempts"]) == 5
        assert (
            self.http.get(f"{API}/student/weak-areas", headers=newcomer).json()["weak_areas"] == []
        )
        assert "questions" in self.http.get(f"{API}/student/review", headers=strong).json()

    def recommendation(self, h) -> None:
        first = self.http.get(f"{API}/student/recommendation", headers=h).json()
        again = self.http.get(f"{API}/student/recommendation", headers=h).json()
        assert first == again, "recommendation is not deterministic"
        assert first["status"] in ("ok", "insufficient_data")
        if first["status"] == "ok":
            assert first["rationale"] and first["category"] in (
                "remediate_prerequisite",
                "continue",
                "new",
            )

    def student_denied(self, h, me) -> None:
        room = me["enrolled_classrooms"][0]["classroom_id"]
        for path in (
            "/teacher/classes",
            f"/teacher/classes/{room}/dashboard",
            f"/teacher/classes/{room}/learners",
            "/teacher/review/questions",
        ):
            code = self.http.get(f"{API}{path}", headers=h).status_code
            assert code == 403, f"{path} returned {code} for a student"

    def teacher(self, h) -> list[dict[str, Any]]:
        classes = self.http.get(f"{API}/teacher/classes", headers=h).json()["classes"]
        assert len(classes) == 5
        room = next(c for c in classes if c["grade_level"] == 7)
        cid = room["classroom_id"]
        roster = self.http.get(f"{API}/teacher/classes/{cid}/learners", headers=h).json()
        assert roster["count"] == 10 and any(r["attempts"] == 0 for r in roster["learners"])
        active = next(r for r in roster["learners"] if r["attempts"])
        detail = self.http.get(
            f"{API}/teacher/classes/{cid}/learners/{active['learner_id']}/progress", headers=h
        )
        assert detail.status_code == 200 and detail.json()["chapters"]
        dash = self.http.get(f"{API}/teacher/classes/{cid}/dashboard", headers=h).json()
        assert dash["learner_count"] == 10 and dash["attempt_summary"]["total_attempts"] > 0
        weak = self.http.get(f"{API}/teacher/classes/{cid}/weak-areas", headers=h)
        assert weak.status_code == 200 and weak.json()["thresholds_provisional"] is True
        return classes

    def isolation(self, ta, tb, classes) -> None:
        room6 = next(c for c in classes if c["grade_level"] == 6)["classroom_id"]
        assert len(self.http.get(f"{API}/teacher/classes", headers=tb).json()["classes"]) == 1
        for path in ("/dashboard", "/learners", "/weak-areas"):
            r = self.http.get(f"{API}/teacher/classes/{room6}{path}", headers=tb)
            assert r.status_code == 403, f"teacher B reached class 6 via {path}"

    def review(self, h) -> None:
        queue = self.http.get(f"{API}/teacher/review/questions?limit=5", headers=h).json()
        assert queue["questions"], "the demo review queue is empty"
        qid = queue["questions"][0]["question_id"]
        refused = self.http.post(
            f"{API}/teacher/review/questions/{qid}",
            headers=h,
            json={"decision": "approved", "rationale": "gate probe: must be refused"},
        )
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "review_refused"

    def extras(self, ta, tb, classes) -> None:
        room7 = next(c for c in classes if c["grade_level"] == 7)["classroom_id"]
        listed = self.http.get(f"{API}/teacher/classes/{room7}/interventions", headers=ta)
        assert listed.status_code == 200 and listed.json()["count"] >= 1
        assert all(
            i["note"] is None or "SYNTHETIC-DEMO" in i["note"]
            for i in listed.json()["interventions"]
            if i["intervention_id"]
        )
        notes = self.http.get(f"{API}/notifications", headers=tb).json()
        assert notes["count"] >= 1
        assert all(
            n["is_synthetic"] or n["kind"] == "intervention_update" for n in notes["notifications"]
        )

    def refusals(self, h) -> None:
        assert self.http.get(f"{API}/student/activity").status_code == 401
        assert self.http.get(f"{API}/student/activity?limit=0", headers=h).status_code == 422
        missing = self.http.get(f"{API}/topics/NOPE/questions", headers=h)
        assert missing.status_code == 404 and "error" in missing.json()
        login = self.http.post(
            f"{API}/auth/login", json={"login_identifier": "demo-l7-01", "credential": "00000000"}
        )
        assert login.status_code == 401

    def tutor(self, h) -> None:
        body = {"question": "How do I add two fractions with the same denominator?"}
        r = self.http.post(f"{API}/doubts", headers=h, json=body)
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["grounding"] in ("grounded", "abstained")
        if out["grounding"] == "grounded":
            assert out["citations"], "a grounded answer must carry citations"
            with Session(self.engine) as s:
                from app.db.models import SourceDocument

                for c in out["citations"]:
                    assert s.get(SourceDocument, c["source_id"]) is not None, c
        unanswerable = self.http.post(
            f"{API}/doubts", headers=h, json={"question": "Who won the cricket world cup in 2011?"}
        ).json()
        assert unanswerable["grounding"] == "abstained", "off-topic question was answered"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.mvp_gate")
    parser.add_argument("--base-url", default="http://127.0.0.1:8020")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--with-llm", action="store_true")
    args = parser.parse_args(argv)
    if not CREDS.exists():
        print("demo credentials missing: run scripts.demo_data load first", file=sys.stderr)
        return 2
    report = Gate(args.base_url, args.database_url, args.with_llm).run()
    passed = sum(r["status"] == "pass" for r in report.results)
    not_run = sum(r["status"] == "not_run" for r in report.results)
    print(
        f"\nMVP backend readiness: {passed} passed, {len(report.failed)} failed, "
        f"{not_run} not run.\nThis is synthetic-data evidence of working software. It is NOT "
        "production readiness, human review or evidence of learning."
    )
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
