"""Every limit-setting value of the Phase 5 KC/prerequisite contract, in one place.

Source: `docs/PHASE_5_CSV_CONTRACT.md` (revision 3) and `docs/PHASE_5_REVIEW_GUIDELINES.md`.
Only the two CSV headers and their column order are owner-instructed. Every other value here
is a recommendation or provisional proposal (see `docs/PHASE_5_DECISION_MATRIX.md`); an owner
change is a one-line edit in this module. Tests check that the headers here equal the ones in
the contract document, so the two cannot drift.
"""

from __future__ import annotations

import re
from pathlib import Path

LOADER_VERSION = "kc-graph-loader-1.0.0"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA = PROJECT_ROOT / "data_pipeline/data"

# --- File locations (D16) ------------------------------------------------------------------
CURATED_DIR = DATA / "curated/kc_graph"  # the two CSVs, kc_vocabularies.json, pilot sheets
REVIEW_DIR = DATA / "overrides/kc_review"  # logs, register, verification, anchors, approvals
REPORT_DIR = DATA / "logs/kc_graph"  # generated validation reports (dry run writes only here)
FINAL_DIR = DATA / "final/kc_graph"  # release manifest and released graph snapshots
KC_CSV = CURATED_DIR / "kc_components.csv"
EDGE_CSV = CURATED_DIR / "prerequisites.csv"
VOCABULARY_FILE = CURATED_DIR / "kc_vocabularies.json"
REVIEW_LOG = REVIEW_DIR / "review_log.jsonl"
LIFECYCLE_LOG = REVIEW_DIR / "lifecycle_log.jsonl"
REGISTER_FILE = REVIEW_DIR / "people.json"
ANCHOR_DIR = REVIEW_DIR / "anchors"  # a convenience copy only, never custody
CUSTODY_FILE = REVIEW_DIR / "custody.json"  # the owner's two custody locations (R2)
GENERATION_DIR = REVIEW_DIR / "generation"  # AI drafting generation records (no textbook text)

# --- Headers (OWNER-INSTRUCTED) -----------------------------------------------------------
KC_HEADER = (
    "kc_id",
    "stable_key",
    "subject_id",
    "name",
    "learning_objective",
    "kc_type",
    "difficulty_tier",
    "misconceptions",
    "source_refs",
    "declared_class_levels",
    "content_version",
    "origin",
    "origin_ref",
    "review_status",
    "review_record_ids",
    "aliases",
    "scope",
    "author_id",
)
EDGE_HEADER = (
    "prerequisite_kc_id",
    "dependent_kc_id",
    "dependency_basis",
    "reason",
    "strength",
    "evidence_refs",
    "origin",
    "origin_ref",
    "review_status",
    "review_record_ids",
    "author_id",
)

# --- Identifiers and closed values ----------------------------------------------------------
SUBJECT_CODES = {
    "ENG": "english",
    "HIN": "hindi",
    "MAT": "mathematics",
    "SCI": "science",
    "SOC": "social_science",
}
SUBJECTS = tuple(sorted(SUBJECT_CODES.values()))
KC_ID_RE = re.compile(r"^KC-(?P<code>ENG|HIN|MAT|SCI|SOC)-(?P<num>\d{5})$")  # D1
SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
STABLE_KEY_RE = re.compile(  # D2: <subject>.<domain>.<concept>[.<facet>]
    rf"^(?P<subject>[a-z_]+)\.(?P<domain>{SLUG})\.(?P<concept>{SLUG})(?:\.(?P<facet>{SLUG}))?$"
)
# Obvious class tokens are errors; anything else with a digit 6-10 is a lookalike warning.
CLASS_TOKEN_RE = re.compile(
    r"(?:^|-)(?:class|grade|std|standard|cls|kaksha)-?\d+(?:$|-)"
    r"|(?:^|-)c(?:0?[6-9]|10)(?:$|-)|(?:^|-)(?:[6-9]|10)(?:th)?(?:$|-)"
)
CLASS_LOOKALIKE_RE = re.compile(r"(?:^|-)(?:[a-z]*)(?:[6-9]|10)(?:[a-z]*)(?:$|-)")
KC_VERSION_RE = re.compile(r"^kc-v(?P<n>[1-9]\d*)$")  # D8
MISCONCEPTION_ID_RE = re.compile(r"^m[0-9]+$")  # D6
PERSON_CODE_RE = re.compile(r"^RV-\d{3,}$")
EVENT_ID_RE = re.compile(r"^RR-\d{4,}$")
GENERATION_REF_RE = re.compile(r"^GEN-[A-Za-z0-9-]+$")
REVIEW_ID_PREFIX = "RR-"
LIFECYCLE_ID_PREFIX = "LC-"

