# `data_pipeline/data/` — local pipeline artifacts

## Directory meanings

- `raw/textbooks/`: immutable source PDF snapshots; private and Git-ignored. User drop-zone is `resources/textbook_pdfs/`.
- `raw/teammate_csv/`: byte-identical, hash-addressed snapshots of teammate CSVs from `resources/teammate_csv/incoming/`.
- `interim/extracted_json/`: raw page-level extractor/OCR output, diagnostics and page locators.
- `interim/csv_profiles/`: non-destructive CSV profiling outputs.
- `processed/textbook_json/`: cleaned and structured JSON, with content units and asset references.
- `processed/csv_cleaning/`: accepted and rejected teammate CSV records plus validation reports; never overwrite inputs.
- `overrides/`: explicit human corrections/annotations, recorded with reviewer and date; do not edit raw extraction in place.
- `logs/`: job/stage logs; do not log secrets or unnecessary student data. CSV cleaning manifests are under `logs/csv_cleaning/`.
- `final/`: validated derived CSV/JSON exports ready for database publishing; do not put files here solely because extraction completed.

## User hand-off workflow

1. Copy textbook PDFs into `resources/textbook_pdfs/` (optionally nested by class/subject/edition).
2. Copy teammate CSV exports into `resources/teammate_csv/incoming/`.
3. Leave original files untouched. Run profiling before cleaning.
4. Find immutable raw snapshots, profiles, accepted/rejected outputs and reports in their dedicated folders below.
5. Do not copy an accepted candidate over `data_pipeline/curriculum.csv`; only do that after the dataset is confirmed as the curriculum inventory, its fields are mapped to the exact 29-column header, and the owner approves the mapping.

## File naming

Include stable source ID and source version in filenames, for example `SRC-...__sha256-prefix__raw.json`. Never use a generic filename such as `class8_math.json` that is overwritten when the edition changes.

## Storage and rights

Do not commit PDFs, OCR corpora, copyrighted content or private student data. The Git ignore list is a safety net, not a rights policy. Back up approved artefacts according to the source licence and data-retention plan. Remove/withdraw indexed content when its permission expires or it is withdrawn.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Storage layout for private source PDFs, teammate CSV snapshots, profiling reports, cleaned/rejected CSV derivatives and generated pipeline artifacts.

### 2. Recent Updates Incorporated in This Module

Resource drop-zones are separate from immutable raw snapshots. Teammate CSV profiles, cleaned accepted rows, rejected rows, raw page extraction, processed JSON, human overrides, logs and final exports remain separate; raw material is private/ignored by Git.

### 3. File Manifest

`raw/textbooks/`, `raw/teammate_csv/`, `interim/csv_profiles/`, `interim/extracted_json/`, `processed/csv_cleaning/`, `processed/textbook_json/`, `overrides/`, `logs/csv_cleaning/`, `logs/`, `final/`.

### 4. Data Structures, Types & Schemas

File path identity includes source ID/class/subject/edition; JSON contains provenance, page locators, pipeline version, extraction/validation/review status.

### 5. File-by-File Implementation Specification

Never overwrite original PDF/CSV or raw extraction. Use new generation paths for CSV profiles, accepted/rejected rows, cleaned JSON and derived exports; include manifests and checksums; set restrictive file permissions.

### 6. Integration Points

Written by `data_pipeline/stages`; read by QC, publish and evaluation jobs.

### 7. Module Verification Checklist

Git ignore scan, path traversal tests, raw-vs-processed immutability test and artifact provenance check.
