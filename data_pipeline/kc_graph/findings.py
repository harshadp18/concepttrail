"""The single finding type every loader stage reports (sortable, deterministic, path-free)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

from data_pipeline.kc_graph.contract import CODES, severity


@dataclass(frozen=True, order=True)
class Finding:
    """One problem. `file` is a label (`kc_csv`, `edge_csv`, `review_log`, ...), never a path."""

    severity: str
    code: str
    file: str = ""
    line: int = 0
    record: str = ""
    field: str = ""
    message: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def finding(
    code: str, message: str, *, file: str = "", line: int = 0, record: str = "", field: str = ""
) -> Finding:
    if code not in CODES:
        raise KeyError(f"undocumented finding code {code}")
    return Finding(severity(code), code, file, line, record, field, message)


def sort_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Errors first, then by code, file, line, record, field and message; duplicates removed."""
    return sorted(
        set(findings),
        key=lambda f: (f.severity != "error", f.code, f.file, f.line, f.record, f.field, f.message),
    )


def errors(findings: Iterable[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "error"]