CLASS_LEVELS = ("6", "7", "8", "9", "10")
REVIEW_STATUSES = ("needs_review", "in_review", "approved", "rejected")
DECIDED_STATUSES = ("approved", "rejected")
ORIGINS = ("human_authored", "ai_drafted", "imported")
SCOPES = ("target", "foundation")
DIFFICULTY_TIERS = ("1", "2", "3", "4", "5")  # D5: optional; no logic uses it
STRENGTHS = ("1", "2", "3")  # D10: optional; no logic uses it until Phase 9
FORBIDDEN_BASES = ("chapter_order",)
LIST_SEPARATOR = ";"

# --- Source references (D7) -----------------------------------------------------------------
SOURCE_TOKEN_RE = re.compile(
    r"^src:(?P<source_id>SRC-C(?:06|07|08|09|10)-[A-Z]{3}-[A-Z0-9]+-[A-Z0-9]+)"
    r"@(?P<page>0|[1-9]\d*)(?::para(?P<para>0|[1-9]\d*))?#(?P<pin>[0-9a-f]{12})$"
)
REV_TOKEN_RE = re.compile(r"^rev:", re.IGNORECASE)
# The resolver reads only existing normalised artifacts; this is the rights use that covers it.
RESOLUTION_USE = "local_text_normalization"

# --- Review quorum and roles (D12, pilot values) ----------------------------------------------
KC_REVIEW_QUORUM = 1
EDGE_REVIEW_QUORUM = 2
REAFFIRMATION_QUORUM = 2
WORDING_ONLY_QUORUM = 2
EVENT_TYPES = ("review", "reaffirmation", "clerical_confirmation", "adjudication")
APPROVING_TYPES = ("review", "reaffirmation", "adjudication")
DECISIONS = ("approved", "rejected", "revision_required")
ROLES = ("author", "reviewer", "senior_reviewer")
REVIEWER_ROLES = ("reviewer", "senior_reviewer")
LIFECYCLE_AUTHORISER_ROLES = ("senior_reviewer",)
CLERICAL_CLASSES = ("clerical", "wording_only")
EVENT_BASIS = "individual_review"
KC_CHECKLIST = (
    "atomic_skill",
    "one_measurable_objective",
    "type_and_difficulty_appropriate",
    "misconceptions_real",
    "sources_support",
    "not_duplicate",
    "subject_correct",
    "distinct_from_similar_keys",
)
EDGE_CHECKLIST = (
    "dependent_needs_prerequisite",
    "direction_correct",
    "evidence_supports",
    "not_sequence_based",
    "direct_not_implied",
    "strength_reasonable",
    "endpoints_approved",
)
# Reviewer-entered event fields: a model may never write these.
REVIEWER_FIELDS = (
    "event_type",
    "record_type",
    "record_key",
    "decision",
    "reviewer_id",
    "decided_on",
    "rationale",
    "expert_rationale",
    "evidence_assessment",
    "checklist",
    "supersedes",
    "clerical_class",
    "old_pedagogical_digest",
)
SEQUENCE_WORDS_RE = re.compile(
    r"\b(?:chapter|before|after|earlier|later|next|previous|sequence|order|unit\s*\d|lesson)\b",
    re.IGNORECASE,
)
LONG_OBJECTIVE_WORDS = 40
SIMILAR_KEY_DISTANCE = 2

