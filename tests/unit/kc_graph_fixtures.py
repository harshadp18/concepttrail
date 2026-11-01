"""The `pkg` fixture for the Phase 5 `data_pipeline.kc_graph` tests: a SYNTHETIC package.

Imported explicitly by each test module (a `conftest.py` here would shadow the root one).

Everything here is synthetic test data (the contract's sample rows, a synthetic source and a
register marked synthetic). A passing synthetic test is never a human approval.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import pytest

from data_pipeline.kc_graph import contract as c
from data_pipeline.kc_graph import review_log, synthetic, validate


class Pkg:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.inputs = synthetic.build(root)
        self.custody = [root / "custody_a", root / "custody_b"]

    @property
    def review_dir(self) -> Path:
        return self.inputs.review_dir

    def run(self) -> validate.Result:
        return validate.run(self.inputs)

    def codes(self, severity: str | None = None) -> set[str]:
        return {f.code for f in self.run().findings if severity in (None, f.severity)}

    def _rewrite(self, path: Path, header: tuple[str, ...], key: str, changes: dict[str, str]):
        rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
        for row in rows:
            if (
                row.get("kc_id") or f"{row['prerequisite_kc_id']}->{row['dependent_kc_id']}"
            ) == key:
                row.update(changes)
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        path.write_text(out.getvalue(), encoding="utf-8")

    def edit_kc(self, target: str, /, **changes: str) -> None:
        self._rewrite(self.inputs.kc_csv, c.KC_HEADER, target, changes)

    def edit_edge(self, target: str, /, **changes: str) -> None:
        self._rewrite(self.inputs.edge_csv, c.EDGE_HEADER, target, changes)

    def add_kc_row(self, line: str) -> None:
        with self.inputs.kc_csv.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def add_edge_row(self, line: str) -> None:
        with self.inputs.edge_csv.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def review(self, **entry: Any) -> dict[str, Any]:
        return synthetic.write_reviews(self.inputs, [entry])[0]

    def anchor(self) -> None:
        synthetic.anchor(self.inputs, self.custody)

    def log_lines(self) -> list[str]:
        return (self.review_dir / c.REVIEW_LOG.name).read_text(encoding="utf-8").splitlines()

    def write_log(self, lines: list[str]) -> None:
        (self.review_dir / c.REVIEW_LOG.name).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def events(self) -> list[dict[str, Any]]:
        return review_log.read_jsonl(self.review_dir / c.REVIEW_LOG.name, "log")[0]

    def register(self) -> dict[str, Any]:
        return json.loads((self.review_dir / c.REGISTER_FILE.name).read_text(encoding="utf-8"))


def kc_review(kc_id: str, reviewer: str, decision: str = "approved", **extra: Any) -> dict:
    entry = synthetic._kc_review(kc_id, reviewer)
    entry["decision"] = decision
    return {**entry, **extra}


def edge_review(key: str, token: str, reviewer: str, **extra: Any) -> dict:
    return {**synthetic._edge_review(key, token, reviewer), **extra}


@pytest.fixture(name="pkg")
def pkg_fixture(tmp_path: Path) -> Pkg:
    return Pkg(tmp_path)


Pkg.kc_entry = staticmethod(kc_review)
Pkg.edge_entry = staticmethod(edge_review)
