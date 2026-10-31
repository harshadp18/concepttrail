"""Snapshot diffing and rule checks used by the live, migration and pre-stamp comparisons."""

from __future__ import annotations

import copy
from typing import Any

from app.db.schema_snapshot import diff_snapshots, rule_violations, snapshot_totals


def test_identical_snapshots_have_no_differences(orm_snapshot: dict[str, Any]) -> None:
    assert diff_snapshots(orm_snapshot, copy.deepcopy(orm_snapshot)) == []


def test_baseline_totals(schema_baseline: dict[str, Any]) -> None:
    assert snapshot_totals(schema_baseline["tables"]) == {
        "tables": 26,
        "columns": 188,
        "primary_keys": 26,
        "composite_primary_keys": 8,
        "foreign_keys": 35,
        "unique_constraints": 4,
        "indexes": 19,
    }


def test_every_kind_of_drift_is_reported(orm_snapshot: dict[str, Any]) -> None:
    actual = copy.deepcopy(orm_snapshot)
    del actual["role"]
    actual["bell_ringer"] = copy.deepcopy(actual["subject"])
    subject = actual["subject"]
    subject["columns"][3] = ["active", "boolean", False]  # nullability change
    subject["columns"].append(["extra", "text", True])
    embedding = actual["embedding_chunk"]["columns"]
    embedding[6] = ["embedding", "vector(768)", True]  # dimension imposed
    actual["kc_edge"]["primary_key"]["columns"].reverse()
    actual["note"]["foreign_keys"] = [
        fk for fk in actual["note"]["foreign_keys"] if fk["name"] != "fk_note_approved_by"
    ]
    actual["attempts"]["indexes"][0]["unique"] = True
    actual["users"]["unique_constraints"] = []

    diffs = diff_snapshots(orm_snapshot, actual)

    expected_fragments = [
        "missing table: role",
        "unexpected table: bell_ringer",
        "subject.active: expected boolean nullable=True, found boolean nullable=False",
        "subject: unexpected column extra",
        "embedding_chunk.embedding: expected vector nullable=True, found vector(768)",
        "kc_edge: primary key expected",
        "note: missing foreign key fk_note_approved_by",
        "attempts: index idx_attempts_learner expected",
        "users: missing unique constraint users_login_identifier_key",
    ]
    for fragment in expected_fragments:
        assert any(fragment in line for line in diffs), fragment


def test_column_order_change_is_reported(orm_snapshot: dict[str, Any]) -> None:
    actual = copy.deepcopy(orm_snapshot)
    actual["subject"]["columns"].reverse()
    assert "subject: column order differs" in diff_snapshots(orm_snapshot, actual)


def test_rule_violations() -> None:
    clean_fk = {
        "table_name": "note",
        "name": "fk_note_approved_by",
        "type": "f",
        "referred_schema": "concepttrail",
        "on_delete": "a",
        "on_update": "a",
        "deferrable": False,
        "validated": True,
    }
    catalog = {
        "columns": [
            {"table_name": "users", "column_name": "user_id", "has_default": False,
             "identity": "", "generated": ""},
        ],
        "constraints": [clean_fk],
        "indexes": [
            {"table_name": "note", "name": "idx_note_kc", "method": "btree",
             "partial": False, "expression": False},
        ],
    }  # fmt: skip
    assert rule_violations(catalog) == []

    bad = copy.deepcopy(catalog)
    bad["columns"][0]["has_default"] = True
    bad["constraints"].append({**clean_fk, "name": "c1", "type": "c"})
    bad["constraints"].append({**clean_fk, "name": "f2", "on_delete": "c"})
    bad["indexes"][0]["method"] = "hnsw"
    problems = rule_violations(bad)
    assert len(problems) == 4
