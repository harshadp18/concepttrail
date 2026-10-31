# Immutable raw inputs

This directory stores byte-identical, hash-addressed snapshots of user-supplied inputs. The friendly copy/paste drop-zones are `resources/textbook_pdfs/` and `resources/teammate_csv/incoming/`. Never treat this directory as editable working storage.

- `textbooks/`: source PDFs copied from the resource drop-zone after metadata/rights checks.
- `teammate_csv/`: original CSV snapshots.

Every snapshot path includes a safe dataset/source slug and SHA-256. Verify copy hash equals input hash. No cleaning or OCR output is written here.

### Module specification

1. **Purpose:** immutable input snapshot boundary.
2. **Updates:** adds raw teammate CSV snapshots alongside source PDFs.
3. **Manifest:** `textbooks/`, `teammate_csv/`, `README.md`.
4. **Schema:** `source_id`/dataset slug, original filename, SHA-256 and acquired timestamp in manifest; curriculum source metadata remains in master CSV.
5. **File behavior:** write once; identical hash reuses snapshot; different hash creates a new version.
6. **Integration:** profile, extraction and evidence cross-check stages read snapshots.
7. **Verification:** byte-level hash comparison and immutability test.
