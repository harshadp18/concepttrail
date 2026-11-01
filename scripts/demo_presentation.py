"""Give the DISPOSABLE demo database realistic-looking fictional names for a recorded walkthrough.

`apply` renames, in a `ct_demo*` database only (same safety checks as `scripts.demo_data`):
- learners `DEMO Learner 8-02` -> fictional full names, logins `demo-l8-02` -> e.g. `ananya.rao8`;
- teachers `demo.teacher.a@example.invalid` -> fictional `@school.example` addresses;
- classrooms `DEMO-A` / `SYNTHETIC-DEMO` -> section `A` at a fictional school;
- the `SYNTHETIC-DEMO:` prefix on synthetic support-plan notes.
Every original value is saved to `.local/demo_presentation_state.json`; `revert` restores them
exactly (run it before `scripts.demo_data load|verify` or `scripts.mvp_gate`, which look for the
demo labels). The new sign-in names with their unchanged secrets are written to
`.local/demo_presentation_credentials.json` (Git-ignored, 0600) and never printed.

All names are invented combinations of common given names and surnames; they do not describe
real people. The data stays synthetic.

    python -m scripts.demo_presentation apply  --database-url "$DEMO_DB" --confirm-disposable
    python -m scripts.demo_presentation revert --database-url "$DEMO_DB" --confirm-disposable
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ClassEnrollment, Classroom, Learner, User
from app.db.proposed_models import TeacherIntervention
from scripts.demo_data import CREDENTIAL_FILE, MARK, SECTION, DemoRefused, _engine, check_target

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / ".local" / "demo_presentation_state.json"
PRESENTATION_CREDENTIALS = ROOT / ".local" / "demo_presentation_credentials.json"
SCHOOL = "Greenfield Public School"
TEACHERS = {
    "demo.teacher.a@example.invalid": "meera.iyer@school.example",
    "demo.teacher.b@example.invalid": "rahul.verma@school.example",
}
FIRST = (
    "Aarav Ananya Vihaan Diya Arjun Ishita Kabir Saanvi Reyansh Myra Aditya Kavya Rohan Anika "
    "Krish Tara Dev Meher Yash Riya Arnav Nisha Siddharth Pooja Kunal Aditi Neel Sneha Varun "
    "Zoya Ishaan Prisha Aryan Sara Karthik Leela Omkar Mira Pranav Ira Rudra Avni Samar Trisha "
    "Veer Jiya Manav Naina Harsh Ritika"
).split()
LAST = (
    "Sharma Rao Patel Iyer Nair Gupta Reddy Kulkarni Menon Joshi Das Singh Khan Pillai Mehta "
    "Bose Chauhan Desai Pandey Shetty Kapoor Mishra Varma Naidu Bhat"
).split()


def _write_private(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _demo_rooms(s: Session) -> list[Classroom]:
    return list(
        s.scalars(
            select(Classroom)
            .where(Classroom.section_label == SECTION, Classroom.school_label == MARK)
            .order_by(Classroom.grade_level)
        )
    )


def apply(database_url: str, *, confirmed: bool) -> dict[str, Any]:
    url, engine = _engine(database_url)
    check_target(url, engine, confirmed=confirmed)
    if STATE_FILE.exists():
        raise DemoRefused(f"already applied; run revert first ({STATE_FILE.name} exists)")
    creds = json.loads(CREDENTIAL_FILE.read_text(encoding="utf-8"))
    state: dict[str, Any] = {"users": {}, "learners": {}, "rooms": {}, "notes": {}}
    new_creds: dict[str, str] = {}
    with Session(engine) as s:
        rooms = _demo_rooms(s)
        if not rooms:
            raise DemoRefused("no demo classrooms found (is this a loaded ct_demo database?)")
        used: set[str] = set()
        n = 0
        for room in rooms:
            learner_rows = s.execute(
                select(Learner, User)
                .join(ClassEnrollment, ClassEnrollment.learner_id == Learner.learner_id)
                .join(User, User.user_id == Learner.user_id)
                .where(
                    ClassEnrollment.classroom_id == room.classroom_id,
                    Learner.display_name.like("DEMO %"),
                    User.login_identifier.like("demo-%"),
                )
                .order_by(User.login_identifier)
            ).all()
            for learner, user in learner_rows:
                # deterministic, unique, never repeating a full name
                while True:
                    first, last = FIRST[n % len(FIRST)], LAST[(n * 7 + n // len(FIRST)) % len(LAST)]
                    n += 1
                    if f"{first} {last}" not in used:
                        break
                used.add(f"{first} {last}")
                login = f"{first}.{last}{room.grade_level}".lower()
                state["learners"][str(learner.learner_id)] = learner.display_name
                state["users"][str(user.user_id)] = user.login_identifier
                if user.login_identifier in creds:
                    new_creds[login] = creds[user.login_identifier]
                learner.display_name = f"{first} {last}"
                user.login_identifier = login
            state["rooms"][str(room.classroom_id)] = [room.section_label, room.school_label]
            room.section_label, room.school_label = "A", SCHOOL
        for old, new in TEACHERS.items():
            teacher = s.scalar(select(User).where(User.login_identifier == old))
            if teacher is not None:
                state["users"][str(teacher.user_id)] = old
                teacher.login_identifier = new
                if old in creds:
                    new_creds[new] = creds[old]
        for row in s.scalars(
            select(TeacherIntervention).where(TeacherIntervention.note.like(f"{MARK}: %"))
        ):
            state["notes"][str(row.intervention_id)] = row.note
            note = row.note[len(MARK) + 2 :]
            row.note = note[:1].upper() + note[1:]
        _write_private(STATE_FILE, state)
        try:
            s.commit()
        except Exception:
            STATE_FILE.unlink(missing_ok=True)
            raise
    _write_private(PRESENTATION_CREDENTIALS, new_creds)
    return {
        "learners_renamed": len(state["learners"]),
        "teachers_renamed": sum(1 for v in state["users"].values() if v in TEACHERS),
        "classrooms_relabelled": len(state["rooms"]),
        "notes_cleaned": len(state["notes"]),
        "credentials_file": str(PRESENTATION_CREDENTIALS.relative_to(ROOT)),
    }


def revert(database_url: str, *, confirmed: bool) -> dict[str, Any]:
    url, engine = _engine(database_url)
    check_target(url, engine, confirmed=confirmed)
    if not STATE_FILE.exists():
        raise DemoRefused("nothing to revert (no saved state)")
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    with Session(engine) as s:
        for uid, login in state["users"].items():
            user = s.get(User, uuid.UUID(uid))
            if user is not None:
                user.login_identifier = login
        for lid, name in state["learners"].items():
            learner = s.get(Learner, uuid.UUID(lid))
            if learner is not None:
                learner.display_name = name
        for rid, (section, school) in state["rooms"].items():
            room = s.get(Classroom, uuid.UUID(rid))
            if room is not None:
                room.section_label, room.school_label = section, school
        for iid, note in state.get("notes", {}).items():
            row = s.get(TeacherIntervention, uuid.UUID(iid))
            if row is not None:
                row.note = note
        s.commit()
    STATE_FILE.unlink()
    PRESENTATION_CREDENTIALS.unlink(missing_ok=True)
    return {"restored_users": len(state["users"]), "restored_rooms": len(state["rooms"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("action", choices=("apply", "revert"))
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--confirm-disposable", action="store_true")
    args = parser.parse_args(argv)
    try:
        fn = apply if args.action == "apply" else revert
        print(json.dumps(fn(args.database_url, confirmed=args.confirm_disposable), indent=2))
    except DemoRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
