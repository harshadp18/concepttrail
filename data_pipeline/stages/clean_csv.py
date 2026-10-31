"""Deterministic, logged cell cleaning for inventory CSVs.

Only two transformations change values:

- `TRIM_OUTER_WHITESPACE`: remove leading/trailing whitespace (internal spacing is kept);
  a whitespace-only cell therefore becomes empty.
- `NORMALIZE_LINE_ENDINGS`: inside a cell, CRLF and lone CR become LF.

Everything else is reported, never rewritten: capitalisation, internal spacing, Unicode
normalisation form (NFC would rewrite composition-excluded Devanagari such as nukta
letters), null-like tokens, control characters and suspected mis-decoded text.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from data_pipeline.inventory_schema import NULL_LIKE_TOKENS

TRIM_OUTER_WHITESPACE = "TRIM_OUTER_WHITESPACE"
NORMALIZE_LINE_ENDINGS = "NORMALIZE_LINE_ENDINGS"

# C0/C1 control characters other than TAB and LF (CR is handled by line-ending rules).
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# U+FFFD, or UTF-8 bytes mis-decoded as Latin-1/Windows-1252 ("Ã©", "à¤", "â€™").
MOJIBAKE = re.compile("�|Ã[\u0080-¿]|à[¤¥]|â€")


@dataclass(frozen=True)
class Transform:
    column: str
    rule: str
    before_sha256: str
    after_sha256: str
    before_length: int
    after_length: int


@dataclass(frozen=True)
class TextFinding:
    column: str
    code: str  # CONTROL_CHARACTER | ENCODING_SUSPECT | UNICODE_NOT_NFC | NULL_LIKE_TOKEN


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def clean_value(column: str, value: str) -> tuple[str, list[Transform]]:
    transforms: list[Transform] = []
    current = value
    for rule, apply in (
        (NORMALIZE_LINE_ENDINGS, lambda v: v.replace("\r\n", "\n").replace("\r", "\n")),
        (TRIM_OUTER_WHITESPACE, str.strip),
    ):
        updated = apply(current)
        if updated != current:
            transforms.append(
                Transform(
                    column, rule, _digest(current), _digest(updated), len(current), len(updated)
                )
            )
            current = updated
    return current, transforms


def inspect_text(column: str, value: str) -> list[TextFinding]:
    findings: list[TextFinding] = []
    if CONTROL_CHARS.search(value):
        findings.append(TextFinding(column, "CONTROL_CHARACTER"))
    if MOJIBAKE.search(value):
        findings.append(TextFinding(column, "ENCODING_SUSPECT"))
    if unicodedata.normalize("NFC", value) != value:
        findings.append(TextFinding(column, "UNICODE_NOT_NFC"))
    if value.strip().lower() in NULL_LIKE_TOKENS:
        findings.append(TextFinding(column, "NULL_LIKE_TOKEN"))
    return findings


def clean_row(
    header: tuple[str, ...], values: tuple[str, ...]
) -> tuple[dict[str, str], list[Transform], list[TextFinding]]:
    """Clean one well-formed row (len(values) == len(header))."""
    cleaned: dict[str, str] = {}
    transforms: list[Transform] = []
    findings: list[TextFinding] = []
    for column, value in zip(header, values, strict=True):
        findings.extend(inspect_text(column, value))
        cleaned[column], cell_transforms = clean_value(column, value)
        transforms.extend(cell_transforms)
    return cleaned, transforms, findings
