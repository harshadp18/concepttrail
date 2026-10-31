"""Read and profile an inventory CSV without changing it.

Every value stays a `str` (no numeric or date inference), so identifiers keep leading
zeros. Only UTF-8 (with or without BOM) is accepted; any other encoding is reported as a
fatal error rather than guessed. Profiling is diagnostic only and never transforms data.

CLI (read-only, prints JSON):  python -m data_pipeline.stages.profile_csv --input <file.csv>
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from data_pipeline.inventory_schema import CANONICAL_HEADER, NULL_LIKE_TOKENS

UTF8_BOM = b"\xef\xbb\xbf"
OTHER_BOMS = {
    b"\xff\xfe\x00\x00": "utf-32-le",
    b"\x00\x00\xfe\xff": "utf-32-be",
    b"\xff\xfe": "utf-16-le",
    b"\xfe\xff": "utf-16-be",
}
CANDIDATE_DELIMITERS = (",", ";", "\t", "|")
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


class CsvReadError(Exception):
    """The file cannot be read safely; `code` is a stable machine-readable reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Record:
    data_index: int  # 1-based position among data rows
    start_line: int  # physical line where the record starts (header is line 1)
    values: tuple[str, ...]


@dataclass
class ParsedCsv:
    path: Path
    sha256: str
    size_bytes: int
    encoding: str
    has_bom: bool
    delimiter: str
    line_endings: dict[str, int]
    header: tuple[str, ...]
    records: list[Record] = field(default_factory=list)
    blank_lines: list[int] = field(default_factory=list)  # skipped; reported, not data


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode(raw: bytes) -> tuple[str, str, bool]:
    """Return (text, encoding, has_bom). Raises CsvReadError for anything but UTF-8."""
    for bom, name in OTHER_BOMS.items():
        if raw.startswith(bom):
            raise CsvReadError("UNEXPECTED_ENCODING", f"file starts with a {name} byte-order mark")
    has_bom = raw.startswith(UTF8_BOM)
    try:
        text = raw[len(UTF8_BOM) :].decode("utf-8") if has_bom else raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CsvReadError(
            "UNEXPECTED_ENCODING", f"not valid UTF-8 at byte offset {exc.start}"
        ) from None
    return text, ("utf-8-sig" if has_bom else "utf-8"), has_bom


def line_ending_counts(text: str) -> dict[str, int]:
    crlf = text.count("\r\n")
    return {"crlf": crlf, "lf": text.count("\n") - crlf, "cr": text.count("\r") - crlf}


def detect_delimiter(text: str) -> str:
    """Pick the candidate that splits the header line into the most fields (ties: comma)."""
    first_line = text.split("\n", 1)[0]
    counts = {d: first_line.count(d) for d in CANDIDATE_DELIMITERS}
    best = max(CANDIDATE_DELIMITERS, key=lambda d: (counts[d], d == ","))
    return best if counts[best] else ","


def read_csv(path: Path) -> ParsedCsv:
    raw = path.read_bytes()
    text, encoding, has_bom = decode(raw)
    if not text.strip():
        raise CsvReadError("EMPTY_FILE", "file has no header row")
    delimiter = detect_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    records: list[Record] = []
    blank_lines: list[int] = []
    try:
        header = tuple(next(reader))
        previous_end = reader.line_num
        for values in reader:
            start_line = previous_end + 1
            previous_end = reader.line_num
            if not values:  # csv yields [] for a completely blank line
                blank_lines.append(start_line)
                continue
            records.append(Record(len(records) + 1, start_line, tuple(values)))
    except csv.Error as exc:
        raise CsvReadError(
            "MALFORMED_CSV", f"CSV structure error near physical line {reader.line_num}: {exc}"
        ) from None
    return ParsedCsv(
        path=path,
        sha256=sha256_bytes(raw),
        size_bytes=len(raw),
        encoding=encoding,
        has_bom=has_bom,
        delimiter=delimiter,
        line_endings=line_ending_counts(text),
        header=header,
        records=records,
        blank_lines=blank_lines,
    )