# --- Findings ---------------------------------------------------------------------------
E, W = "error", "warning"
# code -> (severity, milestone). Every code here is documented in contract section 8.
CODES: dict[str, tuple[str, str]] = {
    # M1: files, rows, vocabularies, keys
    "INVALID_ENCODING": (E, "M1"),
    "BOM_PRESENT": (W, "M1"),
    "INVALID_CSV": (E, "M1"),
    "FILE_MISSING": (E, "M1"),
    "HEADER_MISMATCH": (E, "M1"),
    "ROW_WIDTH": (E, "M1"),
    "BLANK_ROW": (W, "M1"),
    "MISSING_REQUIRED": (E, "M1"),
    "UNTRIMMED_CELL": (E, "M1"),
    "PLACEHOLDER_VALUE": (E, "M1"),
    "INVALID_LIST": (E, "M1"),
    "INVALID_KC_ID": (E, "M1"),
    "DUPLICATE_KC_ID": (E, "M1"),
    "DUPLICATE_STABLE_KEY": (E, "M1"),
    "DUPLICATE_ALIAS": (E, "M1"),
    "ALIAS_COLLIDES_WITH_KEY": (E, "M1"),
    "INVALID_SUBJECT": (E, "M1"),
    "SUBJECT_ID_MISMATCH": (E, "M1"),
    "INVALID_KC_TYPE": (E, "M1"),
    "INVALID_DIFFICULTY": (E, "M1"),
    "INVALID_STRENGTH": (E, "M1"),
    "INVALID_SCOPE": (E, "M1"),
    "INVALID_CLASS_LEVEL": (E, "M1"),
    "INVALID_STATUS": (E, "M1"),
    "INVALID_ORIGIN": (E, "M1"),
    "INVALID_VERSION": (E, "M1"),
    "INVALID_PERSON_CODE": (E, "M1"),
    "INVALID_REVIEW_REF": (E, "M1"),
    "INVALID_KEY": (E, "M1"),
    "KEY_HAS_CLASS_TOKEN": (E, "M1"),
    "KEY_CLASS_LOOKALIKE": (W, "M1"),
    "UNKNOWN_DOMAIN": (E, "M1"),
    "UNKNOWN_FACET": (E, "M1"),
    "INVALID_MISCONCEPTIONS": (E, "M1"),
    "FOUNDATION_HAS_CLASSES": (E, "M1"),
    "FOUNDATION_DEPENDS_ON_TARGET": (E, "M1"),
    "INVALID_SOURCE_REF": (E, "M1"),
    "INVALID_EVIDENCE_REF": (E, "M1"),
    "MISSING_LOCATOR": (E, "M1"),
    "REV_TOKEN_IN_CSV": (E, "M1"),
    "FORBIDDEN_BASIS": (E, "M1"),
    "EDGE_WITHOUT_EVIDENCE": (E, "M1"),
    "AI_FIELD_VIOLATION": (E, "M1"),
    "VOCABULARY_INVALID": (E, "M1"),
    "VOCABULARY_PROVISIONAL": (W, "M1"),
    "REASON_MENTIONS_ORDER": (W, "M1"),
    "SIMILAR_KEY": (W, "M1"),
    "KC_WITHOUT_CLASS_DECLARATION": (W, "M1"),
    "KC_WITHOUT_EDGES": (W, "M1"),
    "FOUNDATION_WITHOUT_TARGET_EDGE": (W, "M1"),
    "REDUNDANT_EDGE": (W, "M1"),
    "CROSS_SUBJECT_EDGE": (W, "M1"),
    "EDGE_AGAINST_CLASS_ORDER": (W, "M1"),
    "DUPLICATE_NAME": (W, "M1"),
    "LONG_OBJECTIVE": (W, "M1"),
    # graph service (reused, not reimplemented)
    "MISSING_ENDPOINT": (E, "M1"),
    "SELF_EDGE": (E, "M1"),
    "DUPLICATE_EDGE": (E, "M1"),
    "CYCLE": (E, "M1"),
    "EDGE_ENDPOINT_KC_NOT_APPROVED": (E, "M1"),
    "EDGE_TOUCHES_REJECTED_KC": (E, "M1"),
    "CYCLE_IN_PROPOSALS": (W, "M1"),
    "PROPOSAL_WITHOUT_EVIDENCE": (W, "M1"),
    # M2: sources and evidence
    "SOURCE_INDEX_UNAVAILABLE": (E, "M2"),
    "SOURCE_UNKNOWN": (E, "M2"),
    "SOURCE_NOT_ACCEPTED": (E, "M2"),
    "SOURCE_RIGHTS_BLOCKED": (E, "M2"),
    "SOURCE_ARTIFACT_MISSING": (E, "M2"),
    "SOURCE_PIN_MISMATCH": (E, "M2"),
    "SOURCE_FILE_ABSENT": (W, "M2"),
    "PAGE_OUT_OF_RANGE": (E, "M2"),
    "PARAGRAPH_OUT_OF_RANGE": (E, "M2"),
    "SOURCE_TEXT_UNUSABLE": (E, "M2"),
    # M3: register, review log, digests
    "REGISTER_MISSING": (E, "M3"),
    "REGISTER_INVALID": (E, "M3"),
    "REGISTER_NOT_VERIFIED": (E, "M3"),
    "AUTHOR_UNKNOWN": (E, "M3"),
    "SYNTHETIC_DATA": (E, "M3"),
    "LOG_INVALID": (E, "M3"),
    "LOG_CHAIN_BROKEN": (E, "M3"),
    "LOG_ANCHOR_MISMATCH": (E, "M3"),
    "LOG_ANCHOR_MISSING": (E, "M3"),
    "CUSTODY_NOT_CONFIGURED": (E, "M3"),
    "REVIEW_RECORD_MISSING": (E, "M3"),
    "REVIEW_MISMATCH": (E, "M3"),
    "REVIEW_NOT_INDIVIDUAL": (E, "M3"),
    "REVIEWER_UNKNOWN": (E, "M3"),
    "REVIEWER_NOT_QUALIFIED": (E, "M3"),
    "QUORUM_NOT_MET": (E, "M3"),
    "REVIEWER_NOT_INDEPENDENT": (E, "M3"),
    "REVIEW_CONFLICT": (E, "M3"),
    "REVIEW_STALE": (E, "M3"),
    "VERSION_NOT_BUMPED": (E, "M3"),
    "CLERICAL_EVENT_ON_SUBSTANTIVE_CHANGE": (E, "M3"),
    "CHECKLIST_INCOMPLETE": (E, "M3"),
    "EVIDENCE_NOT_ASSESSED": (E, "M3"),
    "EVIDENCE_NOT_SUPPORTING": (E, "M3"),
    "EVIDENCE_STALE": (E, "M3"),
    "RATIONALE_MISSING": (E, "M3"),
    "RATIONALE_DUPLICATED": (E, "M3"),
    "EVENT_CITES_FUTURE": (E, "M3"),
    "AI_SELF_APPROVAL": (E, "M3"),
    "REVIEWER_AUTHORED_ENDPOINT": (W, "M3"),
    "VERSION_BUMPED_WITHOUT_CHANGE": (W, "M3"),
    # M4: lifecycle and release
    "EDGE_TOUCHES_RETIRED_KC": (E, "M4"),
    "LIFECYCLE_STALE": (E, "M4"),
    "LIFECYCLE_MISSING": (E, "M4"),
    "LIFECYCLE_INVALID": (E, "M4"),
    "LIFECYCLE_UNAUTHORISED": (E, "M4"),
    "LIFECYCLE_EDGE_UNRESOLVED": (E, "M4"),
    "SNAPSHOT_LIFECYCLE_MISMATCH": (E, "M4"),
    "RETIRED_KC_IN_PATH": (E, "M4"),
    "SNAPSHOT_INVALID": (E, "M4"),
    "SNAPSHOT_DIGEST_MISMATCH": (E, "M4"),
    "VOCABULARY_NOT_CONFIRMED": (E, "M4"),
    "CLASS_MAPPING_MISMATCH": (E, "M5"),
}


def severity(code: str) -> str:
    return CODES[code][0]
