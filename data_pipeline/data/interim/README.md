# Interim extraction artifacts

Store raw page-level extractor and OCR outputs here. Preserve original source hash, source ID, PDF page index, printed page label where available, extraction method and diagnostics. Do not overwrite raw output with cleaning transformations. These artifacts may contain protected textbook material; keep private and out of Git.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Immutable raw page-extraction JSON before cleaning or structuring.

### 2. Recent Updates Incorporated in This Module

PDF page index and printed page label are distinct; extraction diagnostics and OCR indicator are retained.

### 3. File Manifest

One JSON artifact per source version/run plus page-level diagnostics and a run manifest.

### 4. Data Structures, Types & Schemas

Include `source_id`, SHA-256, extractor/version, page_count, page index, text, image refs, OCR method, text length and extraction status.

### 5. File-by-File Implementation Specification

Write atomically; never patch source text in place; failed pages remain explicit records.

### 6. Integration Points

Input to cleaning/structure stages only.

### 7. Module Verification Checklist

Page indices are continuous/traceable; total pages reconcile; OCR-only pages are flagged.
