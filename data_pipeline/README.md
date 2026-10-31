# `data_pipeline/` — one master curriculum inventory and source-content pipeline

## Core decision

Maintain exactly one master CSV: **`curriculum.csv`**. Do not create `resources.csv` or `sources.yaml` as a competing source inventory. `config.yaml` is permitted for processing configuration only; it must not duplicate source metadata.

## Agreed CSV columns

```text
inventory_id,class_level,board,academic_session,subject_id,course_or_language,item_type,chapter_or_unit_code,chapter_title,topic_title,learning_objective,resource_title,source_id,source_url,publication_or_revision,rights_status,permitted_processing,permitted_indexing,permitted_training,permitted_display,permission_reference,acquired_at,sha256,extraction_status,validation_status,review_status,index_status,last_verified_at,notes
```

Keep the exact 29 column names and order stable. The current SQL schema uses string `subject_id`; keep CSV subject codes aligned with the current schema until an explicit migration changes them. Any added column needs owner approval and a documented schema version.

## Product coverage

Represent all 25 initial class-subject combinations: five classes (6–10) crossed with English, Hindi, Mathematics, Science and Social Science. Use actual course/language labels from the verified source. Class 9/10 language course variants must be checked. A row with unavailable/unclear source remains in the inventory with status/notes; never omit it from coverage denominator.

## Derived output files

- `final/kc_components.csv`
- `final/prerequisites.csv`
- `final/questions.csv`
- `final/notes.csv` (proposed fourth output name; confirm before freezing)

These are generated artifacts and should be reproducible. The pipeline may also generate mapping/intermediate exports needed to load `content_unit_kcs` and `kc_curriculum_map`. They are not master inventory files.

## User drop-zones and teammate CSV cleaning

The user copies files into these top-level drop-zones:

- Textbook PDFs: `resources/textbook_pdfs/`
- Teammate CSV exports: `resources/teammate_csv/incoming/`

Do not edit, rename, delete or overwrite originals. Read `docs/CSV_CLEANING_SPEC.md` before processing teammate CSVs. The required sequence is profile → deterministic clean → schema/domain validation → optional PDF evidence cross-check (only when permitted) → human review → approved mapping/import. The teammate CSV is an input dataset, not automatically the master curriculum inventory. Preserve its schema and columns by default. Keep exact original and hash-addressed snapshot, accepted rows, rejected rows, quality report and run manifest. Do not write accepted rows into `curriculum.csv` until the dataset purpose and field mapping have been confirmed and approved.

## Pipeline stages

1. Discover teammate CSV input(s); compute file metadata and SHA-256; create a byte-for-byte raw snapshot before profiling so a changing drop-zone file cannot alter the run.
2. Profile the immutable CSV snapshot and report headers, encoding, delimiter, row counts, missingness, duplicates, inferred types and anomalies without changing the file.
3. Clean only through documented, deterministic and reversible rules; preserve original headers/column order and do not fabricate values.
4. Validate rows against an explicitly selected dataset schema; retain rejected rows and reason codes.
5. Where a CSV is intended as curriculum inventory, map it to the agreed canonical header with an explicit reviewed mapping; never assume the teammate's schema matches.
6. Resolve PDF-to-CSV source pairing and apply the rights gate before reading PDF content. Each intended action (internal extraction, external-model processing, indexing, training, display, redistribution) must be permitted. If unknown, block that action.
7. Cross-check CSV values with matching textbook PDFs only when local-processing rights are confirmed; record source ID, PDF hash and page evidence. Conflicts go to human review, never auto-correction.
8. Validate `curriculum.csv`: exactly 29 fields in order, required values, classes 6–10, agreed subjects, IDs, duplicate rows, valid dates/status values.
9. Acquire approved PDFs/files: record source ID, actual file hash, acquisition timestamp and exact edition/revision; do not replace source files silently.
10. Extract: PyMuPDF for text-native PDFs; OCR with Tesseract only for low-text/scanned pages after permission checks. Preserve PDF page index and printed page label separately.
11. Clean: reversible, logged transformations; keep raw text unchanged. Avoid deleting legitimate repeated content across different sources.
12. Structure: chapter/section/paragraph/question/example/table/figure/map JSON with source/page references and asset paths.
13. Validate: page coverage, reading order, equations, question numbering, tables, diagrams/maps, language script, metadata and rights state.
14. Human review: required for OCR uncertainty, formulas, diagrams, maps, open-ended language content and generated curriculum/KC/prerequisite records.
15. Generate draft KCs, prerequisite edges, notes and questions using structured prompts and Pydantic schemas; use only permitted source context.
16. Verify: deterministic answer check where possible, source alignment, uniqueness of MCQ answer, graph cycle checks, human review.
17. Chunk and embed only approved content whose indexing and embedding-provider processing are permitted.
18. Publish using idempotent import/upsert and a release/version identifier; never overwrite approved content silently.
19. Generate coverage report showing discovered/acquired/extracted/cleaned/validated/reviewed/indexed/published states for every inventory record.

