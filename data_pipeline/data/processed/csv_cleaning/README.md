# Accepted and rejected cleaned CSV outputs

> **Not used by the implemented teammate CSV pipeline (owner decision D-030, 2026-10-31).** Its outputs go to `resources/teammate_csv/processed/` and `resources/teammate_csv/mappings/`. This folder is reserved; the contract below remains the reference for artifact contents.

Each cleaning run gets its own directory: `<dataset_slug>/<run_id>/`. Store `accepted.csv`, `rejected.csv`, `validation_report.json` and `rules_applied.json`. The accepted file preserves original input headers and order unless an explicitly reviewed canonical mapping is applied. The rejected file preserves original row values and adds `__source_row_number` and `__rejection_codes`. Never overwrite a prior run.

Do not autocorrect factual curriculum information. Ambiguous, conflicting, unmapped or evidence-deficient rows are rejected/quarantined or marked for review; they are not silently repaired.

### Module specification

1. **Purpose:** versioned derivative of teammate input after configured cleaning/validation.
2. **Updates:** accepted/rejected split and machine-readable reasons.
3. **Manifest:** accepted/rejected CSVs, validation report and cleaning rules record.
4. **Schema:** original columns preserved by default; canonical schema only when explicitly mapped.
5. **File behavior:** deterministic and idempotent; new run directory for changed source/config/script version.
6. **Integration:** human review and approved canonical mapping/import.
7. **Verification:** original row reconciliation, schema validation, idempotent output hashes and preserved Unicode/IDs.
