# Instructions for `data_pipeline/`

- `curriculum.csv` is the only master curriculum/source inventory. Never create `resources.csv` or `sources.yaml` as parallel masters.
- Preserve its exact 29-column header and order, including string `subject_id`.
- The user copies source PDFs into `resources/textbook_pdfs/` and teammate CSVs into `resources/teammate_csv/incoming/`. Read the respective resource READMEs and `docs/CSV_CLEANING_SPEC.md` before processing.
- Teammate CSV cleaning is mandatory: profile first, preserve original bytes, create SHA-256 snapshots, apply only documented transformations, write accepted/rejected rows separately, and create a reconciled quality report.
- Do not assume teammate CSV purpose or field semantics. Never map it into `curriculum.csv` until the owner confirms its purpose and reviews all field mappings.
- Preserve all input columns/order unless a field mapping is approved. Keep IDs as strings. Do not fabricate or auto-correct facts.
- Cross-check CSV values against textbook PDFs only after source matching and local-processing permission are confirmed. Unknown/denied rights block PDF extraction/OCR; external model processing is separately gated.
- Raw PDFs and raw extraction JSON are immutable. Cleaned artifacts are written separately.
- Maintain 25 rows/groups for the five agreed subjects across Classes 6–10; track missing/unavailable entries rather than dropping them.
- Do not download, extract, send to an external model, embed, index, display or train on a source unless its per-purpose rights gate permits that action.
- Preserve PDF page index, printed page label, source ID/hash, edition, language, chapter boundaries, formulae, tables, maps, figures and question numbering.
- OCR output is untrusted until checked; route uncertain pages to human review.
- Derived CSVs must be deterministic/versioned and are never masters.
- AI-generated KC mappings, prerequisite edges, questions and notes are drafts until validation/review gates pass.
- Do not silently delete apparent duplicates across different sources; preserve provenance.
