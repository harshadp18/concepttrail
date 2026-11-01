"""M1: strict CSV parsing and KC/edge row rules (synthetic data only)."""

from __future__ import annotations

import pytest
from kc_graph_fixtures import pkg_fixture  # noqa: F401  (registers the `pkg` fixture)

from data_pipeline.kc_graph import contract as c
from data_pipeline.kc_graph.csv_io import parse_bytes
from data_pipeline.kc_graph.synthetic import EDGE_SAMPLE, KC_SAMPLE

KC_HEAD = ",".join(c.KC_HEADER)


def codes(data: bytes, header=c.KC_HEADER) -> set[str]:
    return {f.code for f in parse_bytes(data, header, "kc_csv")[1]}


def test_exact_sample_parses_without_findings() -> None:
    rows, findings = parse_bytes(KC_SAMPLE.encode(), c.KC_HEADER, "kc_csv")
    assert findings == [] and len(rows) == 4 and rows[0].line == 2
    rows, findings = parse_bytes(EDGE_SAMPLE.encode(), c.EDGE_HEADER, "edge_csv")
    assert findings == [] and len(rows) == 3


@pytest.mark.parametrize(
    "header, detail",
    [
        (list(c.KC_HEADER[1:]) + [c.KC_HEADER[0]], "reordered"),
        (list(c.KC_HEADER[:-1]), "missing"),
        (list(c.KC_HEADER) + ["extra"], "unexpected"),
        (list(c.KC_HEADER[:-1]) + ["kc_id"], "duplicate"),
    ],
)
def test_header_must_be_exact(header: list[str], detail: str) -> None:
    rows, findings = parse_bytes((",".join(header) + "\n").encode(), c.KC_HEADER, "kc_csv")
    assert rows == [] and findings[0].code == "HEADER_MISMATCH"
    assert any(detail in f.message for f in findings)


def test_encoding_bom_quoting_width_and_blank_rows() -> None:
    assert codes(b"\xff\xfe" + KC_SAMPLE.encode("utf-16-le")) == {"INVALID_ENCODING"}
    rows, findings = parse_bytes(b"\xef\xbb\xbf" + KC_SAMPLE.encode(), c.KC_HEADER, "kc_csv")
    assert {f.code for f in findings} == {"BOM_PRESENT"} and len(rows) == 4
    assert "ROW_WIDTH" in codes((KC_HEAD + "\nKC-MAT-00001,a,b\n").encode())
    assert "INVALID_CSV" in codes((KC_HEAD + '\nKC-MAT-00001,"unterminated\n').encode())
    blank = KC_SAMPLE.replace("\nKC-MAT-00002", "\n\nKC-MAT-00002")
    assert codes(blank.encode()) == {"BLANK_ROW"}
    assert codes(b"") == {"HEADER_MISMATCH"}


def test_untrimmed_and_placeholder_cells_are_reported_not_repaired() -> None:
    padded = KC_SAMPLE.replace("Recognise equivalent fractions", " Recognise equivalent fractions")
    rows, findings = parse_bytes(padded.encode(), c.KC_HEADER, "kc_csv")
    assert {f.code for f in findings} == {"UNTRIMMED_CELL"}
    assert rows[0].cells["name"].startswith(" ")  # never trimmed
    assert codes(KC_SAMPLE.replace(",RV-001\nKC-MAT-00002", ",N/A\nKC-MAT-00002").encode()) == {
        "PLACEHOLDER_VALUE"
    }


def test_contract_samples_validate_clean(pkg) -> None:
    result = pkg.run()
    assert result.ok, [f for f in result.findings if f.severity == "error"]
    assert {f.code for f in result.findings} == {"PROPOSAL_WITHOUT_EVIDENCE"}


