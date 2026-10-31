# CSV-cleaning manifests and logs

> **Not used by the implemented teammate CSV pipeline (owner decision D-030, 2026-10-31).** Its outputs go to `resources/teammate_csv/processed/` and `resources/teammate_csv/mappings/`. This folder is reserved; the contract below remains the reference for artifact contents.

Store one immutable run manifest and redacted JSONL event log per cleaning run. The manifest records input file name, SHA-256, byte size, detected encoding/delimiter, cleaning script/version, config/rules hash, mapping version, counts (input/accepted/rejected/excluded/duplicate), output paths and output SHA-256 values. Event logs record safe error codes and logical row numbers, not full protected textbook passages or personal values.

### Module specification

1. **Purpose:** reproducibility and audit trail for teammate CSV cleaning.
2. **Updates:** records accepted/rejected reconciliation and PDF cross-check status.
3. **Manifest:** `cleaning_manifest.json`, `events.jsonl`, `quality_report.md`.
4. **Schema:** run ID, input hash, rule/script versions, mapping version, counts, output hashes and rights status.
5. **File behavior:** immutable per-run records; redacted structured diagnostics.
6. **Integration:** emitted by all CSV stages and consumed by QA/review.
7. **Verification:** hashes resolve, counts reconcile and redaction tests pass.
