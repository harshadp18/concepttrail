# Phase 5 implementation handoff (revision 4: engineering implemented)

The KC and prerequisite-graph engineering described in [`PHASE_5_CSV_CONTRACT.md`](PHASE_5_CSV_CONTRACT.md) and [`PHASE_5_REVIEW_GUIDELINES.md`](PHASE_5_REVIEW_GUIDELINES.md) is built and tested **on synthetic data**. This document records what exists, how the activities stay separate, and what only people can now do. Implemented does **not** mean approved: decision status is in [`PHASE_5_DECISION_MATRIX.md`](PHASE_5_DECISION_MATRIX.md) and is unchanged.

The teammate owns FastAPI endpoints, authentication and API transport. Phase 5 provides services they can call (`app.services.graph_snapshot.load_released_graph`, `app.services.prerequisite_graph`); no route was added.

## 1. Five separate activities (never merged)

| Activity | What it is | Writes | Needs |
|---|---|---|---|
| **A. Loader** | parse, validate, resolve, verify, report | nothing but reports | nothing |
| **B. Dry-run validation** | `validate`, the default mode | `data/logs/kc_graph/` only | nothing for synthetic data; owner decisions for real data |
| **C. Human review and approval** | registered people append review and lifecycle events | the private logs and anchors | R2 (custody), R4 (register and verification) |
| **D. Database import** | write a released snapshot to PostgreSQL | `knowledge_component`, `kc_edge` | **separate explicit owner approval of one exact plan**; never part of loader execution |
| **E. AI candidate generation** | a local model drafts rows | draft rows (`needs_review`) | **a separate D17 rights record** (none exists), Hindi excluded |

## 2. Modules (implemented)

```
data_pipeline/kc_graph/
  contract.py      headers, patterns, closed values, quorum, paths and every finding code
  findings.py      the one sortable, path-free Finding type
  vocabulary.py    owner vocabulary file, or the labelled built-in provisional proposal
  csv_io.py        strict UTF-8/RFC 4180 reading, exact header and width
  rows.py          typed KC and edge rows with field-level findings
  keys.py          kc_id and stable-key rules, similar keys
  digests.py       full and pedagogical digests; field classes P/S/C
  sources.py       token resolution against the inventory, artifacts and rights gate
  people.py        register and the owner's write-once verification
  review_log.py    events, hash chain, anchors, custody, approval verification
  lifecycle.py     retirement and reinstatement log and checks
  validate.py      runs every stage; reuses validate_graph and coverage_report
  report.py        deterministic validation and coverage reports, run manifest
  release.py       write-once released snapshot and manifest
  import_plan.py   read-only plan, owner-approved transactional execute, reconcile
  pilots.py        D4 and D11 forms, sampling and scoring
  drafting.py      local Ollama drafting adapter, refused unless authorised
  synthetic.py     the synthetic end-to-end package (tests and the synthetic dry run)
  cli.py           python -m data_pipeline.kc_graph <command>
app/schemas/knowledge.py          KcRecord.scope and KcRecord.lifecycle (defaults keep old callers working)
app/services/prerequisite_graph.py retired-aware gating; scope/lifecycle-aware coverage
app/services/graph_snapshot.py    verify_snapshot, load_released_graph (fail closed)
app/services/audit_chain.py       canonical JSON, SHA-256, chain verification
data_pipeline/prompts/kc_graph_drafting_v1.md  versioned drafting prompt
```

The loader imports no FastAPI, database driver, HTTP client or provider module (a test asserts it). Only `import_plan.py` touches SQLAlchemy, and only `execute` writes.

## 3. Build sequence (all ten steps done)

