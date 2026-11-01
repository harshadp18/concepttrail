# Metadata enrichment sidecar (generated, Git-ignored)

Written by `python -m data_pipeline.run_extraction_pilot`, with source-URL evidence from `python -m data_pipeline.verify_source_urls`; the pilot CSV and triage files by the two builders named below. This sidecar is the authoritative **proposal** for `topic_title`, `learning_objective`, `source_url` and `acquired_at`. It never writes `data_pipeline/curriculum.csv`.

| File | Contents |
|---|---|
| `topic_mapping.csv` | Chapter, topic, subtopic and `heading_candidate` rows: verbatim `title`, `display_title` (control characters removed), `contains_control_characters`, kind, number, PDF page index, printed label, method, confidence |
| `learning_objective_mapping.csv` | Objectives with origin (`official_source`, `textbook_explicit`, `source_derived_candidate`, `human_approved`) and page references |
| `source_url_mapping.csv`, `source_url_evidence.json` | Official URL research, verified by exact SHA-256 match |
| `acquisition_date_evidence.json` | Every evidence type considered, and why it was accepted or rejected |
| `unified_enrichment.{json,csv}` | One record per document: the four values, their statuses, origins, evidence, confidence, review status, version, `processed_at` |
| `missing_value_report.{json,md}` | Status counts and the reason for every unresolved value |
| `human_review_queue.csv` | Prioritised review items: `ocr_required` (OCR not run), `ocr_low_confidence_or_empty`, `ocr_quality_review`, page review, title checks, each unresolved field |
| `curriculum_inventory.pilot_enriched.csv` | The 10 pilot rows in the exact canonical 29 columns, one row per PDF (`build_pilot_enriched_csv.py`, D-047). A value is written only when its class is `verified`, `source_explicit`, `ai_generated` (D-049) or `human_approved` and the cleaned cell was empty. Only `learning_objective` may hold several values (` \| `). Rights fields carry the overlays of D-034 and D-050; `extraction_status` follows D-051; `permitted_training` and `permission_reference` are never changed. |
| `curriculum_inventory.pilot_enriched.status.csv` | Per row and field: written or not, value class (`verified`, `source_explicit`, `ai_generated`, `human_approved`, `candidate`, `unresolved`, `authorization_overlay`, `rule_derived`), status, origin, candidate count and sidecar reference, evidence, reason |
| `curriculum_inventory.pilot_enriched.changes.csv` | Every cell that differs from the cleaned CSV, with original value, basis, and authorisation record + hash |
| `curriculum_inventory.pilot_enriched.manifest.json` | Input, sidecar and output hashes, pilot IDs, write rules, versions; `generated_at` kept apart from `content_digest` |
| `human_review_queue.baseline_2026-10-31.csv` | Write-once baseline (45 items) before the Phase 4 continuation; hash-pinned |
| `human_review_queue.triage.{csv,json}` | Baseline items as `resolved` / `open` / `owner_decision`, plus new items (`triage_review_queue.py`, D-048) |
| `provenance_manifest.json` | Input and output hashes, versions, authorisation records, stable `processed_at` |

**Value statuses:** `verified`, `source_explicit`, `source_derived_candidate`, `ai_generated`, `not_yet_extracted`, `not_found`, `unknown`, `not_applicable`, `requires_human_review`.

Placeholder strings such as `N/A`, `0`, `Unknown` or `TBD` are never written into value fields. Missing values stay empty, with an explicit status and reason.

## Review-state columns (D-054)

`learning_objective_mapping.csv` and `topic_mapping.csv` carry `review_completion` (`completed_owner_attested`, `pending`, `not_applicable`, or empty when not covered), `approval_outcome` (`not_individually_recorded`, `approved`, `rejected`, `revision_required`, or empty) and `validation_record`. `review_status` holds the combined current state (for example `teacher_reviewed_outcome_not_recorded`). The objective mapping also keeps `review_status_at_generation` (the original `pending_teacher_review`). **Completion is never approval.** `unified_enrichment.json` has matching `review_completion` and `approval_outcome` objects, and `curriculum_inventory.pilot_enriched.status.csv` has the same two columns.