## Required JSON provenance

Every extraction JSON document must include source ID, source hash, class, subject, course/language, academic session/curriculum version, extraction pipeline version, page-level records, printed-page label when known, chapter/section structure, content types, asset references, extraction status, validation status and review status. Keep PDF page index distinct from printed page number.

## Idempotency

Cache each stage by input hash + pipeline stage version + configuration hash. A rerun with identical inputs should not create duplicate records. A changed PDF or stage config creates a new output version and does not erase human approvals.

See `stages/README.md`, `prompts/README.md`, and `data/README.md`.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Offline, versioned, rights-gated curriculum ingestion for all five agreed subjects in Classes 6–10.

### 2. Recent Updates Incorporated in This Module

Exactly one 29-column master CSV; teammate CSVs are profiled/cleaned as incoming datasets and mapped only after review; textbook PDFs are copied into a separate resource drop-zone; PDF/raw JSON/clean JSON/overrides/derived exports are separate; pilot requires Maths and non-Maths sample; no protected source content is processed without use-specific rights.

### 3. File Manifest

`curriculum.csv` master; `config.yaml` processing settings; `resources/` user file drop-zones; `docs/CSV_CLEANING_SPEC.md` cleaning contract; `stages/profile_csv.py`, `clean_csv.py`, `validate_csv.py` and `compare_csv_to_pdfs.py` for teammate data QA; remaining stage modules for extraction/content generation; `data/` immutable raw/interim/processed/override/log/final artifacts.

### 4. Data Structures, Types & Schemas

Preserve the exact 29-column CSV header in order. Derived outputs: `kc_components.csv`, `prerequisites.csv`, `questions.csv`, and proposed `notes.csv`. Stable source IDs and SHA-256 hashes required.

### 5. File-by-File Implementation Specification

Inventory validation -> rights check -> acquisition -> PyMuPDF extraction -> selective OCR -> cleaning -> structure JSON -> QC/human review -> KCs/edges/questions/notes -> chunk/embed -> publish; each stage idempotent and resumable.

### 6. Integration Points

Imports shared Pydantic schemas; publishes approved records to PostgreSQL; evaluation consumes benchmark exports.

### 7. Module Verification Checklist

Run pipeline twice; second run reuses valid outputs; verify original CSV/PDF hashes unchanged; every input CSV row is accepted, rejected or explicitly excluded with a reason; inspect PDF page coverage, permissions, subject-neutral structure and human override persistence.

## Teammate inventory cleaning (implemented 2026-10-31)

**Command** (from the repository root, with the virtual environment active):

```bash
python -m data_pipeline.clean_teammate_csv                # every *.csv under resources/teammate_csv/incoming/
python -m data_pipeline.clean_teammate_csv --dry-run      # compute and report; write nothing
python -m data_pipeline.clean_teammate_csv --profile-only # snapshot + profile only
python -m data_pipeline.clean_teammate_csv --force        # replace outputs produced from a different input/rules/config
python -m data_pipeline.stages.profile_csv --input <file.csv>   # read-only profile to stdout
```

Options: `--file`, `--input-dir`, `--pdf-root`, `--output-root`, `--snapshot-root`, `--master`, `--config`.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | success (rows may still be rejected or quarantined; see the reports) |
| 2 | unreadable input (encoding or CSV structure) |
| 3 | field mapping required |
| 4 | refused to overwrite another run's outputs |
| 5 | an original changed during the run, or reconciliation failed |
| 6 | `config.yaml` asks for unsupported behaviour |
| 7 | no input found |

### Modules