| Step | Work | Milestone |
|---|---|---|
| 1 | CSV parsing: exact headers, row width, UTF-8, types | M1 |
| 2 | Validate KC rows and edge rows: required cells, vocabularies, keys, aliases, scope, misconceptions, class levels, `chapter_order` ban | M1 |
| 3 | Resolve source references and evidence digests: grammar, accepted inventory, page and paragraph range, pin, passage digest | M2 |
| 4 | Verify review records and approval status: register, verification, log chain, anchors, events, quorum, independence | M3 |
| 5 | Version and lifecycle checks: digests, field classes, staleness, reaffirmation, retirement, snapshot | M3, M4 |
| 6 | Reuse the graph release gate: build `KcRecord`/`EdgeRecord` (with derived `rev:` evidence) and call `validate_graph` | M1 (shape), M4 (full) |
| 7 | Detailed validation and coverage reports, including the foundation section | M5 |
| 8 | Deterministic dry-run: stable ordering, a run manifest with input and output digests, no timestamps in content digests | M5 |
| 9 | Comprehensive unit and integration tests | every milestone |
| 10 | Import-ready transaction plan (generated; executed only with owner approval) | M6 |

### Milestones (implemented)

- **M1 rows and graph shape.** Headers and samples are checked byte-for-byte against the contract; every M1 code has a test.
- **M2 sources.** The 10 pilot documents resolve against their real normalised artifacts (read-only); everything else is `SOURCE_ARTIFACT_MISSING`.
- **M3 review integrity.** Every row of the guidelines' detection table is tested, plus quorum, independence, staleness, clerical and wording-only confirmations, reaffirmation, conflicts and adjudication.
- **M4 lifecycle and release.** Retirement, edge resolution, write-once snapshots, and every fail-closed case of `load_released_graph`.
- **M5 reports.** Byte-identical reports across runs (tested), coverage with declared, mapped and foundation sections.
- **M6 import.** Plan, owner approval, transactional execute with re-planning and read-back, rollback, idempotency and reconciliation, tested on a disposable SQLite database only.

## 4. Commands

`python -m data_pipeline.kc_graph --help`. Read-only: `validate`, `verify-logs`, `verify-register`, `verify-snapshot`, `import-plan` (read-only database connection, or `--assume-empty` offline), `import-verify`, `taxonomy-forms`, `taxonomy-score`, `evidence-score`, `synthetic-dry-run`. Append-only private records: `review-append`, `lifecycle-append`, `anchor`, `register-verify` (owner). Final exports: `release`. **Database writes: only `import-execute`, which refuses without an owner approval bound to the exact snapshot and plan digests, re-plans inside the transaction, aborts on any drift or conflict, verifies by reading back and rolls back on any mismatch.** An offline (`--assume-empty`) plan can never be approved.

## 5. Readiness (final classification)

| Activity | Status | Exact blockers |
|---|---|---|
| CSV loader implementation | **DONE** | none |
| Synthetic dry-run validation | **DONE** | none; deterministic, repeated runs byte-identical |
| Source resolution against real data | **DONE** for the 10 pilot documents | curated CSVs that cite them (none exist) |
| Review-log implementation | **DONE**, tested on synthetic data | **real use blocked** until R2 (custody) and R4 (register and the owner's verification) |
| Human-reviewed pilot | **BLOCKED** | owner approval of D1, D2 (with R3), D6, D7, D8, D9, D13, D14, D18; R2; R4; R7; a D4 decision; two registered qualified reviewers per subject; the owner's vocabulary file |
| D4 taxonomy assessment | tooling **DONE**; assessment **PENDING** | two registered independent human reviewers; R6 thresholds |
| D11 evidence pilot | tooling **DONE**; pilot **BLOCKED** | human-authored candidate edges; reviewers; R2, R4, R6 |
| Released snapshot and runtime consumption | **DONE** (service); runtime delivery blocked | R1 |
| Database import | tooling **DONE**; actual import **requires separate explicit owner approval** | D3; a released real snapshot; R1; a read-only plan against the real database; the owner's approval record |
| Local AI candidate generation | adapter **DONE**, mock-tested; **requires separate rights authorisation** | an owner-created record granting `local_llm_kc_drafting` / `local_llm_prerequisite_edge_drafting`; Hindi quality evaluation |
| External provider processing | **NOT AUTHORISED** | no rights record covers it; no external adapter exists in Phase 5 |

## 6. Safety rules that still apply

No database writes or migrations without the separate approval above; no `.env` reads by the tooling except through `app.db.session` when the owner runs an import command; no external model calls; no curated KC or edge data is created by engineers (synthetic fixtures only, never under `data/curated/`); D-050, the Phase 4 attestations, textbook sources and pilot outputs are never edited; every private path stays ignored.
