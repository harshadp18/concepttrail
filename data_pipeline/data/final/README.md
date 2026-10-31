# Derived and publish-ready exports

Contains reproducible derived CSV/JSON outputs. Current explicit outputs: `kc_components.csv`, `prerequisites.csv`, `questions.csv`; `notes.csv` is the proposed fourth output pending owner confirmation. The files in this directory are generated, not the master source. Do not hand-edit generated output; correct `curriculum.csv` or reviewed overrides and rerun the responsible stage. Import only records that pass permission, validation and review gates.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Generated, reviewable export artifacts; never a source of truth.

### 2. Recent Updates Incorporated in This Module

CSV outputs are derived from validated inventory/structured data; `notes.csv` remains provisional until owner confirms columns.

### 3. File Manifest

`kc_components.csv`, `prerequisites.csv`, `questions.csv`, `notes.csv`.

### 4. Data Structures, Types & Schemas

Stable IDs, source references, review state and verification evidence; match import schema before publication.

### 5. File-by-File Implementation Specification

Generate from validated source artifacts, sort deterministically, use UTF-8, validate headers and emit a row-count report.

### 6. Integration Points

Consumed by relational import/publish; never edit generated files manually (use overrides).

### 7. Module Verification Checklist

Regeneration is reproducible; no missing FKs, orphan KCs, unreviewed publications or invalid CSV headers.