| File | Responsibility |
|---|---|
| `inventory_schema.py` | `CANONICAL_HEADER` (29 columns), field policies, closed vocabularies, ID/date/URL formats, permission categories, `RULES_VERSION` |
| `stages/profile_csv.py` | Byte-level read: UTF-8 with/without BOM only, delimiter and line-ending detection, strict `csv` parsing with every value as `str`; diagnostic profile |
| `stages/clean_csv.py` | The only value transformations; text findings |
| `stages/validate_csv.py` | Issue catalogue, field rules, PDF integrity, duplicate analysis, coverage, dispositions |
| `clean_teammate_csv.py` | Orchestration, outputs, manifests, merge proposal |

### Schemas

- **Incoming:** profiled, never presumed. The current teammate file `curriculum_inventory.csv` already uses the exact canonical header.
- **A non-canonical header:** every row is quarantined with `SCHEMA_MAPPING_REQUIRED` and kept verbatim in `__raw_record_json`. The field-mapping report lists missing and unexpected columns, and the run exits 3. Mappings are never guessed.
- **Canonical:** the exact 29-column header of `data_pipeline/curriculum.csv`.
  - Required fields: identifiers, scope, titles, rights, statuses, `sha256`, and `notes` (which carries `local_path:`).
  - Optional fields: `topic_title`, `learning_objective`, `source_url`, `publication_or_revision`, `permission_reference`, `acquired_at`, `last_verified_at`. These may be empty; they are reported, never filled.

### Cleaning rules (the only changes made to values)

1. `TRIM_OUTER_WHITESPACE` removes leading and trailing whitespace. A whitespace-only cell becomes empty.
2. `NORMALIZE_LINE_ENDINGS` turns in-cell CRLF/CR into LF.

**Never changed:** capitalisation, internal spacing, Unicode normalisation form, null-like tokens (`NA`, `-`, …), identifiers or leading zeros. NFC is deliberately not applied because it rewrites composition-excluded Devanagari (nukta letters).

**Output encoding:** UTF-8 without BOM, LF line endings, minimal quoting.

**Logging:** every transformation is written to `decisions.jsonl` with before/after SHA-256 and lengths.

### Validation, rejection and quarantine

A row is **rejected** if any reject issue applies, otherwise **quarantined** if any quarantine issue applies, otherwise **accepted**. Codes, severities and suggested actions are defined in `ISSUE_CATALOG` in `stages/validate_csv.py`.

**Rejected** (a documented failure; cannot enter the inventory as-is):
- **Structure and required fields:** wrong row width, a missing required field.
- **Values outside the agreed set:** class not in 6–10 (leading zeros are rejected), unknown `subject_id`, malformed academic session.
- **Malformed formats:** `inventory_id`, `source_id` or `sha256`; URL; non-ISO date.
- **PDF integrity:** missing/unsafe/absent/unreadable PDF path, non-`.pdf` extension, missing `%PDF-` signature, SHA-256 mismatch.

**Quarantined** (needs a human decision; never merged or fixed automatically):
- **Field mapping:** a non-canonical header.
- **Scope and vocabulary:** board out of scope, an unknown vocabulary value, `item_type` that disagrees with `chapter_or_unit_code`.
- **Identifier mismatch:** the class or subject inside an ID disagrees with the row's fields.
- **Annotations and flags:** reviewer annotations inside factual fields; teammate `validation_status` of `needs_review` or `failed`.
- **Text problems:** control characters, suspected mis-decoded text.
- **Duplicates and conflicts:** extra copies of exact duplicate rows (the first copy stays eligible), duplicate `inventory_id`/`source_id` with conflicting content, the same recorded SHA-256 on several rows (including under different source IDs or with different permissions), different files with identical bytes, the same PDF path on several rows.

**Warnings** (accepted, but reported): missing optional metadata, rights not granted, irregular filename, non-NFC text, null-like tokens, possible near-duplicates.

PDF checks read bytes only (SHA-256 and the 5-byte signature). Paths come from the teammate convention `local_path: <path relative to resources/textbook_pdfs/>` in `notes`. They must stay inside the drop-zone; absolute paths, `..`, backslashes and escaping symlinks are rejected.

### Rights

- Permission values are `permitted`, `not_permitted` and `permission_required`; only `permitted` (with `rights_status=approved`) opens a gate.
- `external_model_processing` and `redistribution` have no column in the 29-column inventory, so they stay unauthorised.
- The pipeline never edits permission fields.
- The owner's hackathon-use assertion (`docs/DECISIONS.md` D-031) is recorded in the manifest and the merge proposal, but it is not applied to any field.

### Outputs, idempotency and reconciliation

