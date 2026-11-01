# Human review overrides

Store reviewer corrections separately from raw and processed output. Each override should identify source ID/hash, page or content-unit ID, reviewer, review date, reason, old value and corrected value. Pipeline reruns should reapply valid overrides without erasing their provenance. Overrides do not change the source PDF itself.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Versioned human correction layer for extraction and structured-content issues.

### 2. Recent Updates Incorporated in This Module

Overrides are reapplied after generated stages and must not be lost on rerun.

### 3. File Manifest

Override records keyed by source version, page/content-unit ID and field path; reviewer, timestamp, reason and before/after hashes.

### 4. Data Structures, Types & Schemas

An override changes only the specified field and records provenance; source raw artifact remains unchanged.

### 5. File-by-File Implementation Specification

Validate target exists; reject stale override if source hash differs; apply deterministically after clean/structure stages.

### 6. Integration Points

Consumed by `structure_content`/publish workflow; exported in QC reports.

### 7. Module Verification Checklist

Test deterministic replay, stale-source conflict and idempotent reapplication.

## Publication status

Everything in `overrides/` except READMEs and `.gitkeep` is **private and Git-ignored** (`.gitignore`: `data_pipeline/data/overrides/**`). The records hold owner attestations and rights statements, so they are not published. Code that reads them (for example `teacher_validation.py`, `authorization.py`) is published; the records are supplied separately. See `docs/PUBLICATION_AND_REPRODUCIBILITY.md` for what a fresh clone can and cannot reproduce.
