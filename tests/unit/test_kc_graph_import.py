"""M6: import planning and execution against a DISPOSABLE SQLite database (never PostgreSQL).

The `concepttrail` schema is a separate attached SQLite file holding only the three tables the
importer touches, with the same names and columns as the ORM. Passing here proves the importer's
logic, not that any real import has happened.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from kc_graph_fixtures import pkg_fixture  # noqa: F401  (registers the `pkg` fixture)
from sqlalchemy import create_engine, event, text

from data_pipeline.kc_graph import contract as c
from data_pipeline.kc_graph import import_plan, release, review_log

DDL = (
    "CREATE TABLE concepttrail.subject (subject_id VARCHAR PRIMARY KEY, display_name VARCHAR, "
    "subject_family VARCHAR, active BOOLEAN)",
    "CREATE TABLE concepttrail.knowledge_component (kc_id VARCHAR PRIMARY KEY, subject_id "
    "VARCHAR REFERENCES subject(subject_id), stable_key VARCHAR UNIQUE, name VARCHAR, "
    "description TEXT, kc_type VARCHAR, difficulty_tier SMALLINT, misconceptions JSON, "
    "review_status VARCHAR, content_version VARCHAR)",
    "CREATE TABLE concepttrail.kc_edge (prerequisite_kc_id VARCHAR REFERENCES "
    "knowledge_component(kc_id), dependent_kc_id VARCHAR REFERENCES knowledge_component(kc_id), "
    "strength SMALLINT, reason TEXT, review_status VARCHAR, "
    "PRIMARY KEY (prerequisite_kc_id, dependent_kc_id))",
)


@pytest.fixture
def engine(tmp_path: Path):
    schema_file = tmp_path / "concepttrail.sqlite"
    eng = create_engine(f"sqlite:///{tmp_path / 'main.sqlite'}")

    @event.listens_for(eng, "connect")
    def _attach(dbapi_connection, _record):
        dbapi_connection.execute(f"ATTACH DATABASE '{schema_file}' AS concepttrail")
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    with eng.begin() as conn:
        for statement in DDL:
            conn.execute(text(statement))
        conn.execute(text("INSERT INTO concepttrail.subject (subject_id) VALUES ('mathematics')"))
    return eng


@pytest.fixture
def snap(pkg):
    path = release.release(pkg.run(), pkg.root / "final", allow_synthetic_output=True)
    events = review_log.read_jsonl(pkg.review_dir / c.LIFECYCLE_LOG.name, "lc")[0]
    return json.loads(path.read_text()), events


def plan_with(engine, snapshot, events) -> dict:
    with engine.connect() as conn:
        return import_plan.plan(snapshot, import_plan.SqlStore(conn), events)


def approve(snapshot, body) -> dict:
    return import_plan.build_approval(
        snapshot["snapshot_sha256"], body["plan_sha256"], "SYNTHETIC test approval", "2026-02-01"
    )


def count(engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM concepttrail.{table}")).scalar_one()


def test_plan_is_read_only_and_never_deletes(engine, snap) -> None:
    snapshot, events = snap
    body = plan_with(engine, snapshot, events)
    assert body["counts"] == {"insert": 5, "update": 0, "noop": 0}  # 3 KCs, 2 edges
    assert body["deletes"] == 0 and body["conflicts"] == []
    assert count(engine, "knowledge_component") == 0  # planning wrote nothing


def test_execute_then_replan_is_idempotent(engine, snap) -> None:
    snapshot, events = snap
    body = plan_with(engine, snapshot, events)
    audit = import_plan.execute(snapshot, body, approve(snapshot, body), engine, events)
    assert audit["verification"]["matches"] and audit["deletes"] == 0
    assert count(engine, "knowledge_component") == 3 and count(engine, "kc_edge") == 2
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT description, misconceptions, review_status FROM "
                "concepttrail.knowledge_component WHERE kc_id='KC-MAT-00001'"
            )
        ).one()
    assert row[0].startswith("Identify") and json.loads(row[1])[0]["id"] == "m1"
    again = plan_with(engine, snapshot, events)
    assert again["counts"] == {"insert": 0, "update": 0, "noop": 5}
    # The first approved plan is now stale: executing it again aborts and changes nothing.
    with pytest.raises(import_plan.ImportAborted, match="changed since"):
        import_plan.execute(snapshot, body, approve(snapshot, body), engine, events)
    assert count(engine, "knowledge_component") == 3


def test_any_failure_rolls_the_whole_transaction_back(engine, snap, monkeypatch) -> None:
    snapshot, events = snap
    body = plan_with(engine, snapshot, events)

    def boom(self, row):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(import_plan.SqlStore, "insert_edge", boom)
    with pytest.raises(RuntimeError, match="simulated"):
        import_plan.execute(snapshot, body, approve(snapshot, body), engine, events)
    assert count(engine, "knowledge_component") == 0 and count(engine, "kc_edge") == 0


def test_approval_must_bind_the_exact_snapshot_and_plan(engine, snap) -> None:
    snapshot, events = snap
    body = plan_with(engine, snapshot, events)
    good = approve(snapshot, body)
    for bad, message in (
        ({**good, "plan_sha256": "0" * 64}, "different plan"),
        ({**good, "snapshot_sha256": "0" * 64}, "different snapshot"),
        ({**good, "approved_by": "model"}, "no owner import approval"),
        ({}, "no owner import approval"),
    ):
        with pytest.raises(import_plan.ImportAborted, match=message):
            import_plan.execute(snapshot, body, bad, engine, events)
    assert count(engine, "knowledge_component") == 0


def test_conflicts_block_execution(engine, snap) -> None:
    snapshot, events = snap
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO concepttrail.knowledge_component (kc_id, subject_id, stable_key, name,"
                " description, kc_type, review_status, content_version) VALUES ('KC-MAT-00001', "
                "'mathematics', 'mathematics.fractions.equivalent-fractions.recognise', 'old', "
                "'A different objective', 'concept', 'approved', 'kc-v1'), ('KC-MAT-00099', "
                "'mathematics', 'mathematics.number-sense.equal-sharing.recognise', 'x', 'x', "
                "'concept', 'approved', 'kc-v1')"
            )
        )
    body = plan_with(engine, snapshot, events)
    reasons = {x["kc_id"]: x["reason"] for x in body["conflicts"]}
    assert "same content_version" in reasons["KC-MAT-00001"]  # no silent overwrite
    assert "stable_key belongs to KC-MAT-00099" in reasons["KC-MAT-00004"]
    with pytest.raises(import_plan.ImportAborted, match="conflicts"):
        import_plan.execute(snapshot, body, approve(snapshot, body), engine, events)
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT name FROM concepttrail.knowledge_component WHERE kc_id='KC-MAT-00001'")
            ).scalar_one()
            == "old"
        )


def test_missing_subject_and_unverified_snapshot_are_refused(engine, snap) -> None:
    snapshot, events = snap
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM concepttrail.subject"))
    assert plan_with(engine, snapshot, events)["conflicts"][0]["reason"].startswith("subject_id")
    tampered = {**snapshot, "seq": 99}
    with pytest.raises(import_plan.ImportAborted, match="does not verify"):
        plan_with(engine, tampered, events)


def test_reconcile_reports_differences_read_only(engine, snap) -> None:
    snapshot, events = snap
    body = plan_with(engine, snapshot, events)
    import_plan.execute(snapshot, body, approve(snapshot, body), engine, events)
    with engine.connect() as conn:
        assert import_plan.reconcile(snapshot, import_plan.SqlStore(conn))["matches"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE concepttrail.kc_edge SET strength = 1"))
    with engine.connect() as conn:
        result = import_plan.reconcile(snapshot, import_plan.SqlStore(conn))
    assert not result["matches"] and len(result["edges_differing"]) == 2
