# KC review records (private)

Review events, the reviewer register and its verification record, the lifecycle log and log anchors for Phase 5. Everything except this README is **Git-ignored** (`overrides/**`).

- `review_log.jsonl`, `lifecycle_log.jsonl`: append-only, hash-chained. Tamper-evident, **not** immutable storage.
- `people.json`, `people_verification_<date>.json`: the person register and the owner's write-once verification of it.
- `anchors/`: write-once `anchor-<seq>.json` and `lifecycle-anchor-<seq>.json`. Each anchor must also exist in two separate encrypted custody locations outside the repository.

- `custody.json`: the owner's two custody locations (absolute paths outside the repository). Not designated yet.
- `generation/`: drafting generation records (no textbook text); empty while drafting is unauthorised.
- `import_approval_<date>_<plan>.json`: the owner's write-once approval of one exact import plan.

Specification and commands: `docs/PHASE_5_REVIEW_GUIDELINES.md` (section 11). Tooling: `data_pipeline/kc_graph/` (tested on synthetic data only; none of these files exists yet).
