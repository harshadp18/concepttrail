# CSV profiling outputs

> **Not used by the implemented teammate CSV pipeline (owner decision D-030, 2026-10-31).** Its outputs go to `resources/teammate_csv/processed/` and `resources/teammate_csv/mappings/`. This folder is reserved; the contract below remains the reference for artifact contents.

Store non-destructive profiles for each teammate CSV/run. Required artifacts: `profile.json` and human-readable `profile.md`. Include source snapshot hash, logical row count, physical line diagnostics, headers and order, encoding, delimiter, quote/escape settings, per-column null counts, uniqueness, candidate types, length/range summaries, duplicate estimates and parser warnings. Redact potentially personal/sample values.

Do not change source values or infer the dataset's business meaning from a profile alone. Type inference is diagnostic, not a conversion instruction.

### Module specification

1. **Purpose:** record objective data-quality condition before transformations.
2. **Updates:** supports teammate CSV QA and PDF pairing decisions.
3. **Manifest:** `profile.json`, `profile.md`, optional parser diagnostics.
4. **Schema:** run ID, input SHA-256, schema fingerprint, detected dialect, headers, row counts and per-column metrics.
5. **File behavior:** deterministic JSON; reports redact sensitive samples.
6. **Integration:** produced by `profile_csv.py`, consumed by rule/mapping review.
7. **Verification:** counts reconcile to parser records; no source modifications; privacy redaction tests pass.
