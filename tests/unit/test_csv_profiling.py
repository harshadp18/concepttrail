"""Reading and profiling inventory CSVs: encodings, structure, Unicode and type safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from data_pipeline.inventory_schema import CANONICAL_HEADER
from data_pipeline.stages.profile_csv import CsvReadError, profile_csv, read_csv


def write(tmp_path: Path, data: bytes, name: str = "in.csv") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_utf8_without_bom(tmp_path: Path) -> None:
    parsed = read_csv(write(tmp_path, b"a,b\n1,2\n"))
    assert (parsed.encoding, parsed.has_bom) == ("utf-8", False)
    assert parsed.header == ("a", "b")
    assert parsed.records[0].values == ("1", "2")


def test_utf8_bom_is_detected_and_not_part_of_the_header(tmp_path: Path) -> None:
    parsed = read_csv(write(tmp_path, b"\xef\xbb\xbfinventory_id,b\r\nx,y\r\n"))
    assert (parsed.encoding, parsed.has_bom) == ("utf-8-sig", True)
    assert parsed.header[0] == "inventory_id"
    assert parsed.line_endings == {"crlf": 2, "lf": 0, "cr": 0}


@pytest.mark.parametrize(
    "data",
    [
        b"\xff\xfea\x00,\x00b\x00",  # UTF-16 LE with BOM
        "a,b\ncafé,x\n".encode("latin-1"),  # not UTF-8
    ],
)
def test_unexpected_encodings_are_fatal_not_guessed(tmp_path: Path, data: bytes) -> None:
    with pytest.raises(CsvReadError) as excinfo:
        read_csv(write(tmp_path, data))
    assert excinfo.value.code == "UNEXPECTED_ENCODING"


def test_empty_file_is_fatal(tmp_path: Path) -> None:
    with pytest.raises(CsvReadError) as excinfo:
        read_csv(write(tmp_path, b"\xef\xbb\xbf  \n"))
    assert excinfo.value.code == "EMPTY_FILE"


def test_unclosed_quote_is_fatal(tmp_path: Path) -> None:
    with pytest.raises(CsvReadError) as excinfo:
        read_csv(write(tmp_path, b'a,b\n"open,1\n'))
    assert excinfo.value.code == "MALFORMED_CSV"


def test_hindi_mixed_language_and_math_survive_byte_exact(tmp_path: Path) -> None:
    title = "मल्हार: कक्षा 6 — Ganita Prakash √2 × π ≤ ∞, x² + y₁ = ½"
    parsed = read_csv(write(tmp_path, f'h1,h2\n"{title}",क़ ख़ ग़\n'.encode()))
    assert parsed.records[0].values == (title, "क़ ख़ ग़")


def test_quoted_delimiters_and_newlines_and_start_lines(tmp_path: Path) -> None:
    data = b'id,text\n001,"a, b"\n002,"line1\r\nline2"\n003,c\n'
    parsed = read_csv(write(tmp_path, data))
    assert [r.values for r in parsed.records] == [
        ("001", "a, b"),
        ("002", "line1\r\nline2"),
        ("003", "c"),
    ]
    assert [r.start_line for r in parsed.records] == [2, 3, 5]


def test_leading_zero_identifiers_stay_strings(tmp_path: Path) -> None:
    parsed = read_csv(write(tmp_path, b"id,class\n007,06\n"))
    assert parsed.records[0].values == ("007", "06")
    profile = profile_csv(parsed)
    assert profile["columns"]["id"]["inferred_kind"] == "digits"  # diagnostic label only
    assert profile["columns"]["id"]["values"] == {"007": 1}


def test_semicolon_delimiter_is_detected(tmp_path: Path) -> None:
    parsed = read_csv(write(tmp_path, b"a;b;c\n1;2;3\n"))
    assert parsed.delimiter == ";"
    assert parsed.header == ("a", "b", "c")


def test_blank_lines_are_recorded_not_counted_as_rows(tmp_path: Path) -> None:
    parsed = read_csv(write(tmp_path, b"a,b\n1,2\n\n3,4\n"))
    assert [r.values for r in parsed.records] == [("1", "2"), ("3", "4")]
    assert parsed.blank_lines == [3]


def test_profile_structure_and_quality_metrics(tmp_path: Path) -> None:
    rows = [
        "x1, a ,NA",
        "x2,b,",
        "x2,b,",  # exact duplicate
        "x3,c",  # malformed width
    ]
    data = ("id,name,dup\n" + "\n".join(rows) + "\n").encode()
    parsed = read_csv(write(tmp_path, data))
    profile = profile_csv(parsed)
    assert profile["data_rows"] == 4
    assert profile["row_width_histogram"] == {"2": 1, "3": 3}
    assert profile["malformed_rows"] == [{"data_row": 4, "line": 5, "fields": 2}]
    assert profile["exact_duplicate_extra_copies"] == 1
    assert profile["header_matches_canonical"] is False
    assert profile["columns"]["name"]["outer_whitespace"] == 1
    assert profile["columns"]["dup"]["null_like_tokens"] == {"NA": 1}
    assert profile["columns"]["dup"]["empty"] == 2


def test_duplicate_headers_are_reported(tmp_path: Path) -> None:
    profile = profile_csv(read_csv(write(tmp_path, b"a,b,a\n1,2,3\n")))
    assert profile["duplicate_headers"] == ["a"]


def test_canonical_header_is_recognised(inventory) -> None:
    path = inventory.write_csv("inv.csv", [inventory.row()])
    profile = profile_csv(read_csv(path))
    assert profile["header_matches_canonical"] is True
    assert profile["column_count"] == len(CANONICAL_HEADER) == 29
    assert profile["columns"]["chapter_title"]["devanagari"] == 1
