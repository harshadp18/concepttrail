"""ORM metadata must equal the recorded live-schema baseline; no database connection is used."""

from __future__ import annotations

from typing import Any

import pytest
from pgvector.sqlalchemy import VECTOR
from sqlalchemy import CheckConstraint, Table, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db.session import DB_SCHEMA

# The agreed 26-table contract (docs/TECHNICAL_REFERENCE.md, docs/DATABASE_SCHEMA.md), listed
# independently of the baseline file so that a regenerated baseline cannot silently change the
# table set.
EXPECTED_TABLES = {
    "subject",
    "curriculum_version",
    "source_document",
    "curriculum_item",
    "content_unit",
    "knowledge_component",
    "content_unit_kcs",
    "kc_curriculum_map",
    "kc_edge",
    "questions",
    "question_kcs",
    "question_options",
    "note",
    "users",
    "learners",
    "role",
    "user_roles",
    "attempts",
    "bkt_config_version",
    "student_kc_state",
    "embedding_chunk",
    "ingestion_job",
    "ingestion_job_documents",
    "classroom",
    "class_enrollments",
    "teacher_class_assignments",
}

EXPECTED_COMPOSITE_PKS = {
    "content_unit_kcs": ["content_unit_id", "kc_id"],
    "kc_curriculum_map": ["kc_id", "item_id"],
    "kc_edge": ["prerequisite_kc_id", "dependent_kc_id"],
    "question_kcs": ["question_id", "kc_id"],
    "user_roles": ["user_id", "role_code"],
    "student_kc_state": ["learner_id", "kc_id"],
    "ingestion_job_documents": ["job_id", "source_id"],
    "teacher_class_assignments": ["classroom_id", "user_id"],
}

EXPECTED_UNIQUES = {
    ("attempts", "idempotency_key"),
    ("knowledge_component", "stable_key"),
    ("learners", "user_id"),
    ("users", "login_identifier"),
}

PARTS = ("columns", "primary_key", "foreign_keys", "unique_constraints", "indexes")


def test_exactly_the_26_contract_tables_are_mapped(orm_tables: dict[str, Table]) -> None:
    assert len(orm_tables) == 26
    assert set(orm_tables) == EXPECTED_TABLES


def test_baseline_covers_the_same_26_tables(schema_baseline: dict[str, Any]) -> None:
    assert schema_baseline["schema"] == DB_SCHEMA == "concepttrail"
    assert set(schema_baseline["tables"]) == EXPECTED_TABLES


def test_every_table_uses_the_concepttrail_schema(orm_tables: dict[str, Table]) -> None:
    assert {table.schema for table in orm_tables.values()} == {"concepttrail"}
    for table in orm_tables.values():
        for fk in table.foreign_keys:
            assert fk.column.table.schema == "concepttrail", fk.target_fullname


@pytest.mark.parametrize("table", sorted(EXPECTED_TABLES))
@pytest.mark.parametrize("part", PARTS)
def test_orm_matches_recorded_live_baseline(
    table: str, part: str, orm_snapshot: dict[str, Any], schema_baseline: dict[str, Any]
) -> None:
    assert orm_snapshot[table][part] == schema_baseline["tables"][table][part]


def test_constraint_and_index_totals(orm_snapshot: dict[str, Any]) -> None:
    def total(part: str) -> int:
        return sum(len(t[part]) for t in orm_snapshot.values())

    assert sum(len(t["columns"]) for t in orm_snapshot.values()) == 188
    assert total("foreign_keys") == 35
    assert total("unique_constraints") == 4
    assert total("indexes") == 19


def test_only_primary_key_columns_are_not_null(orm_tables: dict[str, Table]) -> None:
    for table in orm_tables.values():
        for column in table.columns:
            assert column.nullable is (not column.primary_key), f"{table.name}.{column.name}"


def test_composite_primary_keys(orm_tables: dict[str, Table]) -> None:
    composite = {
        name: [c.name for c in table.primary_key.columns]
        for name, table in orm_tables.items()
        if len(table.primary_key.columns) > 1
    }
    assert composite == EXPECTED_COMPOSITE_PKS


def test_unique_constraints(orm_tables: dict[str, Table]) -> None:
    found = {
        (table.name, column.name)
        for table in orm_tables.values()
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
        for column in constraint.columns
    }
    assert found == EXPECTED_UNIQUES


def test_subject_id_is_varchar_everywhere(orm_snapshot: dict[str, Any]) -> None:
    subject_columns = [
        (table, column[1])
        for table, snap in orm_snapshot.items()
        for column in snap["columns"]
        if column[0] == "subject_id"
    ]
    assert {table for table, _ in subject_columns} == {
        "subject",
        "source_document",
        "curriculum_item",
        "knowledge_component",
    }
    assert {pg_type for _, pg_type in subject_columns} == {"character varying"}


def test_embedding_chunk_has_nine_columns_and_unbounded_vector(
    orm_tables: dict[str, Table],
) -> None:
    table = orm_tables["embedding_chunk"]
    assert [c.name for c in table.columns] == [
        "chunk_id",
        "content_unit_id",
        "chunk_order",
        "chunk_text",
        "token_count",
        "embedding_model_id",
        "embedding",
        "index_generation",
        "created_at",
    ]
    embedding_type = table.c.embedding.type
    assert isinstance(embedding_type, VECTOR)
    assert embedding_type.dim is None
    assert embedding_type.compile(dialect=postgresql.dialect()) == "VECTOR"


def test_no_bell_ringer_or_doubt_tables(orm_tables: dict[str, Table]) -> None:
    assert not [name for name in orm_tables if "bell" in name or "doubt" in name]


def test_mappings_declare_no_database_side_rules(orm_tables: dict[str, Table]) -> None:
    for table in orm_tables.values():
        assert not [c for c in table.constraints if isinstance(c, CheckConstraint)], table.name
        for column in table.columns:
            where = f"{table.name}.{column.name}"
            assert column.server_default is None, where
            assert column.server_onupdate is None, where
            assert column.default is None, where
            assert column.onupdate is None, where
            assert column.autoincrement in ("auto", False), where
        for fk in table.foreign_keys:
            assert (fk.ondelete, fk.onupdate, fk.deferrable) == (None, None, None), fk.name


def test_uuid_and_string_identifier_types(orm_snapshot: dict[str, Any]) -> None:
    pk_types = {
        table: [c[1] for c in snap["columns"] if c[0] in snap["primary_key"]["columns"]]
        for table, snap in orm_snapshot.items()
    }
    uuid_pk_tables = {t for t, types in pk_types.items() if types == ["uuid"]}
    assert uuid_pk_tables == {
        "question_options",
        "note",
        "users",
        "learners",
        "attempts",
        "embedding_chunk",
        "ingestion_job",
        "classroom",
        "class_enrollments",
    }
    varchar_pk_tables = {t for t, types in pk_types.items() if types == ["character varying"]}
    assert varchar_pk_tables == {
        "subject",
        "curriculum_version",
        "source_document",
        "curriculum_item",
        "content_unit",
        "knowledge_component",
        "questions",
        "role",
        "bkt_config_version",
    }


def test_ddl_compiles_for_postgresql_without_a_connection(orm_tables: dict[str, Table]) -> None:
    dialect = postgresql.dialect()
    for table in orm_tables.values():
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert ddl.startswith(f"\nCREATE TABLE concepttrail.{table.name} (")
        for index in table.indexes:
            assert "ON concepttrail." in str(CreateIndex(index).compile(dialect=dialect))
