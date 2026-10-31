# Processed pipeline artifacts

This folder contains cleaned/structured derivatives of raw extraction. Every record must remain linked to `source_id`, source hash, curriculum identifiers and page locators. Store pipeline version and validation/review status. Never publish a record solely because parsing succeeded.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Cleaned and structured textbook JSON suitable for human review and downstream KC/chunk generation.

### 2. Recent Updates Incorporated in This Module

Preserve section boundaries, math, units, tables, passages, maps/figures, question numbers and page/source provenance.

### 3. File Manifest

Versioned structured JSON per source plus schema/QC report.

### 4. Data Structures, Types & Schemas

Each content unit has stable ID, source ID, subject/class/course/curriculum version, section title, page locators, content type, text/structured assets and review status.

### 5. File-by-File Implementation Specification

Apply deterministic cleaning and schema validation; link structured units to curriculum items only when verified; quarantine ambiguous output.

### 6. Integration Points

Feeds human review, content publish, KCs and chunking.

### 7. Module Verification Checklist

Compare sample original pages with JSON; ensure no missing table/formula/asset/page references.