@pytest.mark.parametrize(
    "changes, code",
    [
        ({"kc_id": "KC-MATH-1"}, "INVALID_KC_ID"),
        ({"kc_id": "KC-SCI-00001"}, "SUBJECT_ID_MISMATCH"),
        ({"subject_id": "maths"}, "INVALID_SUBJECT"),
        ({"stable_key": "Mathematics.Fractions.x"}, "INVALID_KEY"),
        ({"stable_key": "mathematics.fractions.class-7-fractions"}, "KEY_HAS_CLASS_TOKEN"),
        ({"stable_key": "mathematics.fractions.equivalent-fractions-c7"}, "KEY_HAS_CLASS_TOKEN"),
        ({"stable_key": "mathematics.fractionz.equivalent"}, "UNKNOWN_DOMAIN"),
        ({"stable_key": "mathematics.fractions.equivalent.memorise"}, "UNKNOWN_FACET"),
        ({"stable_key": "science.light.equivalent"}, "SUBJECT_ID_MISMATCH"),
        ({"stable_key": "mathematics.fractions.tables-7x"}, "KEY_CLASS_LOOKALIKE"),
        ({"kc_type": "skill"}, "INVALID_KC_TYPE"),
        ({"difficulty_tier": "6"}, "INVALID_DIFFICULTY"),
        ({"misconceptions": "not json"}, "INVALID_MISCONCEPTIONS"),
        ({"misconceptions": '[{"id":"x1","text":"a"}]'}, "INVALID_MISCONCEPTIONS"),
        (
            {"misconceptions": '[{"id":"m1","text":"a"},{"id":"m1","text":"b"}]'},
            "INVALID_MISCONCEPTIONS",
        ),
        (
            {"misconceptions": '[{"id":"m1","text":"a"},{"id":"m2","text":"A"}]'},
            "INVALID_MISCONCEPTIONS",
        ),
        ({"misconceptions": '[{"id":"m1","text":"a","why":"b"}]'}, "INVALID_MISCONCEPTIONS"),
        ({"source_refs": ""}, "MISSING_REQUIRED"),
        ({"source_refs": "page 3"}, "INVALID_SOURCE_REF"),
        ({"source_refs": "src:SRC-C07-MAT-EXMP1-01@3"}, "INVALID_SOURCE_REF"),
        ({"source_refs": "rev:RR-0001"}, "REV_TOKEN_IN_CSV"),
        ({"declared_class_levels": "5"}, "INVALID_CLASS_LEVEL"),
        ({"declared_class_levels": "7;7"}, "INVALID_LIST"),
        ({"declared_class_levels": ""}, "KC_WITHOUT_CLASS_DECLARATION"),
        ({"scope": "foundation"}, "FOUNDATION_HAS_CLASSES"),
        ({"scope": "core"}, "INVALID_SCOPE"),
        ({"content_version": "v1"}, "INVALID_VERSION"),
        ({"origin": "llm"}, "INVALID_ORIGIN"),
        ({"review_status": "retired"}, "INVALID_STATUS"),
        ({"review_record_ids": ""}, "MISSING_REQUIRED"),
        ({"review_record_ids": "R1"}, "INVALID_REVIEW_REF"),
        ({"author_id": ""}, "MISSING_REQUIRED"),
        ({"author_id": "harshad"}, "INVALID_PERSON_CODE"),
        (
            {"aliases": "mathematics.fractions.equivalent-fractions.recognise"},
            "ALIAS_COLLIDES_WITH_KEY",
        ),
        ({"aliases": "fraction addition"}, "INVALID_KEY"),
        ({"name": "Add fractions with unlike denominators"}, "DUPLICATE_NAME"),
        ({"learning_objective": "Identify it. Then explain it."}, "LONG_OBJECTIVE"),
        ({"stable_key": "mathematics.fractions.add-unlike-denominator.compute"}, "SIMILAR_KEY"),
    ],
)
def test_kc_row_rules(pkg, changes: dict[str, str], code: str) -> None:
    pkg.edit_kc("KC-MAT-00001", **changes)
    assert code in pkg.codes()


def test_duplicate_ids_keys_and_aliases(pkg) -> None:
    pkg.edit_kc("KC-MAT-00003", aliases="mathematics.fractions.fraction-addition")
    assert "DUPLICATE_ALIAS" in pkg.codes()
    pkg.add_kc_row(KC_SAMPLE.splitlines()[1])
    assert {"DUPLICATE_KC_ID", "DUPLICATE_STABLE_KEY"} <= pkg.codes("error")


