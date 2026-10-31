# Raw extracted JSON

One versioned JSON artifact per source file/revision. Preserve pages, chapters/sections, text, question numbers, tables/figures/maps references, OCR flags, tool version and page locators. Raw output is immutable; cleaning writes to `processed/textbook_json/`.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Immutable raw extraction output. It preserves page-level extractor output and diagnostics before cleaning, reordering, correction or structuring.

### 2. Recent Updates Incorporated in This Module

- PDF page index and printed page label are separate fields.
- PyMuPDF text-native extraction is attempted first; OCR is limited to scanned/low-text pages and its use is recorded per page.
- Raw extraction output is never overwritten by cleaning or human correction.

### 3. File Manifest

| File/path | Purpose | Exports | Dependencies |
|---|---|---|---|
| `data_pipeline/data/interim/extracted_json/<source_id>__<revision>__<sha256-prefix>.json` | Page-aware raw extraction record | Raw page/text/asset records and diagnostics | PyMuPDF; optional Tesseract |
| `.gitkeep` | Preserve empty directory | None | Git |

### 4. Data Structures, Types & Schemas

Each JSON artifact records `source_id`, `source_sha256`, class, subject, course/language, curriculum version, pipeline version, tool versions, pages, zero-based PDF page index, printed page label when known, extraction method, text blocks, asset references, empty/low-text flags, errors, and extraction status.

### 5. File-by-File Implementation Specification

- Write one versioned JSON file per source revision and extraction configuration.
- Preserve page order and text blocks; do not silently merge pages or sections.
- Record OCR usage and confidence/quality flags per page.
- Preserve references to equations, tables, diagrams, maps and figures even when textual extraction is incomplete.
- A rerun with the same source hash, stage version and configuration hash reuses the artifact; a changed input creates a new generation.

### 6. Integration Points

Extraction stages read permitted files from `data_pipeline/data/raw/textbooks/`. Cleaning stages read these JSON records and write new outputs to `data_pipeline/data/processed/textbook_json/`. QC and human reviewers inspect the raw JSON against the source pages.

### 7. Module Verification Checklist

- Confirm every source page has a corresponding page record or explicit failure status.
- Verify page index and printed page label are not conflated.
- Check extraction tool/version and OCR flags are recorded.
- Confirm raw JSON checksum is stable and cleaning never mutates it.
