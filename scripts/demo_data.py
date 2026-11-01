"""Load a reproducible, clearly labelled SYNTHETIC demo population into a DISPOSABLE database.

    python -m scripts.demo_data load   --database-url URL --confirm-disposable [--seed 7]
    python -m scripts.demo_data verify --database-url URL

The target must be a restored copy of the project database (it needs curriculum, KCs and
questions): create one with `pg_restore` into a database whose name starts with `ct_demo`, see
docs/MVP_SCOPE.md. The loader REFUSES unless all of these hold: the database name starts with
`ct_demo`; it is not the database configured for the application (same host, port and name); the
`concepttrail` schema exists; and `--confirm-disposable` was given. It never touches `.env`, never
deletes or updates an existing row, and is idempotent (deterministic IDs and idempotency keys).

What it creates, all marked synthetic (`SYNTHETIC-DEMO` school label, `DEMO` display names,
`demo-` / `demo.` logins): two teachers, one classroom per class level that has servable
content, ten learners per classroom with different (seeded) abilities, and practice histories
that go through the SAME `submit_attempt` path as a real learner (deterministic scoring, BKT
update, idempotency), so mastery and progress are derived from the synthetic attempts exactly as
they would be from real ones. A few learners are deliberately left with no activity (empty
states). With `--with-proposed-migrations` it also applies db/proposals 0002-0004 to the
disposable database and adds synthetic interventions and notifications (`is_synthetic = true`).

Credentials are generated with `secrets`, hashed with Argon2id and written once to
`.local/demo_credentials.json` (0600, Git-ignored); they are never printed. Synthetic activity
is NOT evidence about real learners or learning outcomes.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import secrets
import stat
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import (
    Attempt,
    ClassEnrollment,
    Classroom,
    CurriculumVersion,
    KcCurriculumMap,
    KnowledgeComponent,
    Learner,
    Question,
    QuestionKc,
    QuestionOption,
    Role,
    StudentKcState,
    TeacherClassAssignment,
    User,
    UserRole,
)
from app.services import attempt_service, interventions, notifications

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CREDENTIAL_FILE = PROJECT_ROOT / ".local" / "demo_credentials.json"
NAMESPACE = uuid.UUID("0d3a7a52-5a1e-4c1e-8d57-5e1c0a9f0d77")
MARK = "SYNTHETIC-DEMO"
LEARNERS_PER_CLASS = 10
ATTEMPTS_PER_KC = 4
MAX_KCS_PER_LEARNER = 8
LEVELS = (6, 7, 8, 9, 10)
SECTION = "DEMO-A"
# (ability, share): strong, average, struggling, and a few with no activity at all.
PROFILES = (("strong", 0.85), ("average", 0.6), ("struggling", 0.3), ("inactive", None))


class DemoRefused(RuntimeError):
    """A safety check failed; nothing was written."""


def _id(name: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, name)


def check_target(url: URL, engine: Engine, *, confirmed: bool) -> None:
    if not confirmed:
        raise DemoRefused("--confirm-disposable is required")
    name = url.database or ""
    if not name.startswith("ct_demo"):
        raise DemoRefused("the database name must start with 'ct_demo'")
    configured = make_url(get_settings().database_url.get_secret_value())
    if (url.host, url.port, url.database) == (
        configured.host,
        configured.port,
        configured.database,
    ):
        raise DemoRefused("the target is the application's configured database")
    with engine.connect() as conn:
        if not conn.execute(
            text("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'concepttrail'")
        ).scalar():
            raise DemoRefused("the 'concepttrail' schema does not exist in the target")
        if conn.execute(text("SELECT pg_is_in_recovery()")).scalar_one():
            raise DemoRefused("the target is a replica")


def _engine(database_url: str) -> tuple[URL, Engine]:
    url = make_url(database_url)
    return url, create_engine(
        url, connect_args={"options": "-c search_path=concepttrail,public"}, pool_pre_ping=True
    )


def _write_credentials(creds: dict[str, Any]) -> None:
    CREDENTIAL_FILE.parent.mkdir(mode=0o700, exist_ok=True)
    existing: dict[str, Any] = {}
    if CREDENTIAL_FILE.exists():
        existing = json.loads(CREDENTIAL_FILE.read_text())
    existing.update(creds)
    CREDENTIAL_FILE.write_text(json.dumps(existing, indent=2))
    os.chmod(CREDENTIAL_FILE, stat.S_IRUSR | stat.S_IWUSR)


def _ensure_user(
    s: Session, name: str, login: str, secret: str, role: str, creds: dict[str, Any]
) -> User:
    existing = s.scalar(select(User).where(User.login_identifier == login))
    if existing is not None:
        return existing  # never overwritten; no new credential is made
    now = datetime.now(UTC)
    user = User(
        user_id=_id(name),
        login_identifier=login,
        password_hash=hash_password(secret),
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    s.add(user)
    s.flush()
    s.add(UserRole(user_id=user.user_id, role_code=role))
    creds[login] = secret
    return user


def class_content(s: Session, level: int) -> list[tuple[str, list[Question]]]:
    """KCs of a class level that have deliverable single-KC questions (servable only)."""
    from app.core.content_release import servable_curriculum_statuses, servable_review_statuses
    from app.db.models import CurriculumItem

    kc_ids = list(
        s.scalars(
            select(KcCurriculumMap.kc_id)
            .join(CurriculumItem, CurriculumItem.item_id == KcCurriculumMap.item_id)
            .join(
                CurriculumVersion,
                CurriculumVersion.curriculum_version_id == CurriculumItem.curriculum_version_id,
            )
            .join(KnowledgeComponent, KnowledgeComponent.kc_id == KcCurriculumMap.kc_id)
            .where(
                CurriculumVersion.class_level == level,
                CurriculumVersion.status.in_(servable_curriculum_statuses()),
                CurriculumItem.status.in_(servable_curriculum_statuses()),
                KcCurriculumMap.review_status.in_(servable_review_statuses()),
                KnowledgeComponent.review_status.in_(servable_review_statuses()),
            )
            .distinct()
            .order_by(KcCurriculumMap.kc_id)
        )
    )
    out = []
    for kc_id in kc_ids:
        questions = []
        for q in s.scalars(
            select(Question)
            .join(QuestionKc, QuestionKc.question_id == Question.question_id)
            .where(
                QuestionKc.kc_id == kc_id,
                Question.active.is_(True),
                Question.item_type.in_(("single_choice", "true_false")),
                Question.review_status.in_(servable_review_statuses()),
            )
            .order_by(Question.question_id)
        ):
            if attempt_service.is_deliverable(
                q,
                list(
                    s.scalars(
                        select(QuestionOption).where(QuestionOption.question_id == q.question_id)
                    )
                ),
            ):
                questions.append(q)
        if len(questions) >= 2:
            out.append((kc_id, questions))
    return out


def _answer(s: Session, question: Question, correct: bool) -> dict[str, str]:
    options = list(
        s.scalars(
            select(QuestionOption)
            .where(QuestionOption.question_id == question.question_id)
            .order_by(QuestionOption.option_key)
        )
    )
    pool = [o for o in options if bool(o.is_correct) == correct]
    return {"option_key": (pool or options)[0].option_key}


def load(
    database_url: str, *, confirmed: bool, seed: int = 7, proposed: bool = False
) -> dict[str, Any]:
    url, engine = _engine(database_url)
    check_target(url, engine, confirmed=confirmed)
    if proposed:
        apply_proposed_migrations(url)
    creds: dict[str, Any] = {}
    summary: dict[str, Any] = {"classes": [], "attempts_submitted": 0, "attempts_replayed": 0}
    with Session(engine) as s:
        before = s.scalar(
            select(func.count(User.user_id)).where(~User.login_identifier.like("demo%"))
        )
        for code in ("student", "teacher"):
            if s.get(Role, code) is None:
                s.add(Role(role_code=code, description=MARK))
        s.flush()
        teacher_a = _ensure_user(
            s,
            "teacher-a",
            "demo.teacher.a@example.invalid",
            secrets.token_urlsafe(18),
            "teacher",
            creds,
        )
        teacher_b = _ensure_user(
            s,
            "teacher-b",
            "demo.teacher.b@example.invalid",
            secrets.token_urlsafe(18),
            "teacher",
            creds,
        )
        s.commit()
        for level in LEVELS:
            content = class_content(s, level)
            if not content:
                summary["classes"].append({"level": level, "state": "no_servable_content"})
                continue
            room = s.get(Classroom, _id(f"room-{level}"))
            if room is None:
                room = Classroom(
                    classroom_id=_id(f"room-{level}"),
                    grade_level=level,
                    section_label=SECTION,
                    academic_session="2026-27",
                    school_label=MARK,
                    active=True,
                )
                s.add(room)
                s.flush()
            for teacher in (teacher_a, teacher_b) if level == 7 else (teacher_a,):
                if s.get(TeacherClassAssignment, (room.classroom_id, teacher.user_id)) is None:
                    s.add(
                        TeacherClassAssignment(
                            classroom_id=room.classroom_id,
                            user_id=teacher.user_id,
                            assigned_at=datetime.now(UTC),
                        )
                    )
            s.commit()
            rng = random.Random(f"{seed}-{level}")
            for n in range(1, LEARNERS_PER_CLASS + 1):
                profile, ability = PROFILES[(n - 1) % len(PROFILES)]
                login = f"demo-l{level}-{n:02d}"
                user = _ensure_user(
                    s, login, login, f"{secrets.randbelow(10**8):08d}", "student", creds
                )
                learner = s.scalar(select(Learner).where(Learner.user_id == user.user_id))
                if learner is None:
                    learner = Learner(
                        learner_id=_id(f"learner-{login}"),
                        user_id=user.user_id,
                        display_name=f"DEMO Learner {level}-{n:02d}",
                        created_at=datetime.now(UTC),
                    )
                    s.add(learner)
                    s.flush()
                if (
                    s.scalar(
                        select(ClassEnrollment.enrollment_id).where(
                            ClassEnrollment.learner_id == learner.learner_id,
                            ClassEnrollment.classroom_id == room.classroom_id,
                        )
                    )
                    is None
                ):
                    s.add(
                        ClassEnrollment(
                            enrollment_id=_id(f"enrol-{login}"),
                            learner_id=learner.learner_id,
                            classroom_id=room.classroom_id,
                            enrolled_at=datetime.now(UTC),
                        )
                    )
                s.commit()
                if ability is None:
                    continue
                picks = rng.sample(content, min(MAX_KCS_PER_LEARNER, len(content)))
                for kc_id, questions in picks:
                    kc_ability = min(0.95, max(0.05, ability + rng.uniform(-0.2, 0.2)))
                    for i in range(ATTEMPTS_PER_KC):
                        question = questions[i % len(questions)]
                        # Learning curve: the chance of a correct answer rises with practice.
                        correct = rng.random() < min(0.97, kc_ability + 0.04 * i)
                        key = f"demo-{seed}-{login}-{kc_id}-{i}"
                        replay = s.scalar(
                            select(Attempt.attempt_id).where(Attempt.idempotency_key == key)
                        )
                        attempt_service.submit_attempt(
                            s,
                            learner.learner_id,
                            question_id=question.question_id,
                            question_version=question.version,
                            submitted_answer=_answer(s, question, correct),
                            hint_tier=0,
                            idempotency_key=key,
                        )
                        summary["attempts_replayed" if replay else "attempts_submitted"] += 1
            summary["classes"].append({"level": level, "classroom_id": str(room.classroom_id)})
        if proposed:
            summary["proposed"] = _proposed_demo_records(s, teacher_a, teacher_b)
        s.commit()
        after = s.scalar(
            select(func.count(User.user_id)).where(~User.login_identifier.like("demo%"))
        )
        summary["non_demo_user_count_unchanged"] = before == after
        summary["learners"] = s.scalar(
            select(func.count(Learner.learner_id)).where(Learner.display_name.like("DEMO %"))
        )
        summary["kc_states"] = s.scalar(
            select(func.count())
            .select_from(StudentKcState)
            .join(Learner, Learner.learner_id == StudentKcState.learner_id)
            .where(Learner.display_name.like("DEMO %"))
        )
    if creds:
        _write_credentials(creds)
        summary["credentials_file"] = str(CREDENTIAL_FILE.relative_to(PROJECT_ROOT))
    engine.dispose()
    return summary


def apply_proposed_migrations(url: URL) -> None:
    """Apply proposals 0002-0004 to THIS disposable database only (never the configured one)."""
    from alembic import command
    from alembic.config import Config

    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option(
        "version_locations",
        os.pathsep.join(
            [str(PROJECT_ROOT / "app/db/migrations/versions"), str(PROJECT_ROOT / "db/proposals")]
        ),
    )
    command.upgrade(cfg, "0004")


def _proposed_demo_records(s: Session, teacher_a: User, teacher_b: User) -> dict[str, int]:
    """Synthetic interventions and notifications (needs the proposed tables)."""
    from app.db.proposed_models import Notification, TeacherIntervention

    room = s.get(Classroom, _id("room-7"))
    if room is None:
        return {"interventions": 0, "notifications": 0}
    existing = s.scalar(
        select(func.count(TeacherIntervention.intervention_id)).where(
            TeacherIntervention.classroom_id == room.classroom_id,
            TeacherIntervention.note.like(f"{MARK}%"),
        )
    )
    if not existing:
        rows = class_weak(s, room.classroom_id)
        for kind, note in (
            ("reteach", f"{MARK}: reteach the weakest topic with a worked example."),
            ("small_group", f"{MARK}: small-group practice for learners below 0.5."),
        ):
            row = interventions.create(
                s,
                room.classroom_id,
                teacher_a.user_id,
                intervention_type=kind,
                kc_id=rows[0] if rows else None,
                note=note,
            )
            notifications.notify_intervention(s, row, teacher_a.user_id, "created")
    ids = list(
        s.scalars(
            select(ClassEnrollment.learner_id).where(
                ClassEnrollment.classroom_id == room.classroom_id,
                ClassEnrollment.ended_at.is_(None),
            )
        )
    )
    notifications.generate_class_alerts(
        s, room.classroom_id, ids, today=datetime.now(UTC), synthetic=True
    )
    notifications.create(
        s,
        teacher_b.user_id,
        "system",
        "Welcome to the synthetic demo",
        f"{MARK}: every learner, attempt and notification in this database is fictional.",
        dedupe_key="demo-welcome",
        synthetic=True,
    )
    s.flush()
    return {
        "interventions": s.scalar(select(func.count(TeacherIntervention.intervention_id))) or 0,
        "notifications": s.scalar(select(func.count(Notification.notification_id))) or 0,
    }


def class_weak(s: Session, classroom_id: uuid.UUID) -> list[str]:
    from app.services import progress_summary

    ids = list(
        s.scalars(
            select(ClassEnrollment.learner_id).where(
                ClassEnrollment.classroom_id == classroom_id, ClassEnrollment.ended_at.is_(None)
            )
        )
    )
    return [r["kc_id"] for r in progress_summary.class_weak_areas(s, ids)]


def verify(database_url: str) -> dict[str, Any]:
    url, engine = _engine(database_url)
    with Session(engine) as s:
        demo_learners = s.scalar(
            select(func.count(Learner.learner_id)).where(Learner.display_name.like("DEMO %"))
        )
        unlabelled = s.scalar(
            select(func.count(Classroom.classroom_id)).where(
                Classroom.section_label == SECTION, Classroom.school_label != MARK
            )
        )
        demo_attempts = s.scalar(
            select(func.count(Attempt.attempt_id))
            .join(Learner, Learner.learner_id == Attempt.learner_id)
            .where(Learner.display_name.like("DEMO %"))
        )
        out = {
            "database": url.database,
            "demo_learners": demo_learners,
            "demo_attempts": demo_attempts,
            "unlabelled_demo_classrooms": unlabelled,
            "ok": bool(demo_learners) and unlabelled == 0,
        }
    engine.dispose()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("load", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--database-url", required=True)
    sub.choices["load"].add_argument("--confirm-disposable", action="store_true")
    sub.choices["load"].add_argument("--seed", type=int, default=7)
    sub.choices["load"].add_argument("--with-proposed-migrations", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "load":
            result = load(
                args.database_url,
                confirmed=args.confirm_disposable,
                seed=args.seed,
                proposed=args.with_proposed_migrations,
            )
        else:
            result = verify(args.database_url)
    except DemoRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
