# Raw textbook sources

Store only files that the team is allowed to acquire and process for the intended purpose. Keep original bytes unchanged. Organise by class/subject/edition and use the `source_id` from `curriculum.csv` in filenames. Record SHA-256, acquisition date and source URL in the master CSV. Never commit PDFs to Git. If rights are unknown, do not run extraction or send files to an external model.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Immutable storage boundary for original source PDFs or other acquired source files. It is an input to the offline pipeline, never a published student-facing content store.

### 2. Recent Updates Incorporated in This Module

- The source file must have a matching row in `data_pipeline/curriculum.csv`.
- No acquisition or processing occurs while the required use-specific rights are unknown or denied.
- Original bytes are never modified in place; each edition/revision is retained as a distinct artifact.

### 3. File Manifest

| File/path | Purpose | Exports | Dependencies |
|---|---|---|---|
| `data_pipeline/data/raw/textbooks/<source_id>/<source_version>/` | Original PDF and permitted source assets | Immutable source bytes | Filesystem permissions; master inventory metadata |
| `.gitkeep` | Preserve an empty directory in Git | None | Git |

### 4. Data Structures, Types & Schemas

A source artifact is identified by `source_id`, source revision/edition, SHA-256, acquisition timestamp, source URL, class, subject, course/language, academic session, `rights_status`, and purpose-specific permission flags from the master inventory.

### 5. File-by-File Implementation Specification

- Store source bytes under a stable `source_id` and revision path; do not use class/subject filenames as identity.
- Compute SHA-256 after acquisition and compare it with `curriculum.csv`.
- Make files read-only after the acquisition stage where the platform permits.
- Reject path traversal, unexpected file types, oversized files and hash mismatches.
- Never place private PDFs in a commit, package release, public object bucket or external LLM request by default.

### 6. Integration Points

The acquisition stage writes this directory; extraction reads it read-only and writes separate raw page-aware JSON under `data_pipeline/data/interim/extracted_json/`. The rights gate reads permission fields from `curriculum.csv`.

### 7. Module Verification Checklist

- Verify every acquired file has an inventory row and source ID.
- Recompute SHA-256 and compare with the recorded value.
- Confirm ignored/private-file rules prevent accidental commits.
- Test that missing/denied permission blocks extraction and external-model processing.
