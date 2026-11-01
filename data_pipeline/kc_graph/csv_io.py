"""Strict CSV reading for the two curated files (contract section 1).

UTF-8 (a BOM is stripped and reported as `BOM_PRESENT`; other encodings are refused), RFC 4180
quoting with `strict=True`, the exact header (names and order, no duplicates), and the exact
row width. Values are never trimmed, repaired or converted: an untrimmed cell or a placeholder
such as `NA` is reported, not fixed. Every problem is reported; a header mismatch stops row
parsing for that file because columns can no longer be identified.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from data_pipeline.inventory_schema import NULL_LIKE_TOKENS
from data_pipeline.kc_graph.findings import Finding, finding

BOM = b"\xef\xbb\xbf"


@dataclass(frozen=True)
class CsvRow:
    line: int  # the physical line on which the row ends (1 is the header)
    cells: dict[str, str]


def parse_bytes(
    data: bytes, header: Sequence[str], label: str
) -> tuple[list[CsvRow], list[Finding]]:
    findings: list[Finding] = []
    if data.startswith(BOM):
        findings.append(finding("BOM_PRESENT", "UTF-8 BOM present; stripped", file=label))
        data = data[len(BOM) :]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        findings.append(finding("INVALID_ENCODING", f"not UTF-8 at byte {exc.start}", file=label))
        return [], findings
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    rows: list[CsvRow] = []
    try:
        actual = next(reader, None)
        if actual is None:
            findings.append(finding("HEADER_MISMATCH", "the file is empty", file=label, line=1))
            return [], findings
        if dupes := sorted({c for c in actual if actual.count(c) > 1}):
            findings.append(
                finding("HEADER_MISMATCH", f"duplicate columns {dupes}", file=label, line=1)
            )
        if list(actual) != list(header):
            missing = [c for c in header if c not in actual]
            extra = [c for c in actual if c not in header]
            detail = []
            if missing:
                detail.append(f"missing {missing}")
            if extra:
                detail.append(f"unexpected {extra}")
            if not missing and not extra:
                detail.append("columns are reordered")
            findings.append(finding("HEADER_MISMATCH", "; ".join(detail), file=label, line=1))
        if any(f.code == "HEADER_MISMATCH" for f in findings):
            return [], findings
        for raw in reader:
            line = reader.line_num
            if raw == []:
                findings.append(finding("BLANK_ROW", "blank line skipped", file=label, line=line))
                continue
            if len(raw) != len(header):
                findings.append(
                    finding(
                        "ROW_WIDTH",
                        f"{len(raw)} cells, expected {len(header)}",
                        file=label,
                        line=line,
                    )
                )
                continue
            cells = dict(zip(header, raw, strict=True))
            for column, value in cells.items():
                if value != value.strip():
                    findings.append(
                        finding(
                            "UNTRIMMED_CELL",
                            "leading or trailing whitespace",
                            file=label,
                            line=line,
                            field=column,
                        )
                    )
                elif value.casefold() in NULL_LIKE_TOKENS:
                    findings.append(
                        finding(
                            "PLACEHOLDER_VALUE",
                            f"placeholder {value!r}; leave the cell empty",
                            file=label,
                            line=line,
                            field=column,
                        )
                    )
            rows.append(CsvRow(line, cells))
    except csv.Error as exc:
        findings.append(finding("INVALID_CSV", str(exc), file=label, line=reader.line_num))
    return rows, findings


def read_csv(
    path: Path, header: Sequence[str], label: str
) -> tuple[list[CsvRow], list[Finding], bytes]:
    if not path.exists():
        return [], [finding("FILE_MISSING", "file not found", file=label)], b""
    data = path.read_bytes()
    rows, findings = parse_bytes(data, header, label)
    return rows, findings, data
