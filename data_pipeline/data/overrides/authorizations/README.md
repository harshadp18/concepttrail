# Purpose-specific authorisation records (committed audit trail)

Write-once JSON records that grant specific **uses** for specific documents. Each document is bound by `source_id` and SHA-256. The inventory permission fields are never rewritten; these records are an overlay that `data_pipeline/authorization.py::check_use()` consults before every processing stage.

| Record | Basis | Scope | Uses granted | Documents |
|---|---|---|---|---|
| `AUTH-2026-10-31-owner-local-hackathon-processing.json` | `owner_attestation` (D-031, D-034) | `local_hackathon_processing` | `local_pdf_extraction`, `local_ocr`, `local_text_normalization`, `local_extraction_quality_evaluation` | 383 accepted Phase 3 rows; the 3 quarantined rows are excluded |
| `AUTH-2026-10-31-owner-project-use.json` | `owner_attestation` (D-050): "I confirm that we have the rights required to use these materials for the intended ConceptTrail project." | `conceptrail_project_use` | the local uses, plus `local_metadata_enrichment`, `ai_assisted_objective_generation`, `ai_assisted_quality_review`, `indexing_retrieval`, `student_facing_display` | the same 383 documents |

**Never granted by the local record** (the project-use record grants display, indexing and the two AI-assisted uses): external Gemini, Groq or DeepSeek processing; third-party OCR; external embeddings; cloud AI; student-facing display; redistribution; model training or fine-tuning (`permitted_training` stays `not_permitted`).

**Rules:**
- Records contain no textbook content.
- Records are never edited. A changed scope needs a new record with a new `record_id`.
- If a document's bytes change, its SHA-256 no longer matches the record, so the gate refuses it.
- An owner attestation is not legal verification. `review_status` stays `owner_attested_pending_rights_review` until written permission is on file.
- **Always refused by the gate,** whatever a record lists: `model_training_or_fine_tuning` and `redistribution`. They need a dedicated authorisation that does not exist.
- **Not decided by either record:** using an external embedding provider or an external LLM for answer generation. Decide before Phase 5.
- **Inventory overlay:** in derived outputs only, the project-use record's `inventory_field_overlay` sets `rights_status=approved` and `permitted_processing`, `permitted_indexing`, `permitted_display` to `permitted`. `permitted_training` and `permission_reference` are never changed. The original teammate CSV and the Phase 3 outputs keep their values.
