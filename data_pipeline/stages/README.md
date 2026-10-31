# `data_pipeline/stages/` — deterministic CSV and curriculum pipeline stages

## Module purpose and boundary

Implements offline, resumable and testable stages. This directory does not own student-facing HTTP routes or UI code. Functions must be deterministic where their inputs/configuration are fixed; all writes are atomic and versioned.

## Required CSV-cleaning stages (run before curriculum mapping)

| File | Function contract | Input | Output | Acceptance gate |
|---|---|---|---|---|
| `profile_csv.py` | `profile_csv(input_path: Path, output_dir: Path, options: CsvProfileOptions) -> CsvProfileResult` | Original CSV in `resources/teammate_csv/incoming/` | `profile.json`, `profile.md`, immutable input hash metadata | Header/encoding/delimiter and row counts accounted for; potentially sensitive samples redacted |
| `clean_csv.py` | `clean_csv(input_path: Path, output_dir: Path, rules: CsvCleaningRules) -> CsvCleaningResult` | Original CSV plus explicitly approved rules | `accepted.csv`, `rejected.csv`, `cleaning_manifest.json` | Transformations deterministic, reversible/auditable; no fabricated values |
| `validate_csv.py` | `validate_csv(input_path: Path, schema_id: str, output_dir: Path, mapping: CsvFieldMapping | None) -> CsvValidationResult` | Accepted CSV and an explicitly chosen schema | validated accepted file, rejected rows/reasons, validation report | Every accepted row satisfies selected schema and domain constraints |
| `compare_csv_to_pdfs.py` | `compare_csv_to_pdfs(csv_path: Path, pdf_paths: Sequence[Path], mapping: EvidenceMapping, rights: ProcessingPermission) -> PdfCrossCheckResult` | Validated candidate CSV and user-supplied PDFs | evidence report with PDF page locators and unresolved conflicts | Runs only when local processing is permitted; no model call by default |

`CsvFieldMapping` and `EvidenceMapping` are explicit configuration records created only after profiling. Do not create them by guessing from column names.

## CSV cleaning invariants

1. Never modify files in `resources/`; never overwrite a teammate's original CSV or textbook PDF.
2. Create a byte-for-byte snapshot under `data_pipeline/data/raw/teammate_csv/<dataset_slug>/<sha256>/`.
3. Preserve original column names and order by default. If a canonical mapping is approved, store the mapping and retain the original header in the run manifest.
4. Read identifiers and general text as strings initially; do not strip leading zeros by numeric coercion.
5. Trim only outer whitespace by default. Preserve internal whitespace, Unicode, Hindi/other scripts, mathematical symbols, punctuation and meaningful text.
6. Treat missing-value tokens as field-specific configuration; do not automatically turn legitimate values such as `NA`, `-`, `0` or empty-looking symbols into nulls without an explicit rule.
7. Exact duplicate rows may be flagged and routed according to an approved policy. Near-duplicates are review flags, not automatic deletions. Do not merge records with different provenance.
8. Do not auto-correct factual textbook content, names, dates, numbers, formulas, answer keys, class, subject, chapter, page or source identifiers. Flag and quarantine discrepancies.
9. Preserve each rejected row with original values and stable logical row number plus machine-readable rejection codes.
10. Every input row must reconcile as accepted, rejected or explicitly excluded with a reason.
11. Running the same input hash, mapping and rules version twice must produce identical content outputs.
12. PDF text/OCR cross-checks are local-only by default and are blocked unless `permitted_processing=true` and the source rights record allows that operation. Unknown rights means no extraction/OCR.

## Implementation status (2026-10-31)

- Phase 4: `extract_pdf.py`, `classify_pages.py`, `ocr_pages.py`, `clean_text.py`, `structure_content.py` and `validate_content.py` are implemented and tested, orchestrated by `data_pipeline/run_extraction_pilot.py` (pilot only, not the full corpus). See `data_pipeline/README.md`, "PDF extraction pilot and metadata enrichment".

- `profile_csv.py`, `clean_csv.py` and `validate_csv.py` are implemented and tested, orchestrated by `data_pipeline/clean_teammate_csv.py`.
- The signatures differ from the original contract table: reading and profiling are `read_csv(path)` and `profile_csv(parsed)`; cleaning is `clean_row(header, values)`; validation is `validate_fields`, `check_pdf`, `duplicate_analysis` and `coverage_report`.
- `compare_csv_to_pdfs.py` is **not implemented**: PDF content cross-checks are blocked because every source records `permitted_processing=permission_required`.
- The output paths below are superseded by D-030; see `data_pipeline/README.md`, "Teammate inventory cleaning".

## Output paths

- Raw CSV snapshot: `data_pipeline/data/raw/teammate_csv/<dataset_slug>/<sha256>/<original_filename>.csv`
- Profile: `data_pipeline/data/interim/csv_profiles/<dataset_slug>/<run_id>/profile.json` and `profile.md`
- Cleaned/validated output: `data_pipeline/data/processed/csv_cleaning/<dataset_slug>/<run_id>/accepted.csv`
- Rejected rows: `data_pipeline/data/processed/csv_cleaning/<dataset_slug>/<run_id>/rejected.csv`
- Validation report: `data_pipeline/data/processed/csv_cleaning/<dataset_slug>/<run_id>/validation_report.json`
- Audit: `data_pipeline/data/logs/csv_cleaning/<dataset_slug>/<run_id>/cleaning_manifest.json` and `events.jsonl`

The standard clean output retains source headers/column order. The rejected output appends `__source_row_number` and `__rejection_codes`; the original raw snapshot remains unchanged. If a teammate CSV is intended to become `curriculum.csv`, map it to the exact 29-column canonical header only after an explicit field-by-field review. Do not automatically replace the header-only canonical file.

