# Reviewed enrichment inputs (committed)

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