def test_untouched_model_drafts_cannot_carry_review_fields(pkg) -> None:
    pkg.edit_kc("KC-MAT-00003", review_status="approved", review_record_ids="RR-0001")
    assert "AI_FIELD_VIOLATION" in pkg.codes("error")
    pkg.edit_kc("KC-MAT-00003", origin_ref="")
    assert "MISSING_REQUIRED" in pkg.codes("error")


@pytest.mark.parametrize(
    "changes, code",
    [
        ({"dependency_basis": "chapter_order"}, "FORBIDDEN_BASIS"),
        ({"dependency_basis": "textbook_sequence"}, "FORBIDDEN_BASIS"),
        ({"strength": "4"}, "INVALID_STRENGTH"),
        ({"evidence_refs": "src:SRC-C07-MAT-EXMP1-01@5#a1b2c3d4e5f6"}, "MISSING_LOCATOR"),
        ({"evidence_refs": "rev:RR-0004"}, "REV_TOKEN_IN_CSV"),
        ({"evidence_refs": "see chapter 2"}, "INVALID_EVIDENCE_REF"),
        ({"evidence_refs": ""}, "EDGE_WITHOUT_EVIDENCE"),
        ({"reason": "Taught in the previous chapter."}, "REASON_MENTIONS_ORDER"),
        ({"reason": ""}, "MISSING_REQUIRED"),
        ({"prerequisite_kc_id": "KC-MAT-1"}, "INVALID_KC_ID"),
        ({"dependent_kc_id": "KC-MAT-00099"}, "MISSING_ENDPOINT"),
        ({"dependent_kc_id": "KC-MAT-00001"}, "SELF_EDGE"),
    ],
)
def test_edge_row_rules(pkg, changes: dict[str, str], code: str) -> None:
    pkg.edit_edge("KC-MAT-00001->KC-MAT-00002", **changes)
    assert code in pkg.codes()


def test_graph_rules_are_the_services(pkg) -> None:
    pkg.add_edge_row(EDGE_SAMPLE.splitlines()[1])
    assert "DUPLICATE_EDGE" in pkg.codes("error")


def test_wrong_direction_and_cycles(pkg) -> None:
    # Reversed copy of an approved edge: a two-node cycle among approved edges.
    pkg.add_edge_row(
        "KC-MAT-00002,KC-MAT-00001,uses_concept,Reverse.,1,"
        "src:SRC-C07-MAT-EXMP1-01@5:para2#a1b2c3d4e5f6,human_authored,,approved,RR-0004;RR-0005,RV-001"
    )
    assert "CYCLE" in pkg.codes("error")


def test_foundation_cannot_depend_on_a_target_kc_and_class_order_warns(pkg) -> None:
    pkg.add_edge_row(
        "KC-MAT-00002,KC-MAT-00004,uses_concept,Wrong way round.,,,"
        "human_authored,,needs_review,,RV-001"
    )
    assert "FOUNDATION_DEPENDS_ON_TARGET" in pkg.codes("error")
    pkg.edit_kc("KC-MAT-00001", declared_class_levels="9;10")
    assert "EDGE_AGAINST_CLASS_ORDER" in pkg.codes("warning")


def test_redundant_and_cross_subject_warnings(pkg) -> None:
    pkg.add_edge_row(
        "KC-MAT-00004,KC-MAT-00002,uses_concept,Shortcut.,1,"
        "src:SRC-C07-MAT-EXMP1-01@5:para2#a1b2c3d4e5f6,human_authored,,approved,RR-0004;RR-0005,RV-001"
    )
    assert "REDUNDANT_EDGE" in pkg.codes("warning")


def test_parsed_rows_are_never_traversable_without_approval(pkg) -> None:
    result = pkg.run()
    released = {f"{e.prerequisite_kc_id}->{e.dependent_kc_id}" for e in result.graph.released_edges}
    assert "KC-MAT-00002->KC-MAT-00003" not in released
    assert released == {"KC-MAT-00001->KC-MAT-00002", "KC-MAT-00004->KC-MAT-00001"}
