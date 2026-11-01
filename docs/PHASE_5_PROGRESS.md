# Phase 5 progress: knowledge components and the prerequisite graph

**Status (2026-10-31): Phase 5 engineering implementation is complete, but Phase 5 is not formally closed pending the listed human and owner-controlled acceptance gates.** None of D1–D18 is recorded as approved; only the two CSV headers and their column order are owner-instructed.

## Scope (authoritative)

Roadmap Phase 5 ([`IMPLEMENTATION_ROADMAP.md`](IMPLEMENTATION_ROADMAP.md)): knowledge components and the prerequisite graph. Pass criteria: unique IDs, no orphan endpoints or cycles, reviewed edges, coverage reports by class and subject. Embeddings and retrieval (roadmap Phase 7) and the LLM answer flow (Phase 8) are out of scope. FastAPI endpoints, authentication and transport belong to the teammate; Phase 5 adds no route.

## What exists (implemented and tested)

| Capability | Where | Evidence |
|---|---|---|
| Strict CSV ingestion, exact 18- and 11-column headers | `data_pipeline/kc_graph/csv_io.py`, `rows.py` | `test_kc_graph_csv_rows.py` |
| KC rules: IDs, stable keys, closed domains and facets, aliases, misconceptions, scope, classes, versions | `rows.py`, `keys.py`, `vocabulary.py`, `validate.py` | `test_kc_graph_csv_rows.py` |
| Edge rules: endpoints, direction, basis (`chapter_order` banned), strength, evidence grammar, cycles (graph service) | `rows.py`, `validate.py`, `app/services/prerequisite_graph.py` | `test_kc_graph_csv_rows.py`, `test_prerequisite_graph.py` |
| Source resolution against the inventory, existing artifacts and the rights gate | `sources.py` | `test_kc_graph_sources.py` (the 10 pilot documents resolve, read-only) |
| Person register and the owner's write-once verification | `people.py` | `test_kc_graph_review.py` |
| Hash-chained review log, anchors, two-location custody gate | `review_log.py`, `app/services/audit_chain.py` | `test_kc_graph_review.py` (every detection-table case) |
| Approval verification: quorum, independence, staleness, versions, clerical and wording-only confirmations, reaffirmation, conflicts, adjudication, evidence assessment | `review_log.py`, `digests.py` | `test_kc_graph_review.py` |
| Non-destructive retirement and lifecycle log | `lifecycle.py` | `test_kc_graph_lifecycle_release.py` |
| Released snapshots and fail-closed runtime loading | `release.py`, `app/services/graph_snapshot.py` | `test_kc_graph_lifecycle_release.py` |
| Scope- and lifecycle-aware coverage (declared vs mapped, foundation section) | `app/services/prerequisite_graph.py` | `test_kc_graph_lifecycle_release.py` |
| Deterministic reports and run manifest | `report.py`, `cli.py` | `test_kc_graph_cli_contract.py` (byte-identical reruns) |
| Import plan, owner-approved transactional execute, rollback, idempotency, reconciliation | `import_plan.py` | `test_kc_graph_import.py` (disposable SQLite only) |
| D4 and D11 pilot forms, sampling and scoring | `pilots.py` | `test_kc_graph_pilots.py` |
| Local drafting adapter, refused without a rights record | `drafting.py`, `data_pipeline/prompts/kc_graph_drafting_v1.md` | `test_kc_graph_drafting.py` (mock transport only) |
| End-to-end synthetic dry run | `synthetic.py`, `python -m data_pipeline.kc_graph synthetic-dry-run` | deterministic; 0 errors |

## What does not exist (and why)

- **No curated KC or edge data, no real review event, no reviewer register, no register verification, no custody configuration, no vocabulary file, no released snapshot, no import plan against the real database, no database write.** These are human and owner actions, not engineering.
- **The D4 taxonomy assessment and the D11 evidence pilot have not been performed.** Their tooling is ready; no reviewer exists to perform them, and synthetic test sheets are not results.
- **No KC or edge drafting with a model.** No rights record grants `local_llm_kc_drafting` or `local_llm_prerequisite_edge_drafting`, so the gate refuses every real request. External processing remains unauthorised.
- **No `kc_curriculum_map` rows are generated.** No approved curriculum-mapping source exists; coverage reports mapped figures as `null`.

## Acceptance gate (roadmap Phase 5 and the owner's criteria)

| Criterion | Engineering | Operational |
|---|---|---|
| Unique IDs, keys; no orphan endpoints, self-edges, duplicates or cycles | **met** (enforced) | pending real data |
| Approved subject-aware domains and facets; approved skill taxonomy | supported (provisional list, labelled) | **pending owner** (R3, D4 assessment, R7) |
| Traceable source references | **met** (resolver) | pending real data |
| Evidence-backed, individually human-reviewed edges by qualified independent reviewers | **met** (verification) | **pending human review** (R4 register, reviewers) |
| Append-only, anchored review records | **met** | **pending owner** (R2 custody) |
| Stale approval detection, versioning, lifecycle | **met** | pending real data |
| Coverage by subject and class, foundation reported separately | **met** | pending real data |
| Retirement-aware snapshots, fail-closed runtime | **met** | **pending owner** (R1 delivery) |
| Transactional, idempotent import | **met** (disposable database) | **pending owner approval** of an exact plan |
| D4 and D11 pilots by real people | tooling **met** | **pending human review** |
| D17 rights record before real drafting | gate **met** | **pending rights authorisation** |

## Exact next actions (people only)

1. Owner: decide D1, D2 (R3, every list entry), D4 (provisional list or assessment), D6, D7, D8, D9, D13, D14, D18, R5, R6, R7.
2. Owner: create `overrides/kc_review/people.json` with real reviewer codes (R4) and run `register-verify`.
3. Owner: designate two encrypted custody locations outside the repository in `custody.json` (R2).
4. Owner: create `curated/kc_graph/kc_vocabularies.json` with `status: owner_confirmed`.
5. Two registered reviewers: complete the D4 sheets (`taxonomy-forms`); authors write candidate KCs and edges from the 10 pilot documents; two reviewers per edge run the D11 pilot.
6. Owner: decide R1, then release; approve one exact import plan if and when an import is wanted.
7. Optional: an owner rights record naming the two drafting uses, if local drafting is wanted (Hindi stays excluded).

## Owner decisions

The consolidated sheet is [`PHASE_5_OWNER_DECISION_CHECKLIST.md`](PHASE_5_OWNER_DECISION_CHECKLIST.md). None of D1–D18 is recorded as approved by it either.
