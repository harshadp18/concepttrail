# Curated sources (private)

Hand-curated, human-reviewed source data that is **not generated** and is the working source of truth for its subject. Phase 5 uses `kc_graph/` for the knowledge-component and prerequisite CSVs and the owner-maintained vocabularies.

- Everything here except READMEs and `.gitkeep` is **Git-ignored** (`data_pipeline/data/curated/**`). It is derived from textbook content and is published only after a separate review.
- Do not put generated output here; generated exports go to `final/`, validation reports to `logs/`, review events and the reviewer register to `overrides/kc_review/`.
- Neither Git nor the database keeps history of these files. Keep dated snapshots and a private backup.

Contract: `docs/PHASE_5_CSV_CONTRACT.md`. Process: `docs/PHASE_5_REVIEW_GUIDELINES.md`.
