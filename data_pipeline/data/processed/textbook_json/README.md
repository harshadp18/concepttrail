# Structured textbook JSON

Store cleaned chapter/section/content-unit JSON here. Preserve content types, math notation, tables, diagrams/maps, source and page provenance. Human overrides must be applied as explicit patches and logged. The original raw JSON remains unchanged. Only approved content moves to the database/publishing stage.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Stores cleaned and structured content units that are ready for validation, human review and later relational publication. It is derived from raw extraction and must retain provenance.

### 2. Recent Updates Incorporated in This Module

- Cleaning is a separate versioned output, not an in-place edit to raw extraction.
- Human overrides are applied as explicit, attributable patches.
- Subject-neutral content types cover prose, equations, questions, examples, tables, figures, maps, passages and procedures.

### 3. File Manifest

| File/path | Purpose | Exports | Dependencies |
|---|---|---|---|
| `data_pipeline/data/processed/textbook_json/<source_id>__<revision>__<pipeline-version>.json` | Clean/structured document content | Structured chapters, sections and content units | Pydantic schemas; deterministic cleaners; override applier |
| `.gitkeep` | Preserve empty directory | None | Git |

### 4. Data Structures, Types & Schemas

A structured content unit contains a stable content ID, `source_id`, source revision/hash, class, subject, course/language, curriculum version, chapter/section codes, content type, text/structured payload, PDF page index, printed page label, asset references, learning-objective links, validation state, review state, and pipeline version.

### 5. File-by-File Implementation Specification

- Apply only deterministic, logged cleaners to raw extraction output.
- Preserve Unicode, scripts, mathematical notation, units, question numbering, table headers and diagram/map references.
- Keep chapter and passage boundaries intact.
- Apply override patches by stable content ID and retain reviewer, timestamp, reason and prior value.
- Quarantine malformed or uncertain units; do not publish them by default.

### 6. Integration Points

Consumes immutable JSON from `data_pipeline/data/interim/extracted_json/` and explicit corrections from `data_pipeline/data/overrides/`. Validation and review stages generate candidate KC/question/notes exports under `data_pipeline/data/final/` and approved records for PostgreSQL import.

### 7. Module Verification Checklist

- Check source/page provenance on every unit.
- Compare representative pages with original PDFs for reading order, formulas, tables and assets.
- Verify override replay is deterministic and raw JSON remains unchanged.
- Confirm invalid/unreviewed records cannot reach publication or embedding stages.
