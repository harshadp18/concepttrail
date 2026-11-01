"""CLI behaviour and doc/code drift checks for the Phase 5 loader."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from kc_graph_fixtures import pkg_fixture  # noqa: F401  (registers the `pkg` fixture)

from data_pipeline.kc_graph import cli, synthetic
from data_pipeline.kc_graph import contract as c
from data_pipeline.kc_graph.vocabulary import PROVISIONAL_VOCABULARY

ROOT = Path(__file__).parents[2]
CONTRACT = (ROOT / "docs/PHASE_5_CSV_CONTRACT.md").read_text(encoding="utf-8")


def block(name: str) -> str:
    return re.search(rf"```csv {re.escape(name)}\n(.*?)```", CONTRACT, re.S).group(1)


def test_headers_and_samples_are_the_contracts() -> None:
    assert block("kc_components.csv header").strip() == ",".join(c.KC_HEADER)
    assert block("prerequisites.csv header").strip() == ",".join(c.EDGE_HEADER)
    assert block("kc_components.csv sample") == synthetic.KC_SAMPLE
    assert block("prerequisites.csv sample") == synthetic.EDGE_SAMPLE


def test_every_code_is_documented_and_every_documented_code_exists() -> None:
    section = CONTRACT.split("## 8. Validation rules", 1)[1].split("## 9.", 1)[0]
    documented = set(re.findall(r"`([A-Z][A-Z_]+[A-Z])`", section))
    assert set(c.CODES) <= documented, sorted(set(c.CODES) - documented)
    assert documented <= set(c.CODES), sorted(documented - set(c.CODES))


def test_provisional_vocabulary_is_the_contract_proposal() -> None:
    table = CONTRACT.split("**Domains per subject", 1)[1].split("**Facets", 1)[0]
    for subject, domains in PROVISIONAL_VOCABULARY["domains"].items():
        row = next(r for r in table.splitlines() if r.startswith(f"| `{subject}` |"))
        listed = re.findall(r"`([a-z-]+)`", row.split("|")[2])
        assert listed == domains, subject
    facets = CONTRACT.split("**Facets", 1)[1].split("\n", 1)[0]
    assert re.findall(r"`([a-z]+)`", facets) == PROVISIONAL_VOCABULARY["facets"]
    assert PROVISIONAL_VOCABULARY["status"] == "provisional"


def test_loader_imports_no_web_database_or_provider_module() -> None:
    code = (
        "import sys\n"
        "import data_pipeline.kc_graph.validate, data_pipeline.kc_graph.release, "
        "data_pipeline.kc_graph.report, data_pipeline.kc_graph.pilots\n"
        "bad = [m for m in sys.modules if m.split('.')[0] in ('fastapi', 'groq', 'httpx', "
        "'psycopg', 'uvicorn') or m.startswith('app.db') or m.startswith('app.api')]\n"
        "print(bad)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=True
    )
    assert out.stdout.strip() == "[]"


def args(tmp: Path, *extra: str) -> list[str]:
    return [*extra, "--report-dir", str(tmp / "reports"), "--final-dir", str(tmp / "final")]


def test_validate_on_missing_files_fails_and_writes_reports_only_to_the_report_dir(
    tmp_path: Path, capsys
) -> None:
    code = cli.main(
        args(
            tmp_path,
            "validate",
            "--kc",
            str(tmp_path / "none.csv"),
            "--edges",
            str(tmp_path / "none2.csv"),
            "--review-dir",
            str(tmp_path / "r"),
            "--vocabulary",
            str(tmp_path / "v.json"),
            "--no-sources",
        )
    )
    assert code == 1
    report = json.loads((tmp_path / "reports/validation_report.json").read_text())
    assert report["summary"]["by_code"]["FILE_MISSING"] == 2
    assert str(tmp_path) not in json.dumps(report)  # no absolute paths
    assert sorted(p.name for p in (tmp_path / "reports").iterdir()) == [
        "coverage_report.json",
        "run_manifest.json",
        "validation_report.json",
    ]
    assert not (tmp_path / "final").exists()


def test_validate_reports_are_byte_identical_across_runs(pkg, tmp_path: Path) -> None:
    common = [
        "--kc",
        str(pkg.inputs.kc_csv),
        "--edges",
        str(pkg.inputs.edge_csv),
        "--vocabulary",
        str(pkg.inputs.vocabulary),
        "--review-dir",
        str(pkg.review_dir),
        "--no-sources",
        "--allow-synthetic",
    ]
    texts = []
    for _ in range(2):
        cli.main(args(tmp_path, "validate", *common))
        texts.append((tmp_path / "reports/validation_report.json").read_bytes())
    assert texts[0] == texts[1]


def test_synthetic_dry_run_command(tmp_path: Path, capsys) -> None:
    assert cli.main(["synthetic-dry-run", "--out", str(tmp_path)]) == 0
    assert "deterministic=True" in capsys.readouterr().out
    assert json.loads((tmp_path / "synthetic_validation_report.json").read_text())["synthetic"]


def test_release_and_review_commands_refuse_safely(pkg, tmp_path: Path, capsys) -> None:
    common = [
        "--kc",
        str(pkg.inputs.kc_csv),
        "--edges",
        str(pkg.inputs.edge_csv),
        "--vocabulary",
        str(pkg.inputs.vocabulary),
        "--review-dir",
        str(pkg.review_dir),
        "--no-sources",
        "--allow-synthetic",
    ]
    assert cli.main(args(tmp_path, "release", *common)) == 1
    assert "release refused" in capsys.readouterr().out
    entry = tmp_path / "entry.json"
    entry.write_text(json.dumps(pkg.kc_entry("KC-MAT-00001", "RV-099")))
    assert cli.main(args(tmp_path, "review-append", *common, "--entry", str(entry))) == 1
    entry.write_text(json.dumps(pkg.kc_entry("KC-MAT-00001", "RV-003")))
    assert cli.main(args(tmp_path, "review-append", *common, "--entry", str(entry))) == 0
    # Existing anchors still match; the new head is not anchored yet, so release stays blocked.
    assert cli.main(args(tmp_path, "verify-logs", *common)) == 0
    assert any("LOG_ANCHOR_MISSING" in b for b in pkg.run().release_blockers)


def test_offline_import_plan_cannot_be_approved(pkg, tmp_path: Path) -> None:
    from data_pipeline.kc_graph import release

    path = release.release(pkg.run(), tmp_path / "final", allow_synthetic_output=True)
    common = ["--review-dir", str(pkg.review_dir)]
    assert (
        cli.main(args(tmp_path, "import-plan", *common, "--snapshot", str(path), "--assume-empty"))
        == 0
    )
    plan = tmp_path / "reports/import_plan.json"
    assert json.loads(plan.read_text())["assumed_empty_database"] is True
    statement = tmp_path / "s.txt"
    statement.write_text("approve")
    assert (
        cli.main(
            args(
                tmp_path,
                "import-approval",
                *common,
                "--plan",
                str(plan),
                "--statement-file",
                str(statement),
                "--date",
                "2026-02-01",
            )
        )
        == 1
    )
    assert not list(pkg.review_dir.glob("import_approval_*"))


@pytest.mark.parametrize("command", ["taxonomy-score", "evidence-score"])
def test_pilot_scoring_without_sheets_is_pending(tmp_path: Path, command: str, capsys) -> None:
    assert cli.main(args(tmp_path, command)) == 0
    assert "pending" in capsys.readouterr().out
