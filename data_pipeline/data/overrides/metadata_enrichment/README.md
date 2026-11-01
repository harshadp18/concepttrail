# Reviewed enrichment inputs (private: not published)

`official_learning_outcomes.json` is an optional catalogue of **official** CBSE/NCERT learning outcomes. Every entry must cite its source exactly:

- `academic_session`, `class_level`, `subject_id`, `chapter_match`;
- `objective` (verbatim);
- `source_url`, `source_title`, `source_page`;
- `verified_on`, `verified_by`.

`data_pipeline/enrich_metadata.py` uses an entry only when class, subject, session and chapter all match. Never add paraphrases or model-written text here: those are `source_derived_candidate` values, not official outcomes.

## Owner-approved inputs (2026-10-31)

| File | What it is |
|---|---|
| `owner_decisions_2026-10-31.json` | Write-once record of the owner's Phase 4 decisions: D-044 approved for `SRC-C09-HIN-IHGA1-02`; AI-generated objectives approved (D-049); `acquired_at` stays unknown without a record (D-052); extraction-status rule (D-051); AI-assisted page review (D-053); rights (D-050); one row per PDF for topics. The pilot CSV builder and the review triage read it. |
| `ai_generated_learning_objectives.json` | **AI-generated** learning-objective drafts for the 9 pilot chapters without a usable textbook objective (51 objectives). Origin `ai_generated`, generator recorded, `pending_teacher_review`. **Not** official, textbook-stated or teacher-approved. Each objective lists evidence terms; the pipeline uses an objective only if every term occurs in the chapter's own text and records the pages. |

Unlike `official_learning_outcomes.json`, the generated file is model-written text. That is why it is a separate file with its own origin and is never mixed into the official catalogue.

## Teacher-validation attestation (2026-10-31, D-054)

| File | What it is |
|---|---|
| `teacher_validation_attestation_2026-10-31.json` | Write-once owner attestation that teacher validation has been completed. It records completion **separately from approval**, holds no teacher identities, comments, scores, dates or per-item outcomes, and has an empty `individual_outcomes` list. It is bound to digests of the 51 objective IDs/texts/evidence (9 chapters) and of the numbered topic lists of 4 chapters, and records the SHA-256 of `ai_generated_learning_objectives.json`, which is not edited and keeps its original `pending_teacher_review`. |

Created with `python -m data_pipeline.teacher_validation record`; a second run changes nothing.

## Phase 4 closure attestations (2026-10-31)

| File | What it is |
|---|---|
| `d053_page_review_attestation_2026-10-31.json` | Write-once owner attestation that the human page-quality review was completed (effective `human_reviewed=true`, basis owner attestation) for the 22 pages in the AI-assisted review record. Bound by SHA-256 to that record, its summary and the inspection index. Individual findings are recorded as not recorded. |
| `phase4_pilot_signoff_2026-10-31.json` | Write-once owner sign-off (`approved`) of the extraction pilot and its recorded quality-gate results, bound by SHA-256 to the pilot reports, manifests and the other attestations. Retains the recorded limitations. |

Both are created by `python -m data_pipeline.owner_attestations` (`record-d053`, `record-signoff`) and checked by `verify`. If bound evidence changes, verification reports `stale` and the record no longer counts. Never regenerate them on another machine.
