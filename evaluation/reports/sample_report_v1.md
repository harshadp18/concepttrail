# ConceptTrail evaluation report (dataset v1)

Generated 2026-11-01T07:09:17.258323+00:00 | metrics fingerprint `f964bd2c1b912f65` | benchmark files unchanged since seal: True

**How to read this.** Section 1 checks that the software matches its written specification. Passing it says nothing about educational quality. Section 2 describes stored content with automated properties and proxies; none is an accuracy figure. Quality (is a key right, is a question clear, is an explanation supported) is `not_measured` until independent humans review it.

## 1. Software correctness (ground truth = the written specification)

| Check | Result | Provenance of expected values |
|---|---|---|
| Deterministic answer scoring | 38/38 cases | engineer_constructed_from_scoring_rules |
| - essay_x | 1/1 | |
| - multiple_select | 9/9 | |
| - numeric | 11/11 | |
| - short_answer | 1/1 | |
| - single_choice | 10/10 | |
| - true_false | 6/6 | |
| Adaptive policy conformance | 12/12 cases | engineer_constructed_from_written_policy |
| BKT known-answer vectors | 4/4 | exact_rational_arithmetic_from_bkt_equations |
| BKT fitting recovers synthetic parameters | max abs error 0.0175 (synthetic) | pipeline check only |
| Retrieval scope-filter leakage | 0 leaks in 576 results (75 queries, 25 class/subject cells) | scope filters only |

## 2. Stored content: automated properties and proxies (NOT quality)

Questions: 460 | status {'demo_release': 460} | origin {'ai_drafted': 460}
Types {'multiple_select': 70, 'single_choice': 246, 'true_false': 144} | languages {'en': 393, 'hi': 67}
Recorded human reviews: 0/460
Stored single-choice key positions {'A': 46, 'B': 131, 'C': 47, 'D': 22} (uniform chi-square p=0.0; learners see a shuffled order)
Correct option is also the longest (single-choice, chance ~25%): 57.3% (n=246, 95% CI 51.1%-63.3%)
Stem flagged passage-dependent by regex: 2.0% (n=460, 95% CI 1.0%-3.7%)
Cited source page exists as a stored unit: 100.0% (n=460, 95% CI 99.2%-100.0%) (existence, not support)
Options with an explanation: 22.6% (n=1552, 95% CI 20.5%-24.7%)
Near-duplicate pairs within a KC: 1
KC coverage: 137 KCs; questions per KC {0: 6, 2: 5, 3: 69, 4: 42, 5: 15}; zero-question KCs ['KC-ENG-50011', 'KC-HIN-50008', 'KC-HIN-50018', 'KC-MAT-50012', 'KC-MAT-50022', 'KC-SCI-50014']
Retrieval index: 1008 chunks, models {'ollama:bge-m3@790764642607': 1008}, dimensions {1024: 1008}; units without chunks {'text_unusable': 27}
  - resolves_to_unit_and_source: 100.0% (n=1008, 95% CI 99.6%-100.0%)
  - has_pdf_page_index: 100.0% (n=1008, 95% CI 99.6%-100.0%)
  - source_has_sha256: 100.0% (n=1008, 95% CI 99.6%-100.0%)
  - indexing_permitted_in_record: 100.0% (n=1008, 95% CI 99.6%-100.0%)
  - has_vector: 100.0% (n=1008, 95% CI 99.6%-100.0%)
  - nonempty_text_and_tokens: 100.0% (n=1008, 95% CI 99.6%-100.0%)

## 3. Not measured / blocked

| Metric | Status | Why |
|---|---|---|
| questions.key_correct | not_measured | no human reviews recorded |
| questions.unambiguous | not_measured | no human reviews recorded |
| questions.kc_alignment | not_measured | no human reviews recorded |
| questions.age_language_fit | not_measured | no human reviews recorded |
| questions.distractor_quality | not_measured | no human reviews recorded |
| retrieval.recall_mrr | not_measured | no human-labelled retrieval cases exist |
| explanation.supported | not_measured | no captured outputs, no reviewers |
| explanation.correct | not_measured | no human-authored prompts, no reviewers |
| explanation.abstention | not_measured | no labelled prompts |
| bkt.real_prediction | blocked | 5 real attempts from 1 learner |
| adaptive.learning_gain | blocked | no real learners; completion is not learning |

Human review: not_measured - no completed human review supplied

