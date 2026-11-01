"""`python -m data_pipeline.kc_graph <command>`: the Phase 5 workflow, one step per command.

Read-only by default. No command validates and imports in one go. Commands that append to the
private review or lifecycle log take a human-entered entry file; commands that write to the
database need an owner approval bound to the exact plan. Exit status 0 means success with no
errors; 1 means errors were found or the step was refused.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_pipeline.kc_graph import contract as c
from data_pipeline.kc_graph import (
    import_plan,
    lifecycle,
    people,
    pilots,
    release,
    report,
    review_log,
    synthetic,
    validate,
)
from data_pipeline.kc_graph.sources import build_index


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _inputs(args: argparse.Namespace) -> validate.Inputs:
    sources = None if args.no_sources else build_index()
    return validate.Inputs(
        kc_csv=args.kc,
        edge_csv=args.edges,
        vocabulary=args.vocabulary,
        review_dir=args.review_dir,
        sources=sources,
        allow_synthetic=args.allow_synthetic,
    )


def _summary(result: validate.Result) -> str:
    errors = sum(1 for f in result.findings if f.severity == "error")
    warnings = len(result.findings) - errors
    return f"{len(result.kcs)} KCs, {len(result.edges)} edges: {errors} errors, {warnings} warnings"


def cmd_validate(args: argparse.Namespace) -> int:
    result = validate.run(_inputs(args))
    v = report.write(args.report_dir, "validation_report.json", report.validation_report(result))
    cov = report.write(args.report_dir, "coverage_report.json", report.coverage_document(result))
    outputs = {p.name: json.loads(p.read_text())["content_sha256"] for p in (v, cov)}
    report.write(
        args.report_dir, "run_manifest.json", report.run_manifest(result, outputs, "dry_run")
    )
    print(_summary(result))
    for blocker in result.release_blockers:
        print(f"release blocked: {blocker}")
    return 0 if result.ok else 1


def cmd_verify_logs(args: argparse.Namespace) -> int:
    findings = []
    custody, _ = review_log.load_custody(args.review_dir / c.CUSTODY_FILE.name)
    for name, prefix, stem in (
        (c.REVIEW_LOG.name, c.REVIEW_ID_PREFIX, "anchor"),
        (c.LIFECYCLE_LOG.name, c.LIFECYCLE_ID_PREFIX, "lifecycle-anchor"),
    ):
        events, f = review_log.read_jsonl(args.review_dir / name, name)
        findings += f + review_log.chain_findings(events, prefix, name)
        sets = {"local": review_log.read_anchors(args.review_dir / "anchors", stem)}
        if custody is not None:
            sets.update({label: review_log.read_anchors(d, stem) for label, d in custody.locations})
        findings += review_log.anchor_findings(events, sets, name)
        print(f"{name}: {len(events)} events")
    for f in findings:
        print(f"{f.code}: {f.file} {f.message}")
    return 1 if findings else 0


def cmd_verify_register(args: argparse.Namespace) -> int:
    register, findings = people.load(
        args.review_dir / c.REGISTER_FILE.name, allow_synthetic=args.allow_synthetic
    )
    for f in findings:
        print(f"{f.code}: {f.message}")
    if register:
        print(f"{len(register.people)} people, {len(register.verified_codes)} verified codes")
    return 1 if any(f.severity == "error" for f in findings) else 0


def _entry(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_review_append(args: argparse.Namespace) -> int:
    inputs = _inputs(args)
    result = validate.run(inputs)
    state = review_log.State(result.kcs, result.edges, result.resolutions, result.register)
    event = review_log.build_event(
        _entry(args.entry),
        state,
        _now(),
        synthetic=bool(result.register and result.register.synthetic),
    )
    sealed = review_log.append(args.review_dir / c.REVIEW_LOG.name, event, c.REVIEW_ID_PREFIX)
    print(f"appended {sealed['event_id']}; anchor after the session (`anchor`)")
    return 0


def cmd_lifecycle_append(args: argparse.Namespace) -> int:
    result = validate.run(_inputs(args))
    event = lifecycle.build_event(
        _entry(args.entry), result.kcs, result.edges, result.register, _now()
    )
    sealed = review_log.append(args.review_dir / c.LIFECYCLE_LOG.name, event, c.LIFECYCLE_ID_PREFIX)
    print(f"appended {sealed['event_id']}")
    return 0


def cmd_anchor(args: argparse.Namespace) -> int:
    custody, why = review_log.load_custody(args.review_dir / c.CUSTODY_FILE.name)
    if custody is None:
        print(f"refused: {why}")
        return 1
    dirs = [args.review_dir / "anchors", *(d for _, d in custody.locations)]
    for name, stem in ((c.REVIEW_LOG.name, "anchor"), (c.LIFECYCLE_LOG.name, "lifecycle-anchor")):
        events, _ = review_log.read_jsonl(args.review_dir / name, name)
        if events:
            review_log.write_anchor(dirs, review_log.anchor_record(events, _now()), stem)
            print(f"{name}: anchored seq {len(events)} in {len(dirs)} locations")
    return 0


def cmd_register_verify(args: argparse.Namespace) -> int:
    statement = args.statement_file.read_text(encoding="utf-8")
    record = people.build_verification(args.review_dir / c.REGISTER_FILE.name, statement, args.date)
    print(f"wrote {people.write_verification(args.review_dir, record).name}")
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    result = validate.run(_inputs(args))
    try:
        path = release.release(result, args.final_dir)
    except release.ReleaseRefused as exc:
        print(f"release refused: {exc}")
        return 1
    print(f"released {path.name}")
    return 0


def _lifecycle_events(review_dir: Path) -> list[dict[str, Any]]:
    return review_log.read_jsonl(review_dir / c.LIFECYCLE_LOG.name, "lifecycle")[0]


def cmd_verify_snapshot(args: argparse.Namespace) -> int:
    from app.services.graph_snapshot import verify_snapshot

    problems = verify_snapshot(release.load(args.snapshot), _lifecycle_events(args.review_dir))
    for p in problems:
        print(f"{p.code}: {p.message} {list(p.items)}")
    print("snapshot verified" if not problems else "snapshot refused: no graph may be served")
    return 1 if problems else 0


class _EmptyStore:
    """Offline planning only: pretends the tables are empty. Never used for execution."""

    def kcs(self, ids):
        return {}

    def kc_ids_by_stable_key(self, keys):
        return {}

    def edges(self, keys):
        return {}

    def subjects(self, ids):
        return set(c.SUBJECTS)


def cmd_import_plan(args: argparse.Namespace) -> int:
    snapshot = release.load(args.snapshot)
    events = _lifecycle_events(args.review_dir)
    if args.assume_empty:
        body = import_plan.plan(snapshot, _EmptyStore(), events)
        body["assumed_empty_database"] = True
    else:
        from app.db.session import create_db_engine

        with create_db_engine(read_only=True).connect() as conn:
            body = import_plan.plan(snapshot, import_plan.SqlStore(conn), events)
    path = report.write(args.report_dir, "import_plan.json", body)
    print(f"{path.name}: {body['counts']}, {len(body['conflicts'])} conflicts, 0 deletes")
    return 1 if body["conflicts"] else 0


def cmd_import_approval(args: argparse.Namespace) -> int:
    plan_body = release.load(args.plan)
    if plan_body.get("assumed_empty_database"):
        print("refused: an offline plan cannot be approved for execution")
        return 1
    record = import_plan.build_approval(
        plan_body["snapshot_sha256"],
        plan_body["plan_sha256"],
        args.statement_file.read_text(encoding="utf-8"),
        args.date,
    )
    print(f"wrote {import_plan.write_approval(args.review_dir, record).name}")
    return 0


def cmd_import_execute(args: argparse.Namespace) -> int:
    from app.db.session import create_db_engine

    try:
        audit = import_plan.execute(
            release.load(args.snapshot),
            release.load(args.plan),
            release.load(args.approval),
            create_db_engine(),
            _lifecycle_events(args.review_dir),
        )
    except import_plan.ImportAborted as exc:
        print(f"import aborted and rolled back: {exc}")
        return 1
    report.write(args.report_dir, f"import_audit_{audit['plan_sha256'][:12]}.json", audit)
    print(f"imported: {audit['counts']}")
    return 0


def cmd_import_verify(args: argparse.Namespace) -> int:
    from app.db.session import create_db_engine

    with create_db_engine(read_only=True).connect() as conn:
        body = import_plan.reconcile(release.load(args.snapshot), import_plan.SqlStore(conn))
    report.write(args.report_dir, "import_reconciliation.json", body)
    print("database matches the snapshot" if body["matches"] else "database differs")
    return 0 if body["matches"] else 1


def cmd_taxonomy_forms(args: argparse.Namespace) -> int:
    args.out.mkdir(parents=True, exist_ok=True)
    for name in ("reviewer_a", "reviewer_b"):
        (args.out / f"taxonomy_sheet_{name}.csv").write_text(
            pilots.reviewer_form(), encoding="utf-8"
        )
    print(f"wrote two blank taxonomy sheets to {args.out.name}/ (no key included)")
    return 0


def cmd_taxonomy_score(args: argparse.Namespace) -> int:
    read = lambda p: pilots.read_sheet(p) if p and p.exists() else None  # noqa: E731
    body = pilots.score_taxonomy(read(args.sheet_a), read(args.sheet_b), read(args.adjudication))
    report.write(args.report_dir, "taxonomy_pilot.json", body)
    print(f"taxonomy pilot: {body['status']}")
    return 0 if body["status"] in ("scored", "pending_human_assessment") else 1


def cmd_evidence_score(args: argparse.Namespace) -> int:
    rows = [r for p in args.sheets if p.exists() for r in pilots.read_sheet(p)]
    body = pilots.score_evidence(rows)
    report.write(args.report_dir, "evidence_pilot.json", body)
    print(f"evidence pilot: {body['status']}")
    return 0 if body["status"] in ("scored", "pending_human_review") else 1


def cmd_synthetic_dry_run(args: argparse.Namespace) -> int:
    """Build the synthetic package twice in temp dirs; reports must be byte-identical."""
    texts = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            result = validate.run(synthetic.build(Path(tmp)))
            texts.append(report.dumps(report.validation_report(result)))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "synthetic_validation_report.json").write_text(texts[0], encoding="utf-8")
    same = texts[0] == texts[1]
    print(f"SYNTHETIC dry run: {_summary(result)}; deterministic={same}")
    return 0 if same and result.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m data_pipeline.kc_graph")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--kc", type=Path, default=c.KC_CSV)
        p.add_argument("--edges", type=Path, default=c.EDGE_CSV)
        p.add_argument("--vocabulary", type=Path, default=c.VOCABULARY_FILE)
        p.add_argument("--review-dir", type=Path, default=c.REVIEW_DIR)
        p.add_argument("--report-dir", type=Path, default=c.REPORT_DIR)
        p.add_argument("--final-dir", type=Path, default=c.FINAL_DIR)
        p.add_argument("--no-sources", action="store_true", help="skip source resolution")
        p.add_argument("--allow-synthetic", action="store_true", help="tests only")
        return p

    commands = {
        "validate": (cmd_validate, "dry-run validation and coverage reports (read-only)"),
        "verify-logs": (cmd_verify_logs, "verify review and lifecycle chains and anchors"),
        "verify-register": (cmd_verify_register, "check the register and owner verification"),
        "review-append": (cmd_review_append, "append one human review entry"),
        "lifecycle-append": (cmd_lifecycle_append, "append one authorised lifecycle entry"),
        "anchor": (cmd_anchor, "write write-once head anchors to the custody locations"),
        "register-verify": (cmd_register_verify, "OWNER: write the register verification"),
        "release": (cmd_release, "write the released snapshot (no database)"),
        "verify-snapshot": (cmd_verify_snapshot, "verify a released snapshot, fail closed"),
        "import-plan": (cmd_import_plan, "read-only import plan for a released snapshot"),
        "import-approval": (cmd_import_approval, "OWNER: approve one exact import plan"),
        "import-execute": (cmd_import_execute, "OWNER-APPROVED: apply an approved plan"),
        "import-verify": (cmd_import_verify, "read-only reconciliation after import"),
        "taxonomy-forms": (cmd_taxonomy_forms, "blank D4 reviewer sheets"),
        "taxonomy-score": (cmd_taxonomy_score, "score two completed D4 sheets"),
        "evidence-score": (cmd_evidence_score, "score completed D11 sheets"),
        "synthetic-dry-run": (cmd_synthetic_dry_run, "end-to-end synthetic determinism check"),
    }
    for name, (func, help_text) in commands.items():
        p = common(sub.add_parser(name, help=help_text))
        p.set_defaults(func=func)
        if name in ("review-append", "lifecycle-append"):
            p.add_argument("--entry", type=Path, required=True)
        if name in ("register-verify", "import-approval"):
            p.add_argument("--statement-file", type=Path, required=True)
            p.add_argument("--date", required=True)
        if name in ("verify-snapshot", "import-plan", "import-execute", "import-verify"):
            p.add_argument("--snapshot", type=Path, required=True)
        if name == "import-plan":
            p.add_argument("--assume-empty", action="store_true", help="offline plan only")
        if name in ("import-approval", "import-execute"):
            p.add_argument("--plan", type=Path, required=True)
        if name == "import-execute":
            p.add_argument("--approval", type=Path, required=True)
        if name == "taxonomy-forms":
            p.add_argument("--out", type=Path, default=c.CURATED_DIR / "pilot")
        if name == "taxonomy-score":
            p.add_argument("--sheet-a", type=Path)
            p.add_argument("--sheet-b", type=Path)
            p.add_argument("--adjudication", type=Path)
        if name == "evidence-score":
            p.add_argument("--sheets", type=Path, nargs="*", default=[])
        if name == "synthetic-dry-run":
            p.add_argument("--out", type=Path, default=c.REPORT_DIR / "synthetic")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, RuntimeError) as exc:
        print(f"refused: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
