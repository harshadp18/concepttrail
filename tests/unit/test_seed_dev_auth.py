"""Dev-auth seed: hashing, credential privacy, refusals, and (live) PostgreSQL behaviour.

Live tests run against the verified LOCAL development PostgreSQL only. Those that write do so
inside a transaction that is rolled back, and they skip if any synthetic account already exists.
SQLite is not used: it would not prove PostgreSQL compatibility.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core import security
from scripts import seed_dev_auth as seed


def test_seed_uses_the_api_hashing_helper() -> None:
    stored = security.hash_password("12345678")
    assert stored.startswith("$argon2id$") and "12345678" not in stored
    assert security.verify_password("12345678", stored)
    assert seed.hash_password is security.hash_password


def test_credential_file_is_private_and_atomic(tmp_path: Path) -> None:
    target = tmp_path / ".local" / "creds.json"
    tmp = seed._write_credentials(target, {"student": {"pin": "00000001"}})
    assert not target.exists() and tmp.exists()  # only promoted after the commit
    assert stat.S_IMODE(tmp.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    os.replace(tmp, target)
    assert json.loads(target.read_text())["student"]["pin"] == "00000001"
    seed._write_credentials(target, {})
    with pytest.raises(FileExistsError):  # a stale temp file is never silently reused
        seed._write_credentials(target, {})


def test_synthetic_identity_is_obviously_synthetic_and_deterministic() -> None:
    assert seed.STUDENT_LOGIN.startswith("dev-") and "@" not in seed.STUDENT_LOGIN
    assert seed.TEACHER_LOGIN.endswith(".invalid")
    assert seed.MARK == "SYNTHETIC-DEV-ONLY"
    assert seed._id("classroom") == seed._id("classroom") != seed._id("learner")


def test_credential_file_location_is_git_ignored() -> None:
    import subprocess

    out = subprocess.run(
        ["git", "check-ignore", "-q", str(seed.CREDENTIAL_FILE)], cwd=seed.PROJECT_ROOT
    )
    assert out.returncode == 0


class FakeSettings:
    class _Url:
        def get_secret_value(self) -> str:
            return "postgresql+psycopg://u:p@db.example.org:5432/concepttrail_db"

    database_url = _Url()
    app_env = "production"
    db_schema = "concepttrail"


class NoEngine:
    def connect(self):  # pragma: no cover - must never be reached
        raise AssertionError("a refused target must not be connected to")


def test_non_development_or_non_loopback_target_is_never_connected_to() -> None:
    pre = seed.preflight(NoEngine(), FakeSettings())  # type: ignore[arg-type]
    assert not pre.ok
    assert {"app_env_is_development failed", "host_is_loopback failed"} <= set(pre.problems)


def test_seed_refuses_when_preflight_fails_and_writes_nothing(tmp_path, monkeypatch) -> None:
    bad = seed.Preflight(problems=["host_is_loopback failed"])
    monkeypatch.setattr(seed, "preflight", lambda *a, **k: bad)
    target = tmp_path / ".local" / "c.json"
    with pytest.raises(seed.SeedRefused, match="host_is_loopback"):
        seed.seed(NoEngine(), credential_file=target)  # type: ignore[arg-type]
    assert not target.parent.exists()


def test_partial_state_and_stale_credential_file_are_refused(tmp_path, monkeypatch) -> None:
    ok = seed.Preflight(existing={"student_user": True, "teacher_user": False})
    monkeypatch.setattr(seed, "preflight", lambda *a, **k: ok)
    with pytest.raises(seed.SeedRefused, match="only one"):
        seed.seed(NoEngine(), credential_file=tmp_path / "c.json")  # type: ignore[arg-type]
    ok.existing = {"student_user": False, "teacher_user": False}
    stale = tmp_path / "c.json"
    stale.write_text("{}")
    with pytest.raises(seed.SeedRefused, match="credential file exists"):
        seed.seed(NoEngine(), credential_file=stale)  # type: ignore[arg-type]
    assert stale.read_text() == "{}"  # untouched


def test_already_seeded_makes_no_inserts(monkeypatch) -> None:
    done = seed.Preflight(existing={"student_user": True, "teacher_user": True})
    monkeypatch.setattr(seed, "preflight", lambda *a, **k: done)
    result = seed.seed(NoEngine(), credential_file=Path("/nonexistent/c.json"))  # type: ignore[arg-type]
    assert result["status"] == "already_seeded" and not any(result["inserted"].values())


def test_cli_preflight_output_has_no_connection_details(capsys) -> None:
    try:
        code = seed.main(["preflight"])
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database not configured: {type(exc).__name__}")
    out = capsys.readouterr().out
    assert code in (0, 1)
    for forbidden in ("postgresql", "://", "password"):
        assert forbidden not in out.lower()


# --- live PostgreSQL (local development only) ------------------------------------------


@pytest.fixture(scope="module")
def live():
    from app.db.session import create_db_engine

    try:
        engine = create_db_engine()
        pre = seed.preflight(engine)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"local development database unavailable: {type(exc).__name__}")
    if not pre.ok:
        pytest.skip(f"not the verified local development database: {pre.problems}")
    return engine, pre


def counts(engine) -> dict[str, int]:
    with engine.connect() as conn:
        return seed.table_counts(conn)


@pytest.mark.live_db
def test_live_seed_failure_midway_rolls_everything_back(live, tmp_path, monkeypatch) -> None:
    engine, pre = live
    if any(pre.existing.values()):
        pytest.skip("synthetic accounts already exist; the rollback test needs a clean state")
    before = counts(engine)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure after earlier rows were flushed")

    monkeypatch.setattr(seed, "TeacherClassAssignment", boom)  # last object created
    target = tmp_path / ".local" / "creds.json"
    with pytest.raises(RuntimeError, match="simulated"):
        seed.seed(engine, credential_file=target)
    assert counts(engine) == before  # users, learner, classroom, roles all rolled back
    assert not target.exists() and not list(target.parent.glob("*.tmp"))


@pytest.mark.live_db
def test_live_second_run_is_a_noop_and_state_verifies(live) -> None:
    engine, pre = live
    if not all(pre.existing.values()):
        pytest.skip("accounts not seeded in this database yet")
    before = counts(engine)
    assert seed.seed(engine)["status"] == "already_seeded"
    assert counts(engine) == before
    report = seed.verify(engine)
    assert [k for k, v in report.items() if v is False] == [], report


@pytest.mark.live_db
def test_live_schema_and_alembic_untouched_and_nothing_is_human_approved(live) -> None:
    """AI-generated demo content may exist (`demo_release`), but no row is human-approved,
    published or released: those states need real reviewers and stay empty."""
    engine, _ = live
    with engine.connect() as conn:
        for table, column, bad in (
            ("knowledge_component", "review_status", "approved"),
            ("kc_edge", "review_status", "approved"),
            ("kc_curriculum_map", "review_status", "approved"),
            ("questions", "review_status", "approved"),
            ("question_kcs", "review_status", "approved"),
            ("curriculum_version", "status", "published"),
            ("curriculum_item", "status", "published"),
            ("content_unit", "review_status", "approved"),
        ):
            count = conn.execute(
                text(f"SELECT count(*) FROM concepttrail.{table} WHERE {column} = :v"), {"v": bad}
            ).scalar_one()
            assert count == 0, (table, column)
        versions = conn.execute(text("SELECT version_num FROM public.alembic_version"))
        assert [r[0] for r in versions] == ["0001"]
