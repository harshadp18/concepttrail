# Data acquisition, PDF extraction, JSON, CSV and validation specification

## 1. Master data design

One master file: `data_pipeline/curriculum.csv`. It holds the user's agreed columns for inventory, source, rights, edition, curriculum, chapter/topic/objective and processing statuses. Do not add `resources.csv` or `sources.yaml` as parallel masters.

The relational database is normalised when the CSV is imported: one row may resolve to a subject, curriculum version, curriculum item and source document records. The CSV remains a convenient human-reviewed inventory; PostgreSQL tables enforce relationships.

## 2. Required curriculum coverage

Create/track all 25 class-subject combinations: Classes 6–10 × the five agreed subjects. Each row should include academic session, course/language, actual source title, edition/revision and official URL. For Class 9/10 English/Hindi course variants, record the actual applicable course. Do not fabricate a chapter when a source is missing. A row with `not_found`, `needs_confirmation`, or rights hold remains in the coverage report.

## 3. Source discovery and use permissions

Start with official CBSE curriculum documents and official NCERT textbook resources where relevant. Record exact URL, retrieval date, publisher, edition, page count if available, local SHA-256 and permission evidence. Public access is not permission for all software operations. For every resource independently determine whether the intended use is permitted:

- local/internal extraction and processing;
- sending text/pages to an external LLM or embedding provider;
- storing text in a retrieval index;
- displaying source excerpts or generated notes in product;
- training/fine-tuning a model;
- redistribution/download by platform users.

If a permission is unknown, block that operation and keep the status `review_required`/`permission_required`. Do not bypass login, DRM, rate limits or website access controls. Use licensed, teacher-created or otherwise permitted alternatives when permission is not established.

## 4. Resource drop-zones and folder flow

User copies original textbook PDFs into `resources/textbook_pdfs/` and teammate CSV exports into `resources/teammate_csv/incoming/`. `resources/` is a file drop-zone, not an inventory. Original files stay unchanged. The pipeline snapshots inputs by SHA-256 and writes generated artifacts under `data_pipeline/data/`. See `docs/CSV_CLEANING_SPEC.md`.

```text
resources/
  textbook_pdfs/               # user copies source PDFs here
  teammate_csv/incoming/       # user copies teammate CSVs here
data_pipeline/
  curriculum.csv
  config.yaml
  schemas.py
  pipeline.py
  stages/
  prompts/
  data/
    raw/textbooks/<source_id>/<edition>/<filename>.pdf
    raw/teammate_csv/<dataset_slug>/<sha256>/<filename>.csv
    interim/csv_profiles/<dataset_slug>/<run_id>/
    processed/csv_cleaning/<dataset_slug>/<run_id>/accepted.csv
    processed/csv_cleaning/<dataset_slug>/<run_id>/rejected.csv
    logs/csv_cleaning/<dataset_slug>/<run_id>/
    interim/extracted_json/
    processed/textbook_json/
    overrides/
    logs/
    final/
```

## 5. Extraction strategy

### Text-native PDFs

Use PyMuPDF. Extract per page, preserve PDF page index, test reading order and detect pages with low text length. Save raw page text and diagnostics before cleaning.

### Scanned/image-only pages

Use Tesseract only on pages that need OCR, with an installed language pack for the actual script. Record OCR use and confidence/diagnostic status. OCR text is not automatically trusted.

### Tables, equations, diagrams, maps and layout

Ordinary text extraction may lose table structure, math notation, multi-column reading order, diagram labels and map semantics. Preserve asset references and page locations; inspect source page images and require subject-aware human review when uncertain. Use additional parsers/vision only when source permissions allow.

### Preserve

- source ID and original file hash;
- PDF page index and printed page label separately;
- chapter/section heading hierarchy;
- paragraph order and question numbering;
- formulas, superscripts/subscripts, units and mathematical signs;
- table title/headers/cells/units;
- figure/diagram/map identifiers and file paths;
- language/script metadata;
- extraction/cleaning tool and version.

## 6. JSON output contract

Example shape (illustrative; validate against the implementation schema):