## PDF/content pipeline stages

| Stage | Module | Input → output | Gate |
|---|---|---|---|
| Inventory | `validate_inventory.py` | `curriculum.csv` → validation/coverage report | Exact 29 columns, 25 combinations, IDs and rights fields |
| Acquisition | `acquire_sources.py` | Rights-approved source records → immutable raw files/hash manifest | Purpose-specific permission and hash recorded |
| Extraction | `extract_pdf.py` | Approved PDF → raw page JSON | All pages accounted for; page index separate from printed label |
| OCR | `ocr_pages.py` | Flagged low-text pages → OCR JSON | Only selected pages; language and review state recorded |
| Text clean | `clean_text.py` | Raw extracted text → cleaned derivative | Raw unchanged; reversible transforms |
| Structure | `structure_content.py` | Clean pages → chapter/section/content-unit JSON | Boundaries/page locators valid |
| Content QC | `validate_content.py` | Structured JSON → QC/quarantine | Equations/assets/metadata/page coverage checked |
| KCs | `generate_kcs.py` | Reviewed content → KC drafts | Schema, provenance and human review |
| Graph | `generate_prerequisites.py` | Candidate KCs → edge drafts | Valid endpoints, no cycles, pedagogical review |
| Notes/questions | `generate_notes.py`, `generate_questions.py` | Approved content → draft exports | Typed schemas, answer validation and review |
| Publish | `verify_outputs.py`, `publish.py` | Approved exports → PostgreSQL/index generation | Rights, quality and idempotency |
| Coverage | `coverage_report.py` | Inventory/jobs → coverage report | Every denominator row represented |

## Dependencies and file manifest

Use Python standard library `csv`, `hashlib`, `json`, `pathlib`, `uuid`, `datetime` and `statistics` for CSV work. Use Pydantic v2 for explicit options/results/domain schemas. Use PyMuPDF for permitted PDF cross-check/extraction. Do not add a CSV-cleaning dependency solely for convenience. If pandas is used later, force string-preserving reads and prove no leading-zero/Unicode loss in tests.

| File | Purpose | Exports | Dependencies |
|---|---|---|---|
| `profile_csv.py` | CSV structure/data-quality profile | `CsvProfileOptions`, `CsvProfileResult`, `profile_csv` | stdlib |
| `clean_csv.py` | Apply configured reversible transformations | `CsvCleaningRules`, `CsvCleaningResult`, `clean_csv` | stdlib; shared schemas |
| `validate_csv.py` | Schema/domain checks and rejected-row output | `CsvFieldMapping`, `CsvValidationResult`, `validate_csv` | Pydantic/shared schemas |
| `compare_csv_to_pdfs.py` | Local evidence cross-check against PDF page content | `EvidenceMapping`, `PdfCrossCheckResult`, `compare_csv_to_pdfs` | PyMuPDF; rights gate |
| `validate_inventory.py` | Canonical master inventory validation | validator and CLI | CSV schema |
| `extract_pdf.py`, `ocr_pages.py`, `clean_text.py`, `structure_content.py`, `validate_content.py` | PDF-to-structured JSON | stage functions and CLIs | PyMuPDF; optional Tesseract |
| `generate_kcs.py`, `generate_prerequisites.py`, `generate_notes.py`, `generate_questions.py` | Draft knowledge and assessment artifacts | stage functions and CLIs | approved provider adapter, Pydantic |
| `verify_outputs.py`, `publish.py`, `coverage_report.py` | quality, import and coverage | stage functions and CLIs | app services/repositories |
| `__init__.py` | Python package marker | package | none |

## Error handling

Malformed quoting, inconsistent column counts, undecodable text, ambiguous delimiters, missing required headers, invalid types, unsupported formulas, orphan references, unavailable PDF evidence and rights blocks must produce explicit report codes. Do not silently skip malformed rows. If the parser cannot safely read the file, preserve the input and report the offending logical/physical row.

## Integration points

Resource intake files are read from `resources/`. Immutable snapshots and processing artifacts are written under `data_pipeline/data/`. Only owner-approved canonical mappings can populate `data_pipeline/curriculum.csv`; only validated/reviewed outputs can enter controlled PostgreSQL import services.

## Verification checklist

- UTF-8 BOM, UTF-8 Hindi, punctuation, mathematical signs, quoted delimiters and quoted newlines survive round-trip.
- Leading-zero IDs remain strings.
- Empty values, literal `NA`, dash and zero follow configured per-column rules.
- Exact duplicates and near-duplicates follow their separate policies.
- All input rows reconcile to accepted/rejected/excluded counts.
- Invalid rows retain originals and reason codes.
- Source files and raw snapshots are byte-identical after pipeline execution.
- Rights-denied/unknown PDFs are not extracted or OCR'd.
- CSV-vs-PDF disagreements include page evidence and are not auto-corrected.
- Second run with same inputs/config produces identical output hashes.
- Canonical inventory output has exactly 29 columns in the approved order.

## CLI contract

Once implemented, expose deterministic commands equivalent to:

```powershell
python -m data_pipeline.stages.profile_csv --input resources/teammate_csv/incoming/<file>.csv
python -m data_pipeline.stages.clean_csv --input resources/teammate_csv/incoming/<file>.csv --rules <approved-rules.yaml>
python -m data_pipeline.stages.validate_csv --input <accepted.csv> --schema <reviewed-schema-id>
python -m data_pipeline.stages.compare_csv_to_pdfs --csv <validated.csv> --pdf-root resources/textbook_pdfs --rights-manifest data_pipeline/curriculum.csv
```

The CLI must validate paths are within approved roots, print output locations and summary counts, and return non-zero on blocking validation errors. Never accept arbitrary shell commands from CSV cells.
