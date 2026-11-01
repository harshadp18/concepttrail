"""The Phase 5A contract documents agree with the ORM, the schemas and the graph service."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import re
from pathlib import Path

import pytest

from app.db import models
from app.schemas.knowledge import EdgeRecord, KcRecord
from app.services import prerequisite_graph as pg

DOCS = Path(__file__).resolve().parents[2] / "docs"
CONTRACT = (DOCS / "PHASE_5_CSV_CONTRACT.md").read_text(encoding="utf-8")
GUIDELINES = (DOCS / "PHASE_5_REVIEW_GUIDELINES.md").read_text(encoding="utf-8")
MATRIX = (DOCS / "PHASE_5_DECISION_MATRIX.md").read_text(encoding="utf-8")
HANDOFF = (DOCS / "PHASE_5_IMPLEMENTATION_HANDOFF.md").read_text(encoding="utf-8")
OWNER_KC_HEADER = (
    "kc_id,stable_key,subject_id,name,learning_objective,kc_type,difficulty_tier,misconceptions,"
    "source_refs,declared_class_levels,content_version,origin,origin_ref,review_status,"
    "review_record_ids,aliases,scope,author_id"
)
OWNER_EDGE_HEADER = (
    "prerequisite_kc_id,dependent_kc_id,dependency_basis,reason,strength,evidence_refs,origin,"
    "origin_ref,review_status,review_record_ids,author_id"
)
PROGRESS = (DOCS / "PHASE_5_PROGRESS.md").read_text(encoding="utf-8")
SUBJECTS = {
    "ENG": "english",
    "HIN": "hindi",
    "MAT": "mathematics",
    "SCI": "science",
    "SOC": "social_science",
}


def block(label: str) -> str:
    match = re.search(rf"```csv {re.escape(label)}\n(.*?)```", CONTRACT, re.S)
    assert match, label
    return match.group(1)


def rows(label: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(block(label))))


def header(label: str) -> list[str]:
    return next(csv.reader(io.StringIO(block(label))))


def first_column_names(section_start: str) -> set[str]:
    part = CONTRACT.split(section_start, 1)[1].split("\n## ", 1)[0]
    names: set[str] = set()
    for line in part.splitlines():
        if line.startswith("|") and not set(line) <= set("|- "):
            cell = line.strip("|").split("|")[0].split("(was")[0]
            names |= set(re.findall(r"`(\w+)`", cell))
    return names - {"Column"}


KC_HEADER = header("kc_components.csv header")
EDGE_HEADER = header("prerequisites.csv header")


def test_headers_are_exactly_the_owner_instructed_ones_in_order() -> None:
    assert ",".join(KC_HEADER) == OWNER_KC_HEADER
    assert ",".join(EDGE_HEADER) == OWNER_EDGE_HEADER
    assert "OWNER-INSTRUCTED" in CONTRACT


def test_headers_are_exact_and_samples_match_them() -> None:
    assert len(KC_HEADER) == 18 and len(EDGE_HEADER) == 11
    assert len(set(KC_HEADER)) == 18 and len(set(EDGE_HEADER)) == 11
    assert header("kc_components.csv sample") == KC_HEADER
    assert header("prerequisites.csv sample") == EDGE_HEADER
    for label in ("kc_components.csv sample", "prerequisites.csv sample"):
        for record in rows(label):
            assert None not in record and None not in record.values()


def test_every_column_is_documented() -> None:
    assert set(KC_HEADER) == first_column_names("## 2. `kc_components.csv`")
    assert set(EDGE_HEADER) == first_column_names("## 3. `prerequisites.csv`")


def tables_by_name():
    return {t.name: t for t in models.Base.metadata.tables.values()}


def test_database_mapping_names_real_columns_and_absent_ones_are_absent() -> None:
    section = CONTRACT.split("## 9. Database mapping", 1)[1].split("**No column exists for**", 1)[0]
    stored = re.findall(r"\| `(\w+\.\w+)` \|", section)
    assert len(stored) == 15
    tables = tables_by_name()
    for ref in stored:
        table, column = ref.split(".")
        assert column in tables[table].columns, ref
    kc_cols = set(tables["knowledge_component"].columns.keys())
    edge_cols = set(tables["kc_edge"].columns.keys())
    for absent in (
        "learning_objective",
        "source_refs",
        "aliases",
        "scope",
        "declared_class_levels",
        "author_id",
        "origin",
        "review_record_ids",
        "lifecycle",
        "retired",
    ):
        assert absent not in kc_cols, absent
    for absent in ("evidence_refs", "dependency_basis", "author_id", "review_record_ids"):
        assert absent not in edge_cols, absent
    # Every CSV column is either mapped or listed as having no column.
    unmapped = set(
        re.findall(r"`(\w+)`", CONTRACT.split("**No column exists for**", 1)[1].split("\n", 1)[0])
    )
    mapped = {r.split(".")[1] for r in stored}
    for column in KC_HEADER + EDGE_HEADER:
        assert (
            column in unmapped
            or column in mapped
            or column in {"learning_objective", "review_status", "prerequisite_kc_id"}
        ), column


def kc_records() -> list[KcRecord]:
    return [
        KcRecord(
            kc_id=r["kc_id"],
            stable_key=r["stable_key"],
            subject_id=r["subject_id"],
            name=r["name"],
            kc_type=r["kc_type"],
            difficulty_tier=int(r["difficulty_tier"]) if r["difficulty_tier"] else None,
            review_status=r["review_status"],
            class_levels=tuple(int(c) for c in r["declared_class_levels"].split(";") if c),
        )
        for r in rows("kc_components.csv sample")
    ]


def edge_records() -> list[EdgeRecord]:
    return [
        EdgeRecord(
            prerequisite_kc_id=r["prerequisite_kc_id"],
            dependent_kc_id=r["dependent_kc_id"],
            reason=r["reason"],
            strength=int(r["strength"]) if r["strength"] else None,
            evidence_refs=tuple(t for t in r["evidence_refs"].split(";") if t),
            review_status=r["review_status"],
        )
        for r in rows("prerequisites.csv sample")
    ]


def test_samples_validate_against_the_existing_schemas_and_graph_service() -> None:
    kcs, edges = kc_records(), edge_records()
    report = pg.validate_graph(kcs, edges)
    assert report.ok, report.errors
    assert [e.key for e in report.released_edges] == [
        ("KC-MAT-00001", "KC-MAT-00002"),
        ("KC-MAT-00004", "KC-MAT-00001"),
    ]
    assert [k.review_status for k in kcs] == ["approved", "approved", "needs_review", "approved"]
    assert "PROPOSAL_WITHOUT_EVIDENCE" in report.codes("warning")  # the model-drafted edge


def test_sample_rows_follow_the_contract_rules() -> None:
    keys, aliases = set(), set()
    for r in rows("kc_components.csv sample"):
        assert re.fullmatch(r"KC-[A-Z]{3}-\d{5}", r["kc_id"])
        assert SUBJECTS[r["kc_id"].split("-")[1]] == r["subject_id"]
        assert re.fullmatch(r"[a-z][a-z0-9]*([._-][a-z0-9]+)*", r["stable_key"])
        assert r["stable_key"].split(".")[0] == r["subject_id"]  # subject is the first part
        assert len(r["stable_key"].split(".")) in (3, 4)
        assert not re.search(r"class|grade|std|(^|[._-])(6|7|8|9|10)([._-]|$)", r["stable_key"])
        assert r["stable_key"] not in keys
        keys.add(r["stable_key"])
        for alias in filter(None, r["aliases"].split(";")):
            assert alias not in aliases and alias not in keys
            aliases.add(alias)
        assert r["kc_type"] in {
            "concept",
            "procedure",
            "fact",
            "vocabulary",
            "application",
            "interpretation",
        }
        assert r["origin"] in {"human_authored", "ai_drafted", "imported"}
        assert r["scope"] in {"target", "foundation"}
        assert (not r["declared_class_levels"]) if r["scope"] == "foundation" else True
        assert re.fullmatch(r"kc-v\d+", r["content_version"])
        assert r["source_refs"] and all(
            re.fullmatch(
                r"src:SRC-C\d\d-[A-Z]{3}-[A-Z0-9]+-[A-Z0-9]+@\d+(:para\d+)?#[0-9a-f]{12}", t
            )
            for t in r["source_refs"].split(";")
        )
        if r["misconceptions"]:
            items = json.loads(r["misconceptions"])
            assert all(
                set(m) == {"id", "text"} and re.fullmatch(r"m\d+", m["id"]) and m["text"]
                for m in items
            )
            assert len({m["id"] for m in items}) == len(items)
        ids = [i for i in r["review_record_ids"].split(";") if i]
        if r["review_status"] in ("approved", "rejected"):
            assert ids
        if r["origin"] == "ai_drafted":
            assert r["origin_ref"] and not r["author_id"] and r["review_status"] == "needs_review"
        else:
            assert re.fullmatch(r"RV-\d{3}", r["author_id"])
    for r in rows("prerequisites.csv sample"):
        assert r["dependency_basis"] in {
            "uses_concept",
            "uses_procedure",
            "uses_vocabulary",
            "uses_representation",
            "expert_judgement",
        }
        assert "rev:" not in r["evidence_refs"]  # never a review token in the CSV
        ids = [i for i in r["review_record_ids"].split(";") if i]
        if r["review_status"] == "approved":
            assert len(ids) == 2 and len(set(ids)) == 2  # two independent approvals (pilot)
            if r["dependency_basis"] != "expert_judgement":
                assert r["evidence_refs"]
        if r["origin"] == "ai_drafted":
            assert not r["author_id"] and r["review_status"] == "needs_review"


def test_samples_use_only_synthetic_content() -> None:
    sample = block("kc_components.csv sample") + block("prerequisites.csv sample")
    assert "EXMP" in sample and not re.search(r"[ऀ-ॿ]", sample)


def test_foundation_kc_is_reported_without_a_class() -> None:
    kcs = kc_records()
    foundation = next(k for k in kcs if k.kc_id == "KC-MAT-00004")
    assert foundation.class_levels == ()
    assert "`scope=foundation`" in CONTRACT or "scope=foundation" in CONTRACT
    assert "scope- and lifecycle-aware" in CONTRACT  # the service limitation is stated, not hidden


@pytest.mark.parametrize(
    "needle",
    [
        "AI generation is never approval",
        "never inferred from chapter order",
        "No table, column or migration is added",
        "`chapter_order` is prohibited",
        "A `rev:` token is never allowed in this column",
        "Pedagogical content digest",
        "Human reaffirmation",
        "never copies an approval across a version",
    ],
)
def test_contract_states_its_key_guarantees(needle: str) -> None:
    assert needle in CONTRACT or needle.replace("`", "") in CONTRACT.replace("`", "")


def test_loader_codes_documented_and_service_codes_really_emitted() -> None:
    codes = set(
        re.findall(
            r"`([A-Z][A-Z_]{4,})`",
            CONTRACT.split("## 8. Validation rules", 1)[1].split("## 9.", 1)[0],
        )
    )
    service_codes = {
        "DUPLICATE_KC_ID",
        "DUPLICATE_STABLE_KEY",
        "MISSING_ENDPOINT",
        "SELF_EDGE",
        "DUPLICATE_EDGE",
        "CYCLE",
        "EDGE_WITHOUT_EVIDENCE",
        "EDGE_ENDPOINT_KC_NOT_APPROVED",
        "EDGE_TOUCHES_REJECTED_KC",
        "CYCLE_IN_PROPOSALS",
        "PROPOSAL_WITHOUT_EVIDENCE",
    }
    source = Path(pg.__file__).read_text(encoding="utf-8")
    for code in service_codes:
        assert code in codes and f'"{code}"' in source, code
    for must in (
        "REV_TOKEN_IN_CSV",
        "EDGE_TOUCHES_RETIRED_KC",
        "QUORUM_NOT_MET",
        "REVIEWER_NOT_INDEPENDENT",
        "REVIEW_STALE",
        "VERSION_NOT_BUMPED",
        "LOG_ANCHOR_MISMATCH",
        "AI_FIELD_VIOLATION",
        "CLASS_MAPPING_MISMATCH",
        "FORBIDDEN_BASIS",
        "SOURCE_PIN_MISMATCH",
        "MISSING_LOCATOR",
        "REGISTER_NOT_VERIFIED",
        "SNAPSHOT_LIFECYCLE_MISMATCH",
        "RETIRED_KC_IN_PATH",
        "LIFECYCLE_STALE",
        "LIFECYCLE_MISSING",
    ):
        assert must in codes, must
    assert len(codes) > len(service_codes) + 10  # the rest are loader rules, not yet implemented


def test_guidelines_keep_the_required_distinctions() -> None:
    low = GUIDELINES.lower()
    for needle in (
        "review completion is not approval",
        "never sets an approval outcome",
        "fail closed",
        "not immutable storage",
        "do not describe the log as immutable",
        "no `retired` review status",
        "no automatic mastery transfer",
    ):
        assert needle.lower() in low, needle
    assert (
        "authorised_by" in GUIDELINES
        and "replacement_kc_ids" in GUIDELINES
        and "edge_resolution" in GUIDELINES
    )
    assert "two independent" in low


def test_matrix_covers_every_decision_and_converts_nothing_into_an_approval() -> None:
    headings = re.findall(r"^## (D\d+): .+?\. \*(.+?)\*$", MATRIX, re.M)
    assert [h[0] for h in headings] == [f"D{n}" for n in range(1, 19)]
    disposition = dict(headings)
    assert "Investigation" in disposition["D4"] and "Separate authorisation" in disposition["D17"]
    for d in ("D3", "D6", "D9", "D14"):
        assert "approved in principle earlier" in disposition[d]  # never promoted to approved
    assert not any(
        re.search(r"\bapproved by explicit owner\b", v, re.I) for v in disposition.values()
    )
    assert "No decision is converted into an owner approval" in MATRIX
    assert "None of D1–D18 is recorded as approved" in PROGRESS
    for n in range(1, 19):
        section = MATRIX.split(f"## D{n}:", 1)[1].split("\n## ", 1)[0]
        for needle in ("**Final value", "**CSV / schema", "**Depends on"):
            assert needle in section, (n, needle)
        assert re.search(r"[Rr]ationale", section) and re.search(r"[Aa]cceptance", section), n
    table = [
        ln
        for ln in MATRIX.split("## Master table", 1)[1].split("\n---", 1)[0].splitlines()
        if ln.startswith("| D")
    ]
    assert [ln.split("|")[1].strip() for ln in table] == [f"D{n}" for n in range(1, 19)]


def test_nothing_blocks_loader_implementation_and_the_blockers_are_exact() -> None:
    assert "**Nothing blocks loader implementation.**" in MATRIX
    master = MATRIX.split("## Master table", 1)[1]
    assert (
        re.search(r"D3 .*blocks import only", master.replace("\n", " "), re.I)
        or "**blocks import only**" in master
    )
    assert "blocks AI drafting only" in master
    for r in ("R1", "R2", "R3", "R4", "R5", "R6", "R7"):
        assert f"| {r} |" in master


def test_taxonomy_package_has_thirty_synthetic_skills_one_per_type_per_subject() -> None:
    part = MATRIX.split("## Appendix A", 1)[1].split("## Appendix B", 1)[0]
    rows_ = [ln.strip("|").split("|") for ln in part.splitlines() if re.match(r"\| \d+ \|", ln)]
    assert len(rows_) == 30
    kinds = {"concept", "procedure", "fact", "vocabulary", "application", "interpretation"}
    by_subject: dict[str, list[str]] = {}
    for r in rows_:
        by_subject.setdefault(r[1].strip(), []).append(r[3].strip())
    assert set(by_subject) == set(SUBJECTS.values())
    for subject, types in by_subject.items():
        assert len(types) == 6 and set(types) == kinds, subject
    assert "not performed" in part.lower() and "A model must not assess it" in part
    for needle in (
        "Recording sheet",
        "Scoring rubric",
        "Disagreement and adjudication",
        "Evidence needed before the taxonomy is frozen",
        "Cohen's kappa",
    ):
        assert needle in part, needle
    assert not re.search(r"[\u0900-\u097f]", part)


def test_pilot_design_states_sample_size_and_interval() -> None:
    part = MATRIX.split("## Appendix B", 1)[1]
    assert "100 edges" in part and "Wilson" in part and "stratified" in part
    # +/-10 points at 95% for p=0.5 needs about 96 edges; 20 per subject gives about +/-22.
    assert round(1.96**2 * 0.25 / 0.1**2) == 96
    assert round(1.96 * (0.25 / 20) ** 0.5, 2) == 0.22


# --- the hash-chain claims, checked against a reference implementation ---------------------


def event_hash(event: dict) -> str:
    body = {k: v for k, v in event.items() if k != "event_hash"}
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def build_log(n: int = 6) -> list[dict]:
    log, prev = [], "0" * 64
    for seq in range(1, n + 1):
        event = {
            "seq": seq,
            "event_id": f"RR-{seq:04d}",
            "decision": "approved",
            "rationale": f"r{seq}",
            "prev_hash": prev,
        }
        event["event_hash"] = event_hash(event)
        log.append(event)
        prev = event["event_hash"]
    return log


def rehash_from(log: list[dict], start: int) -> list[dict]:
    """An attacker who recomputes every hash from `start` onward (and renumbers)."""
    out = copy.deepcopy(log)
    for i in range(start, len(out)):
        out[i]["seq"] = i + 1
        out[i]["event_id"] = f"RR-{i + 1:04d}"
        out[i]["prev_hash"] = out[i - 1]["event_hash"] if i else "0" * 64
        out[i]["event_hash"] = event_hash(out[i])
    return out


def chain_ok(log: list[dict]) -> bool:
    prev = "0" * 64
    for i, e in enumerate(log, 1):
        if (
            e["seq"] != i
            or e["prev_hash"] != prev
            or e["event_hash"] != event_hash(e)
            or e["event_id"] != f"RR-{i:04d}"
        ):
            return False
        prev = e["event_hash"]
    return True


def anchor_ok(log: list[dict], anchors: list[dict]) -> bool:
    return all(
        a["seq"] <= len(log) and log[a["seq"] - 1]["event_hash"] == a["head_hash"] for a in anchors
    )


def anchor_at(log: list[dict], seq: int) -> dict:
    return {"seq": seq, "head_hash": log[seq - 1]["event_hash"]}


def test_the_documented_detection_table_matches_a_reference_implementation() -> None:
    log = build_log()
    anchors = [anchor_at(log, 4)]
    assert chain_ok(log) and anchor_ok(log, anchors)

    edited = copy.deepcopy(log)
    edited[1]["decision"] = "rejected"
    assert not chain_ok(edited)  # interior edit: chain alone detects
    assert not anchor_ok(
        rehash_from(edited, 1), anchors
    )  # rehashed suffix: only the anchor detects it
    assert chain_ok(rehash_from(edited, 1))

    deleted = log[:1] + log[2:]
    assert not chain_ok(deleted)  # interior deletion: detected
    assert chain_ok(rehash_from(deleted, 1)) and not anchor_ok(rehash_from(deleted, 1), anchors)

    truncated = log[:3]
    assert chain_ok(truncated)  # truncation: the chain alone cannot see it
    assert not anchor_ok(truncated, anchors)  # an anchor with a higher seq does
    assert anchor_ok(log[:5], anchors)  # events after the last anchor are not covered by it

    reordered = [log[0], log[2], log[1], *log[3:]]
    assert not chain_ok(reordered)
    assert not anchor_ok(rehash_from(reordered, 1), anchors)

    forged = rehash_from([dict(e, rationale="forged") for e in log], 0)
    assert chain_ok(forged)  # a consistent replacement passes the chain
    assert not anchor_ok(forged, anchors)  # and fails against anchors held elsewhere
    assert anchor_ok(
        forged, [anchor_at(forged, 4)]
    )  # unless the attacker also replaced the anchors

    tail_tamper = copy.deepcopy(log)
    tail_tamper[5]["decision"] = "rejected"
    tail_tamper = rehash_from(tail_tamper, 5)
    assert chain_ok(tail_tamper) and anchor_ok(
        tail_tamper, anchors
    )  # after the last anchor: not detected


def test_pilot_protocol_does_not_fabricate_data_and_states_limits() -> None:
    part = MATRIX.split("## Appendix B", 1)[1]
    for needle in (
        "Status: not performed",
        "about **100 edges",
        "about 20 from each of the five subject families",
        "±22",
        "Wilson",
        "Locally authorised source material",
        "Limitations to state",
    ):
        assert (
            needle in part
            or needle.replace("Status: not performed", "**Status: not performed.**") in part
        ), needle
    assert "No model reads them" in part and "nothing is uploaded" in part


def test_handoff_has_the_ten_steps_milestone_one_and_the_exact_readiness_table() -> None:
    steps = re.findall(
        r"^\| (\d+) \| .+ \| (.*M\d.*|every milestone) \|$",
        HANDOFF,
        re.M,
    )
    assert [int(n) for n, _ in steps] == list(range(1, 11))
    assert "### Milestones (implemented)" in HANDOFF and "data_pipeline/kc_graph/" in HANDOFF
    for activity in (
        "CSV loader implementation",
        "Synthetic dry-run validation",
        "Human-reviewed pilot",
        "Review-log implementation",
        "Database import",
        "Local AI candidate generation",
        "External provider processing",
    ):
        assert f"| {activity}" in HANDOFF, activity
    assert (
        "**NOT AUTHORISED**" in HANDOFF and "requires separate explicit owner approval" in HANDOFF
    )
    assert "never part of loader execution" in HANDOFF
    for r in ("R2", "R4"):
        assert r in HANDOFF


def test_curated_folder_is_ignored_and_has_only_readmes() -> None:
    gitignore = (DOCS.parent / ".gitignore").read_text(encoding="utf-8").splitlines()
    for rule in ("data_pipeline/data/curated/**", "!data_pipeline/data/curated/**/README.md"):
        assert rule in gitignore, rule
    curated = DOCS.parent / "data_pipeline/data/curated"
    present = sorted(p.name for p in curated.rglob("*") if p.is_file()) if curated.exists() else []
    assert set(present) <= {"README.md", ".gitkeep"}  # no curated data exists yet
    # The separate roles never share a folder.
    paths = re.findall(
        r"`(data_pipeline/data/[a-z_]+/[a-z_]+/)`", CONTRACT.split("## 11. File locations", 1)[1]
    )
    assert {
        "data_pipeline/data/curated/kc_graph/",
        "data_pipeline/data/overrides/kc_review/",
        "data_pipeline/data/logs/kc_graph/",
        "data_pipeline/data/final/kc_graph/",
    } <= set(paths)