- **Locations** (D-030): outputs go under `resources/teammate_csv/processed/{cleaned,rejected,reports,manifests}/` and `resources/teammate_csv/mappings/` (see their READMEs). The immutable snapshot is `data_pipeline/data/raw/teammate_csv/<stem>/<sha256>/`, read-only. All are Git-ignored.
- **Idempotency:** the run ID is derived from the input SHA-256, pipeline version, rules version, rule-source hash and config hash. Re-running identical inputs produces byte-identical outputs; only `generated_at_utc` and `snapshot.reused_existing` differ in the manifest. Outputs from a different run ID are only replaced with `--force`.
- **Manifest contents:** input and master SHA-256 before and after (the run fails if either changed), versions, config, reconciliation, and the SHA-256 of every output.
- **Reconciliation:** `input rows = accepted + rejected + quarantined` must balance or the run fails. `reconciliation.csv` lists every input row with its disposition and codes.

### Reprocessing and human review

1. Never edit the original or the outputs. Fix the source export (a new file name or new bytes) or change an approved rule (bump `RULES_VERSION`), then re-run with `--force`.
2. Review `processed/rejected/<stem>.quarantined.csv` and `processed/reports/<stem>.reviewer_notes.csv`. A reviewer-note report gives `candidate_value_if_annotation_removed` with `applied=false`; applying it requires owner approval and an override record with provenance (`data_pipeline/data/overrides/csv_cleaning/README.md`).
3. Read `mappings/<stem>.merge_proposal.md`. `data_pipeline/curriculum.csv` is changed only after explicit owner approval, never by this pipeline.

Tests: `tests/unit/test_csv_profiling.py`, `test_csv_cleaning.py`, `test_csv_validation.py` and `tests/integration/test_teammate_csv_pipeline.py`. The opt-in `-m real_inventory` test reruns the real 386-row inventory with outputs in a temporary directory.

## PDF extraction pilot and metadata enrichment (Phase 4, implemented 2026-10-31)

Commands, in order (repository root, virtual environment active):

```bash
python -m data_pipeline.authorization record-owner-local-processing   # write-once rights overlay (D-034)
python -m data_pipeline.authorization record-owner-project-use        # owner project-use rights (D-050)
python -m data_pipeline.select_pilot                                  # numeric signals -> 10 pilot slots
python -m data_pipeline.verify_source_urls                            # optional; official-site research (network)
python -m data_pipeline.run_extraction_pilot                          # extract, classify, OCR, normalise, enrich
python -m data_pipeline.hindi_diagnostics                             # Hindi duplicate-glyph evidence (D-044; changes no text)
python -m data_pipeline.build_pilot_enriched_csv                      # derived 29-column pilot CSV (D-047)
python -m data_pipeline.triage_review_queue                           # baseline queue -> resolved/open/owner_decision (D-048)
python -m data_pipeline.inspection_pack                               # rendered pages + text for human review
```

OCR is enabled (`config.yaml` `ocr.enabled: true`, languages `eng`, `hin`; D-043). It needs local Tesseract with the `eng` and `hin` packs (`brew install tesseract tesseract-lang`). Changing `config.yaml` changes the Phase 3 `run_id`, so re-running Phase 3 cleaning needs `--force`.

### Modules

