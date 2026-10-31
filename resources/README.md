# `resources/` — user-provided resource drop-zone

## What to copy here

This folder is the easy hand-off point for materials the user receives from the teammate. Copy files here using File Explorer; do not edit the originals after copying.

| Resource | Exact drop-zone | Purpose |
|---|---|---|
| Original textbook/source PDFs | `resources/textbook_pdfs/` | Local reference material used to verify the teammate's CSV and later for permitted extraction |
| Teammate-generated CSV exports | `resources/teammate_csv/incoming/` | Input datasets to profile, clean, validate and potentially map into ConceptTrail schemas |

## Important workflow

1. Copy PDFs into `resources/textbook_pdfs/`; optional subfolders by class, subject and edition are recommended.
2. Copy the teammate's original CSV file(s) into `resources/teammate_csv/incoming/`. Keep original filenames.
3. Tell Claude Code which CSV corresponds to which PDF set when that relationship is not evident. It must not assume a match from filenames alone.
4. Claude Code first profiles the CSV, snapshots its original bytes and produces a data-quality report. It then cleans only under documented rules, emits accepted and rejected rows, and cross-checks content against PDFs only when local processing permission is clear.
5. Find outputs under `resources/teammate_csv/processed/{cleaned,rejected,reports,manifests}/` and `resources/teammate_csv/mappings/` (owner decision D-030); immutable snapshot under `data_pipeline/data/raw/teammate_csv/`; run `python -m data_pipeline.clean_teammate_csv` (see `data_pipeline/README.md`).

## Rights and privacy gate

A file being present in this folder does not itself grant permission for extraction, OCR, external-model processing, embeddings, indexing, training, display or redistribution. Record each relevant permission for each source. If local content processing permission is unknown or denied, Claude may inventory file metadata and profile the CSV but must not extract/OCR the PDF or use its contents to correct CSV values. External provider calls are separately gated.

Do not place API keys, passwords, student personal data or confidential information here unless the project has an approved lawful basis and access/retention plan. Do not commit files from these drop-zones to Git.

## Module specification

### 1. Module Purpose & Architectural Role

Human-friendly input boundary for teammate CSVs and their textbook/source PDFs. It is not a second curriculum inventory.

### 2. Recent Updates Incorporated in This Module

Adds a dedicated drop-zone and a non-destructive CSV cleaning workflow; expressly excludes frontend development by Claude Code.

### 3. File Manifest

- `resources/README.md`: hand-off and policy instructions.
- `resources/textbook_pdfs/README.md`: PDF intake instructions.
- `resources/teammate_csv/README.md`: teammate CSV intake instructions.
- `resources/teammate_csv/incoming/README.md`: exact incoming-file location.

### 4. Data Structures, Types & Schemas

The drop-zone has no independent master metadata schema. Source metadata and purpose-specific permissions remain in the single `data_pipeline/curriculum.csv`; cleaning-run metadata lives in run manifests.

### 5. File-by-File Implementation Specification

Do not run executable processing from this directory. Pipeline modules read from this folder, hash/copy inputs to immutable raw storage, and write all generated outputs under `data_pipeline/data/`.

### 6. Integration Points

Consumed by `data_pipeline/stages/profile_csv.py`, `clean_csv.py`, `validate_csv.py`, `compare_csv_to_pdfs.py` and the PDF acquisition/extraction stages.

### 7. Module Verification Checklist

Files remain byte-identical; resources are Git-ignored; unknown rights block PDF content processing; originals in `incoming/` and `textbook_pdfs/` are never written; generated outputs go only to `resources/teammate_csv/processed/` and `resources/teammate_csv/mappings/` (D-030, Git-ignored).
