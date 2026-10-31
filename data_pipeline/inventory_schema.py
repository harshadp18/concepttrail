"""Canonical inventory schema and the reviewed validation rules for inventory CSVs.

`data_pipeline/curriculum.csv` is the single master inventory. Its exact 29-column
header is `CANONICAL_HEADER`. Vocabularies below are closed: a value outside them is
never mapped to a known value automatically; the row is quarantined for review.

Bump `RULES_VERSION` whenever a rule or vocabulary changes; it is recorded in every
processing manifest so that outputs can be traced to the rules that produced them.
"""

from __future__ import annotations

import re

RULES_VERSION = "teammate-inventory-rules-v1"

CANONICAL_HEADER: tuple[str, ...] = (
    "inventory_id",
    "class_level",
    "board",
    "academic_session",
    "subject_id",
    "course_or_language",
    "item_type",
    "chapter_or_unit_code",
    "chapter_title",
    "topic_title",
    "learning_objective",
    "resource_title",
    "source_id",
    "source_url",
    "publication_or_revision",
    "rights_status",
    "permitted_processing",
    "permitted_indexing",
    "permitted_training",
    "permitted_display",
    "permission_reference",
    "acquired_at",
    "sha256",
    "extraction_status",
    "validation_status",
    "review_status",
    "index_status",
    "last_verified_at",
    "notes",
)

# --- Scope -----------------------------------------------------------------------------

CLASS_LEVELS: tuple[str, ...] = ("6", "7", "8", "9", "10")
SUBJECT_IDS: tuple[str, ...] = ("english", "hindi", "mathematics", "science", "social_science")
BOARDS: tuple[str, ...] = ("CBSE",)

# Three-letter subject code used inside `inventory_id` and `source_id`.
SUBJECT_CODES: dict[str, str] = {
    "ENG": "english",
    "HIN": "hindi",
    "MAT": "mathematics",
    "SCI": "science",
    "SOC": "social_science",
}

# --- Field policies ----------------------------------------------------------------------

# Empty value => row rejected (the record cannot be identified, located or rights-gated).
REQUIRED_FIELDS: tuple[str, ...] = (
    "inventory_id",
    "class_level",
    "board",
    "academic_session",
    "subject_id",
    "course_or_language",
    "item_type",
    "chapter_or_unit_code",
    "chapter_title",
    "resource_title",
    "source_id",
    "rights_status",
    "permitted_processing",
    "permitted_indexing",
    "permitted_training",
    "permitted_display",
    "sha256",
    "extraction_status",
    "validation_status",
    "review_status",
    "index_status",
    "notes",  # carries the teammate's `local_path:` locator; see LOCAL_PATH_PATTERN
)

# Empty value => accepted with a `metadata_missing` warning. Never filled automatically.
OPTIONAL_FIELDS: tuple[str, ...] = tuple(f for f in CANONICAL_HEADER if f not in REQUIRED_FIELDS)

# Human-readable factual fields that must not carry reviewer annotations.
FACTUAL_TEXT_FIELDS: tuple[str, ...] = (
    "course_or_language",
    "chapter_title",
    "topic_title",
    "learning_objective",
    "resource_title",
    "publication_or_revision",
)

# --- Vocabularies ------------------------------------------------------------------------

ITEM_TYPES: tuple[str, ...] = ("chapter_pdf", "other_resource")
RIGHTS_STATUSES: tuple[str, ...] = ("review_required", "approved", "restricted", "denied")
# Only `permitted` opens a gate; `permission_required` and `not_permitted` both block.
PERMISSION_VALUES: tuple[str, ...] = ("permitted", "not_permitted", "permission_required")
PERMISSION_FIELDS: tuple[str, ...] = (
    "permitted_processing",
    "permitted_indexing",
    "permitted_training",
    "permitted_display",
)
EXTRACTION_STATUSES: tuple[str, ...] = ("not_started", "in_progress", "extracted", "failed")
VALIDATION_STATUSES: tuple[str, ...] = ("not_started", "passed", "needs_review", "failed")
REVIEW_STATUSES: tuple[str, ...] = ("needs_review", "in_review", "approved", "rejected")
INDEX_STATUSES: tuple[str, ...] = ("not_indexed", "indexed", "failed")

VOCABULARIES: dict[str, tuple[str, ...]] = {
    "item_type": ITEM_TYPES,
    "rights_status": RIGHTS_STATUSES,
    **dict.fromkeys(PERMISSION_FIELDS, PERMISSION_VALUES),
    "extraction_status": EXTRACTION_STATUSES,
    "validation_status": VALIDATION_STATUSES,
    "review_status": REVIEW_STATUSES,
    "index_status": INDEX_STATUSES,
}

# Purpose-specific permission categories (owner prompt §9) and the canonical column that
# records each one. `None` means the 29-column inventory has no column for that category,
# so the operation stays unauthorised until a reviewed record exists elsewhere.
PERMISSION_CATEGORY_COLUMNS: dict[str, str | None] = {
    "local_extraction": "permitted_processing",
    "local_processing": "permitted_processing",
    "external_model_processing": None,
    "embedding_indexing": "permitted_indexing",
    "student_facing_display": "permitted_display",
    "redistribution": None,
    "model_training": "permitted_training",
}

# --- Formats -----------------------------------------------------------------------------

INVENTORY_ID_PATTERN = re.compile(r"^CT-C(?P<cls>06|07|08|09|10)-(?P<subj>[A-Z]{3})-\d{3}$")
SOURCE_ID_PATTERN = re.compile(
    r"^SRC-C(?P<cls>06|07|08|09|10)-(?P<subj>[A-Z]{3})-[A-Z0-9]+-[A-Z0-9]+$"
)
ACADEMIC_SESSION_PATTERN = re.compile(r"^(?P<start>20\d{2})-(?P<end>\d{2})$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ISO_DATE_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)
URL_PATTERN = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.IGNORECASE)
CHAPTER_CODE_PATTERN = re.compile(r"^(?:Chapter|Unit) [1-9]\d*$")
OTHER_RESOURCE_CODE_PATTERN = re.compile(r"^(?:Prelims|Glossary|Answers|Cover|Appendix(?: \d+)?)$")

# Teammate convention: `notes` = "local_path: <path relative to the PDF root> | ...".
LOCAL_PATH_PATTERN = re.compile(r"(?:^|\|)\s*local_path:\s*(?P<path>[^|]*?)\s*(?:\||$)")

# Reviewer annotations typed into factual fields, e.g. "Title [Note: file named ...]".
REVIEWER_NOTE_PATTERN = re.compile(
    r"\[\s*(?:note|todo|fixme|review|check|discrepancy)\b[^\]]*\]|\b(?:TODO|FIXME|TBD)\b",
    re.IGNORECASE,
)

# Tokens that often mean "missing". Reported only; never converted to empty.
NULL_LIKE_TOKENS: frozenset[str] = frozenset(
    {"na", "n/a", "null", "none", "nil", "-", "--", "?", "tbd", "unknown", "nan"}
)

PDF_SIGNATURE = b"%PDF-"