| File | Responsibility |
|---|---|
| `authorization.py` | Write-once, purpose-specific authorisation records; `check_use(source_id, sha256, use)` gate |
| `select_pilot.py` | Numeric signals for every eligible accepted chapter PDF (no text kept); deterministic slot selection |
| `stages/extract_pdf.py` | PyMuPDF raw extraction, page by page (details below) |
| `stages/classify_pages.py` | Documented thresholds deciding `text_native`, `mixed_text_image`, `image_heavy`, `scanned`, `low_quality_extraction`, `empty_or_non_text`, `extraction_failed`, and which pages are OCR candidates |
| `stages/ocr_pages.py` | Local Tesseract only: detection, language selection (Hindi needs `hin`; never English as a substitute), TSV confidence, native-vs-OCR comparison. OCR text is stored separately and never replaces native text. |
| `stages/clean_text.py` | Normalisation into a new artifact that points back to its raw page (details below) |
| `stages/structure_content.py` | Chapter/topic/subtopic hierarchy from heading candidates (verbatim titles; automatic classification only); inventory chapter-title check |
| `stages/validate_content.py` | Per-subject quality metrics and findings (no text reported) |
| `enrich_metadata.py` | `topic_title`, `learning_objective`, `source_url`, `acquired_at` proposals with explicit statuses |
| `verify_source_urls.py` | NCERT URL rule from the official `textbook.php` script, plus SHA-256 match of the downloaded bytes |
| `run_extraction_pilot.py` | Orchestration, write-once artifacts, enrichment sidecar, manifests |
| `official_outcomes.py` | Verbatim official chapter learning outcomes from CBSE curriculum PDFs into `data/overrides/metadata_enrichment/official_learning_outcomes.json` (`python -m data_pipeline.official_outcomes`) |
| `inspection_pack.py` | Renders representative pages, every OCR page, the most-affected virama pages and best/worst OCR examples next to raw, markup, normalised and OCR text; writes `decisions.md` |
| `stages/repair_devanagari.py` | D-044 same-glyph Devanagari repair for approved source IDs: a repaired copy of the raw blocks for normalisation, a per-correction log, review flags for residue (never auto-corrected) |
| `hindi_diagnostics.py` | Glyph-level diagnosis of doubled Devanagari code points; D-040 and D-044 previews with OCR agreement and before/after word pairs; never changes pipeline text |
| `build_pilot_enriched_csv.py` | Derived 29-column CSV of the 10 pilot rows from the hash-verified cleaned CSV, plus status, changes and manifest sidecars |
| `triage_review_queue.py` | Rule-based triage of the hash-pinned 45-item baseline review queue |

`stages/extract_pdf.py` keeps, for every page:
- the zero-based page index and the printed page label (from PDF label rules, or a margin-number heuristic);
- the raw text, text blocks with bounding boxes, and character statistics;
- heading, caption and list candidates;
- images with bounding boxes and coverage, and tables with rows and columns;
- fonts, with legacy-Devanagari font detection;
- `script_markup_text`, which writes superscripts and subscripts as `^{..}` / `_{..}`. Plain PDF text flattens `x²` to `x2`.

`stages/clean_text.py` removes running headers and footers, rebuilds prose paragraphs, and preserves maths, table regions and Unicode exactly. Legacy-encoded Hindi is flagged as unusable rather than altered.

### Rules

- **Rights gate:** extraction, OCR, normalisation and quality evaluation each check `check_use()`. Only the 383 accepted documents, with matching SHA-256, are covered. External AI, external OCR or embeddings, display, redistribution and training are never authorised by this overlay.
- **No external processing:** no model or provider API is called and no page is uploaded. The only network use is `verify_source_urls.py`, which downloads public NCERT files to hash them in memory.
- **Provenance:** every raw page carries `source_id`, the PDF path, its SHA-256, the page index, the printed label, the extraction method, `extracted_at`, the pipeline version and the review status. Every normalised page carries `raw_ref` (the raw artifact, page index and raw-text SHA-256).
- **Write-once and idempotent:** artifact names include the PDF hash and a cache key derived from the versions, thresholds and OCR environment. A rerun reuses the files, and enrichment keeps a stable `processed_at`, so unchanged inputs give byte-identical outputs.
- **Enrichment never fills the master:** proposals live in `data/processed/metadata_enrichment/`. In the derived pilot CSV a value appears only when it is a single `verified`, `source_explicit` or `human_approved` value and the cleaned cell is empty. Derived objectives remain candidates, and several topics stay in `topic_mapping.csv` (one canonical row per PDF).
- **Hindi repair (D-044):** only for `devanagari_repair.source_ids` in `config.yaml`. Raw text never changes; normalised text records `devanagari_repair` per page, with the flagged residue.
- **Objectives:** official > self-contained textbook statement > owner-approved AI-generated (grounded in chapter text, `pending_teacher_review`, D-049) > derived candidate.
- **Topics:** only numbered headings become topics. Large unnumbered type, prose fragments and out-of-sequence numbered lines are `heading_candidate` only (D-045).
- **Acquisition dates are never inferred:** file times, macOS quarantine (transfer) timestamps, PDF production dates and pipeline dates are rejected as acquisition evidence.

Tests:
- unit: `tests/unit/test_pdf_extraction.py`, `test_ocr_and_normalization.py`, `test_authorization_and_enrichment.py`, `test_hindi_diagnostics.py`, `test_pilot_enriched_csv.py`, `test_review_triage.py`, `test_inspection_pack.py`, `test_devanagari_repair.py`, `test_quality_review_records.py`;
- integration: `tests/integration/test_extraction_pilot.py`.

All tests use synthetic PDFs only.