def _column_profile(values: list[str]) -> dict[str, Any]:
    present = [v for v in values if v.strip() != ""]
    distinct = collections.Counter(v.strip() for v in present)
    profile: dict[str, Any] = {
        "empty": len(values) - len(present),
        "empty_pct": round(100 * (len(values) - len(present)) / max(len(values), 1), 2),
        "distinct_non_empty": len(distinct),
        "duplicate_values": sum(1 for n in distinct.values() if n > 1),
        "max_length": max((len(v) for v in values), default=0),
        "outer_whitespace": sum(1 for v in values if v != v.strip()),
        "embedded_newlines": sum(1 for v in values if "\n" in v or "\r" in v),
        "control_characters": sum(1 for v in values if CONTROL_CHARS.search(v)),
        "non_ascii": sum(1 for v in values if not v.isascii()),
        "devanagari": sum(1 for v in values if DEVANAGARI.search(v)),
        "not_nfc_normalized": sum(1 for v in values if unicodedata.normalize("NFC", v) != v),
        "null_like_tokens": dict(
            sorted(
                collections.Counter(
                    v.strip() for v in present if v.strip().lower() in NULL_LIKE_TOKENS
                ).items()
            )
        ),
        "inferred_kind": _infer_kind(distinct),
    }
    # Low-cardinality columns are categorical metadata; show their full distribution.
    if len(distinct) <= 25:
        profile["values"] = dict(sorted(distinct.items(), key=lambda kv: (-kv[1], kv[0])))
    return profile


def _infer_kind(distinct: collections.Counter[str]) -> str:
    """Diagnostic label only; values are never converted."""
    if not distinct:
        return "empty"
    keys = list(distinct)
    if all(re.fullmatch(r"\d+", k) for k in keys):
        return "digits"
    if all(re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", k) for k in keys):
        return "iso_date_like"
    if all(re.fullmatch(r"https?://\S+", k) for k in keys):
        return "url"
    if all(re.fullmatch(r"[0-9a-f]{64}", k) for k in keys):
        return "sha256_hex"
    return "text"


def profile_csv(parsed: ParsedCsv) -> dict[str, Any]:
    """Structural and per-column profile of a parsed CSV (no transformation)."""
    width = len(parsed.header)
    column_values: dict[str, list[str]] = {name: [] for name in parsed.header}
    for record in parsed.records:
        for index, name in enumerate(parsed.header):
            if index < len(record.values):
                column_values[name].append(record.values[index])
    exact = collections.Counter(record.values for record in parsed.records)
    header_counts = collections.Counter(parsed.header)
    return {
        "file": parsed.path.name,
        "sha256": parsed.sha256,
        "size_bytes": parsed.size_bytes,
        "encoding": parsed.encoding,
        "utf8_bom": parsed.has_bom,
        "delimiter": parsed.delimiter,
        "quoting": "RFC 4180 double-quote (csv.reader strict=True)",
        "line_endings": parsed.line_endings,
        "header": list(parsed.header),
        "column_count": width,
        "duplicate_headers": sorted(h for h, n in header_counts.items() if n > 1),
        "header_matches_canonical": parsed.header == CANONICAL_HEADER,
        "data_rows": len(parsed.records),
        "blank_lines_skipped": parsed.blank_lines,
        "row_width_histogram": {
            str(k): v
            for k, v in sorted(collections.Counter(len(r.values) for r in parsed.records).items())
        },
        "malformed_rows": [
            {"data_row": r.data_index, "line": r.start_line, "fields": len(r.values)}
            for r in parsed.records
            if len(r.values) != width
        ],
        "exact_duplicate_extra_copies": sum(n - 1 for n in exact.values() if n > 1),
        "columns": {name: _column_profile(values) for name, values in column_values.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        parsed = read_csv(args.input)
    except CsvReadError as exc:
        print(json.dumps({"error": exc.code, "message": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(profile_csv(parsed), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
