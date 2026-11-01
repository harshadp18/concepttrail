"""Seed SYNTHETIC, local-development-only authentication records (one student, one teacher).

    python -m scripts.seed_dev_auth preflight    # read-only: checks the target, writes nothing
    python -m scripts.seed_dev_auth seed         # writes, after every preflight check passes
    python -m scripts.seed_dev_auth verify       # read-only: re-checks the seeded records

What it writes, in one transaction and only into existing tables: two `role` rows (`student`,
`teacher`) if absent, two `users`, one `learners`, one `user_roles` per user, one `classroom`, one
`class_enrollments` (active: `ended_at` NULL) and one `teacher_class_assignments` (active). No
learning content (KCs, edges, curriculum, mastery) is ever touched. Nothing is migrated or deleted.

Safety: it refuses unless the target is the local development database (APP_ENV development, a
loopback host, schema `concepttrail`, exactly 26 tables, Alembic `0001`). It never overwrites an
existing user: if a synthetic account already exists it is left exactly as it is and no new
credential is made. Credentials are generated with `secrets`, hashed with Argon2id
(`app.core.security`, the API's own helper) and written once to a private file (directory
0700, file 0600) under
`.local/`, which is Git-ignored. Plaintext is never printed, logged or stored in the database.
The connection URL and `.env` are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.db.models import (
    ClassEnrollment,
    Classroom,
    Learner,
    Role,
    TeacherClassAssignment,
    User,
    UserRole,
)
from app.db.session import DB_SCHEMA, create_db_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CREDENTIAL_DIR = PROJECT_ROOT / ".local"
CREDENTIAL_FILE = CREDENTIAL_DIR / "dev_auth_credentials.json"
EXPECTED_TABLES = 26
EXPECTED_ALEMBIC = "0001"
LOOPBACK = ("localhost", "127.0.0.1", "::1")

# Deterministic synthetic identity: the same IDs every run, so the seed is idempotent.
NAMESPACE = uuid.UUID("6f1d3a52-0c1e-4b1e-9d57-5e1c0a9f0d01")
STUDENT_LOGIN = "dev-student-001"
TEACHER_LOGIN = "dev-teacher-001@concepttrail-dev.invalid"
MARK = "SYNTHETIC-DEV-ONLY"
ROLES = {
    "student": "Student (platform-issued username and PIN)",
    "teacher": "Teacher (school email and password)",
}


def _id(name: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, name)


IDS = {
    "student_user": _id("student-user"),
    "teacher_user": _id("teacher-user"),
    "learner": _id("learner"),
    "classroom": _id("classroom"),
    "enrollment": _id("enrollment"),
}
TABLES = (
    "users",
    "learners",
    "role",
    "user_roles",
    "classroom",
    "class_enrollments",
    "teacher_class_assignments",
)


class SeedRefused(RuntimeError):
    """A safety check failed; nothing was written."""


@dataclass
class Preflight:
    checks: dict[str, Any] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    existing: dict[str, bool] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems


def table_counts(connection) -> dict[str, int]:
    return {
        t: connection.execute(text(f"SELECT count(*) FROM {DB_SCHEMA}.{t}")).scalar_one()
        for t in TABLES
    }


def preflight(engine: Engine, settings=None) -> Preflight:
    """Read-only. Never prints or returns the URL; reports only non-secret facts."""
    settings = settings or get_settings()
    result = Preflight()
    url = make_url(settings.database_url.get_secret_value())

    def check(name: str, ok: bool, detail: Any = "") -> None:
        result.checks[name] = detail if detail != "" else ok
        if not ok:
            result.problems.append(f"{name} failed")

    check("app_env_is_development", settings.app_env == "development", settings.app_env)
    check("host_is_loopback", (url.host or "") in LOOPBACK)
    check("schema_is_concepttrail", settings.db_schema == DB_SCHEMA, settings.db_schema)
    if result.problems:  # a non-development target is never even connected to
        return result
    with engine.connect() as conn:
        tables = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = :s AND table_type = 'BASE TABLE'"
            ),
            {"s": DB_SCHEMA},
        ).scalar_one()
        check("expected_26_tables", tables == EXPECTED_TABLES, tables)
        versions = [
            r[0] for r in conn.execute(text("SELECT version_num FROM public.alembic_version"))
        ]
        check("alembic_is_0001", versions == [EXPECTED_ALEMBIC], versions)
        check(
            "not_a_replica", conn.execute(text("SELECT pg_is_in_recovery()")).scalar_one() is False
        )
        if result.ok:
            result.counts = table_counts(conn)
            result.existing = {
                "student_user": _login_exists(conn, STUDENT_LOGIN),
                "teacher_user": _login_exists(conn, TEACHER_LOGIN),
            }
    result.checks["credential_file_exists"] = CREDENTIAL_FILE.exists()
    return result


def _login_exists(conn, login: str) -> bool:
    return (
        conn.execute(
            select(func.count()).select_from(User).where(User.login_identifier == login)
        ).scalar_one()
        > 0
    )


def credential_dir_private() -> bool:
    if not CREDENTIAL_DIR.is_dir():
        return False
    return stat.S_IMODE(CREDENTIAL_DIR.stat().st_mode) == 0o700


def _write_credentials(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(mode=0o700, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    return tmp


def seed(engine: Engine, settings=None, *, credential_file: Path = CREDENTIAL_FILE) -> dict:
    """Seed once. Returns counts only (never credentials). Raises `SeedRefused` on any problem."""
    pre = preflight(engine, settings)
    if not pre.ok:
        raise SeedRefused("; ".join(pre.problems))
    existing = pre.existing
    if all(existing.values()):
        return {"status": "already_seeded", "inserted": dict.fromkeys(TABLES, 0)}
    if any(existing.values()):
        raise SeedRefused(
            "only one of the synthetic accounts exists; refusing to guess. Nothing was changed."
        )
    if credential_file.exists():
        raise SeedRefused(
            "a credential file exists but the accounts do not; refusing to "
            "overwrite it. Remove it deliberately if it is stale."
        )

    pin = f"{secrets.randbelow(10**8):08d}"
    password = secrets.token_urlsafe(18)
    now = datetime.now(UTC)
    tmp = _write_credentials(
        credential_file,
        {
            "warning": "SYNTHETIC LOCAL DEVELOPMENT CREDENTIALS. Never commit or reuse.",
            "created_at": now.isoformat(),
            "student": {"login_identifier": STUDENT_LOGIN, "pin": pin},
            "teacher": {"login_identifier": TEACHER_LOGIN, "password": password},
            "classroom_id": str(IDS["classroom"]),
        },
    )
    try:
        with Session(engine) as session, session.begin():  # one transaction; rolls back on error
            before = table_counts(session.connection())
            for code, description in ROLES.items():
                if session.get(Role, code) is None:
                    session.add(Role(role_code=code, description=description))
            session.add_all(
                [
                    User(
                        user_id=IDS["student_user"],
                        login_identifier=STUDENT_LOGIN,
                        password_hash=hash_password(pin),
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    ),
                    User(
                        user_id=IDS["teacher_user"],
                        login_identifier=TEACHER_LOGIN,
                        password_hash=hash_password(password),
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
            session.flush()
            session.add_all(
                [
                    Learner(
                        learner_id=IDS["learner"],
                        user_id=IDS["student_user"],
                        display_name=f"{MARK} Student",
                        created_at=now,
                    ),
                    Classroom(
                        classroom_id=IDS["classroom"],
                        grade_level=8,
                        section_label="DEV-A",
                        academic_session="2026-27",
                        school_label=MARK,
                        active=True,
                    ),
                    UserRole(user_id=IDS["student_user"], role_code="student", assigned_at=now),
                    UserRole(user_id=IDS["teacher_user"], role_code="teacher", assigned_at=now),
                ]
            )
            session.flush()
            session.add_all(
                [
                    ClassEnrollment(
                        enrollment_id=IDS["enrollment"],
                        learner_id=IDS["learner"],
                        classroom_id=IDS["classroom"],
                        enrolled_at=now,
                        ended_at=None,
                    ),
                    TeacherClassAssignment(
                        classroom_id=IDS["classroom"],
                        user_id=IDS["teacher_user"],
                        assigned_role="class_teacher",
                        assigned_at=now,
                        ended_at=None,
                    ),
                ]
            )
            session.flush()
            after = table_counts(session.connection())
        os.replace(tmp, credential_file)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return {"status": "seeded", "inserted": {t: after[t] - before[t] for t in TABLES}}


def verify(engine: Engine, credential_file: Path = CREDENTIAL_FILE) -> dict[str, Any]:
    """Read-only checks of the seeded records; returns booleans and counts, never credentials."""
    out: dict[str, Any] = {}
    with engine.connect() as conn:
        student = conn.execute(
            select(User).where(User.login_identifier == STUDENT_LOGIN)
        ).one_or_none()
        teacher = conn.execute(
            select(User).where(User.login_identifier == TEACHER_LOGIN)
        ).one_or_none()
        out["both_users_exist"] = student is not None and teacher is not None
        if not out["both_users_exist"]:
            return out
        out["hashes_are_argon2id"] = all(
            (u.password_hash or "").startswith("$argon2id$") for u in (student, teacher)
        )
        roles = lambda uid: sorted(  # noqa: E731
            r[0] for r in conn.execute(select(UserRole.role_code).where(UserRole.user_id == uid))
        )
        out["student_role_correct"] = roles(student.user_id) == ["student"]
        out["teacher_role_correct"] = roles(teacher.user_id) == ["teacher"]
        learner = conn.execute(
            select(Learner).where(Learner.user_id == student.user_id)
        ).one_or_none()
        out["student_has_learner_profile"] = learner is not None
        out["teacher_has_no_learner_profile"] = (
            conn.execute(
                select(func.count()).select_from(Learner).where(Learner.user_id == teacher.user_id)
            ).scalar_one()
            == 0
        )
        out["active_enrollment"] = (
            learner is not None
            and conn.execute(
                select(func.count())
                .select_from(ClassEnrollment)
                .where(
                    ClassEnrollment.learner_id == learner.learner_id,
                    ClassEnrollment.ended_at.is_(None),
                )
            ).scalar_one()
            == 1
        )
        out["active_teacher_assignment"] = (
            conn.execute(
                select(func.count())
                .select_from(TeacherClassAssignment)
                .where(
                    TeacherClassAssignment.user_id == teacher.user_id,
                    TeacherClassAssignment.ended_at.is_(None),
                )
            ).scalar_one()
            == 1
        )
        out["same_classroom"] = (
            learner is not None
            and conn.execute(
                text(
                    f"SELECT count(*) FROM {DB_SCHEMA}.class_enrollments e JOIN "
                    f"{DB_SCHEMA}.teacher_class_assignments a ON a.classroom_id = e.classroom_id "
                    "WHERE e.learner_id = :l AND a.user_id = :t AND e.ended_at IS NULL "
                    "AND a.ended_at IS NULL"
                ),
                {"l": learner.learner_id, "t": teacher.user_id},
            ).scalar_one()
            == 1
        )
        out["no_orphans"] = (
            conn.execute(
                text(
                    f"SELECT (SELECT count(*) FROM {DB_SCHEMA}.user_roles ur "
                    f"LEFT JOIN {DB_SCHEMA}.users u "
                    "ON u.user_id = ur.user_id WHERE u.user_id IS NULL) + "
                    f"(SELECT count(*) FROM {DB_SCHEMA}.class_enrollments e "
                    f"LEFT JOIN {DB_SCHEMA}.learners l "
                    "ON l.learner_id = e.learner_id WHERE l.learner_id IS NULL)"
                )
            ).scalar_one()
            == 0
        )
        out["account_counts"] = {
            "users": conn.execute(select(func.count()).select_from(User)).scalar_one(),
            "learners": conn.execute(select(func.count()).select_from(Learner)).scalar_one(),
        }
        out["duplicate_logins"] = conn.execute(
            text(
                f"SELECT count(*) FROM (SELECT login_identifier FROM {DB_SCHEMA}.users GROUP BY 1 "
                "HAVING count(*) > 1) d"
            )
        ).scalar_one()
        # Plaintext must appear in no column of the seeded users, classroom or learner rows.
        if credential_file.exists():
            creds = json.loads(credential_file.read_text(encoding="utf-8"))
            secrets_ = [creds["student"]["pin"], creds["teacher"]["password"]]
            out["login_utility_validates_student_pin"] = verify_password(
                creds["student"]["pin"], student.password_hash
            )
            out["login_utility_validates_teacher_password"] = verify_password(
                creds["teacher"]["password"], teacher.password_hash
            )
            out["wrong_secret_rejected"] = not verify_password("00000000", student.password_hash)
            dumped = json.dumps(
                [
                    [str(v) for v in row]
                    for row in conn.execute(
                        text(
                            "SELECT u.login_identifier, u.password_hash, l.display_name "
                            f"FROM {DB_SCHEMA}.users u "
                            f"LEFT JOIN {DB_SCHEMA}.learners l ON l.user_id = u.user_id "
                            "WHERE u.login_identifier IN (:a, :b)"
                        ),
                        {"a": STUDENT_LOGIN, "b": TEACHER_LOGIN},
                    )
                ]
            )
            out["no_plaintext_in_database_rows"] = not any(s in dumped for s in secrets_)
            mode = stat.S_IMODE(credential_file.stat().st_mode)
            out["credential_file_mode_0600"] = mode == 0o600
            out["credential_dir_mode_0700"] = credential_dir_private()
        else:
            out["credential_file_present"] = False
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.seed_dev_auth")
    parser.add_argument("command", choices=("preflight", "seed", "verify"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "preflight":
            pre = preflight(create_db_engine(read_only=True))
            print(
                json.dumps(
                    {
                        "ok": pre.ok,
                        "checks": pre.checks,
                        "problems": pre.problems,
                        "row_counts": pre.counts,
                        "synthetic_accounts_exist": pre.existing,
                    },
                    indent=2,
                    default=str,
                )
            )
            return 0 if pre.ok else 1
        if args.command == "seed":
            result = seed(create_db_engine())
            print(json.dumps(result, indent=2))
            if result["status"] == "seeded":
                print(
                    "credentials written (not shown) to "
                    f"{CREDENTIAL_FILE.relative_to(PROJECT_ROOT)}"
                )
            return 0
        report = verify(create_db_engine(read_only=True))
        print(json.dumps(report, indent=2, default=str))
        failed = [k for k, v in report.items() if v is False]
        return 1 if failed else 0
    except SeedRefused as exc:
        print(f"refused: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