```json
{
  "source_id": "SRC-EXAMPLE",
  "source_sha256": "...",
  "class_level": 7,
  "subject_id": "science",
  "course_or_language": "English",
  "academic_session": "2026-27",
  "pipeline_version": "extract-v1",
  "chapters": [{
    "chapter_code": "CH-01",
    "chapter_title": "Example chapter",
    "sections": [{
      "section_title": "Example section",
      "pages": [{
        "pdf_page_index": 12,
        "printed_page_label": "8",
        "text": "Extracted text...",
        "tables": [],
        "figures": [],
        "questions": [],
        "extraction_method": "pymupdf",
        "validation_status": "pending",
        "review_status": "pending"
      }]
    }]
  }]
}
```

This is a structure example, not verified textbook content. Raw extraction JSON is immutable; cleaned JSON is a new artifact.

## 7. Teammate CSV cleaning

Profile before cleaning; preserve the original file and header order; read IDs as strings; trim only outer whitespace by default; make null tokens field-specific; flag duplicates; preserve malformed/ambiguous rows in a rejected output; reconcile all rows; write reports/manifests with input/output hashes. Never auto-correct factual fields by guessing or asking an LLM. Cross-check against textbook PDFs only when source matching and local-processing permission are confirmed. Full implementation contract is `docs/CSV_CLEANING_SPEC.md`.

## 8. PDF/text cleaning rules

- Remove repeated headers/footers only when validated by page patterns and preserve reversibility.
- Fix broken line wraps without changing meaning; do not join real hyphenated terms blindly.
- Preserve Unicode scripts, diacritics and punctuation.
- Preserve mathematical minus signs, fractions, powers, units and symbols.
- Do not reorder tables/columns unless verified against the page.
- Keep duplicates across different source editions/provenance; exact duplicate detection is a flag, not an automatic delete command.
- Every transformation is logged with source/page/stage/version and preferably before/after hash or diff.

## 9. Automated quality checks

Measure actual values, do not prefill success scores:

- page coverage = pages with extracted content / PDF total pages;
- metadata completeness = records with required provenance / records expected;
- citation resolvability = emitted citations that resolve to existing source/page records / citations emitted;
- duplicate normalized chunk rate;
- OCR proportion and human correction rate;
- equation/table/figure/map inspection results by subject;
- required inventory coverage by class/subject/chapter;
- count of records blocked by rights or missing metadata;
- failed/review-needed page counts.

For a first pilot, inspect every page of small sample documents when practical and include at least one Mathematics example plus a non-Maths document that tests a different structure (prose/table/timeline/map/language). This validates a pipeline, not full subject coverage.

## 10. Derived CSV generation

Draft outputs from reviewed curriculum/content:

- `kc_components.csv`: stable KC key, name/description, subject, skill type, objectives, misconception data, source references and review status.
- `prerequisites.csv`: prerequisite KC key, dependent KC key, reason, strength, evidence/source and review status.
- `questions.csv`: question ID, type, stem, expected answer, rubric, difficulty, misconception tags, KC mapping, source refs, verification and review state.
- `notes.csv`: proposed fourth output for learning note drafts/metadata; exact schema must be confirmed by product owner.

Do not create prerequisite edges from chapter order alone. Do not publish generated questions simply because JSON parses. Maths can use deterministic calculation checks; subjective writing, literature, maps and interpretations need reviewed rubrics/teacher review.

## 11. Chunking and embeddings

Chunk at meaningful boundaries (paragraph/section/question/solution/table). Do not split equations or a question from its answer/explanation. Initial chunk size/overlap is an experiment, not a universal constant. Store source and page provenance through the content unit and chunk relation. Embeddings require a separate chosen model; record model ID, exact revision, dimensions and normalization. The existing `embedding_chunk` schema must remain exactly as in the ERD unless the owner approves a migration.

## 12. Publishing

Only publish records after rights, structural validation, academic review, provenance and schema checks pass. Use transaction/upsert with stable IDs and generation/version fields. A failed source should remain visible in coverage reporting. Index build should be versioned and reversible.
