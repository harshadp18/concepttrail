# `evaluation/benchmarks/` — evaluation architecture and benchmark data specification

Status: framework implemented; **no independent human-verified benchmark data exists yet**. Every
quality metric below is `not measured` or `blocked` until it does. Read the report, not the test
count: passing pytest shows the software matches its specification, not that the content teaches
correctly.

## 1. Architecture

Three separate things, never mixed:

1. **Instruments** (`evaluation/*.py`): `stats.py` (intervals, kappa, recall/MRR), `bank_metrics.py`
   (read-only properties of the stored bank and index), `citations.py` (citation checks on captured
   answers), `review.py` (blind human-review packets and their analysis), `run.py` (the report),
   `catalog.py` (the single list of metrics and what each requires).
2. **Benchmark data** (`evaluation/benchmarks/v1/`, sealed by SHA-256 in `manifest.json`): written
   by people or derived from rules, never from the question bank, the index or any model output.
3. **Reports** (`.local/evaluation/reports/`, git-ignored): generated, timestamped, with a
   `metrics_sha256` over the deterministic part so reruns are comparable.

Two kinds of claim, reported in separate sections:

| | Software correctness | Quality measurement |
|---|---|---|
| Question | Does the code do what its written spec says? | Is the content right, clear, supported, useful? |
| Ground truth | The specification | Independent human judgement; real learner outcomes |
| Evidence | pytest, conformance cases, known-answer vectors | Blind expert review, human-labelled cases, longitudinal data |
| A pass means | The code matches the spec | (only when measured) the content meets the rubric |

Boundaries enforced in code and tests: automated metrics are labelled `automated_property` or
`proxy`, never an accuracy; a `human_quality` metric cannot be marked automated; a breakdown cell
under 10 items is `insufficient_data`; AI-generated labels are ignored by the scorers; the report
prints every human-only metric as `not_measured`/`blocked` and fails a test if it does not.

## 2. Benchmark data specification (v1)

Common fields for every case: `case_id`, `dataset_version`, `class_level` (6-10), `subject_id`,
`language` (`en`/`hi`), `curriculum_item_id` (chapter), `label_provenance`, `reviewers`
(pseudonymous IDs), `split`. JSON Schemas are in `schemas/`.

- `label_provenance`: `human_expert_verified` and `human_reviewed_single` are the only values that
  count as ground truth for a quality metric. `engineer_constructed` cases check specifications.
  `ai_generated_unverified` may propose cases for review and never scores anything.
- **Independence:** the reviewer did not write or generate the item, labels before seeing any model
  output or stored key, and is competent in the subject (Hindi items: a Hindi-fluent reviewer).
- **Splits:** `dev` for iterating; `locked_test` is read only by release evaluations and never used
  to tune prompts, thresholds or models. No test item may be a paraphrase of a dev item.
- **Separation:** benchmark prompts are not drawn from, and benchmark labels are not derived from,
  the generated content under test. Source pages may be shared (they are the corpus), items may not.
- **Privacy:** pseudonymous learner and reviewer IDs only; real learner data needs a consent
  reference; no names, phone numbers or roll numbers anywhere.
- **Provenance of demo vs approved content** is preserved: reports show `review_status` counts, and
  nothing here changes a status.

| Suite | File / schema | Content | Today |
|---|---|---|---|
| scoring | `scoring_cases.jsonl` | 38 constructed answer/expected-status cases | populated |
| adaptive | `adaptive_cases.jsonl` | 12 constructed policy cases | populated |
| bkt | `bkt_known_answers.jsonl` | 4 exact-arithmetic vectors | populated |
| retrieval | `schemas/retrieval_case.schema.json` | query + graded relevant pages, incl. unanswerable | **no cases** |
| explanation | `schemas/explanation_case.schema.json` | prompt + reference points + supporting pages | **no cases** |
| question review | `schemas/question_review.schema.json` | blind reviewer record per item | **no reviews** |
| bkt sequences | `schemas/bkt_sequence.schema.json` | consented real response sequences | **no data** |
| learning outcome | `schemas/learning_outcome.schema.json` | pre/post study records with disjoint post-test | **no data** |

## 3. Metrics

### A. Software correctness, automated properties and proxies (none is an educational accuracy)

| Metric | What it is | Needs | Status now |
|---|---|---|---|
| `scoring.conformance` | Evaluator agrees with the scoring specification | engineer-constructed cases from the written rules | automated |
| `scoring.type_coverage` | Question types covered by constructed cases | case file | automated |
| `questions.structure` | Servable: deterministic key, option and type rules hold | stored rows | automated |
| `questions.key_position_bias` | Correct-answer position distribution | stored rows | automated |
| `questions.longest_correct_cue` | Correct option is also the longest | stored rows | automated |
| `questions.passage_dependence` | Stem refers to text the student cannot see | regex over stems; misses unlabelled dependence | automated |
| `questions.near_duplicates` | Near-duplicate stems within the bank | word-trigram similarity | automated |
| `questions.option_explanations` | Options with an explanation | stored rows | automated |
| `questions.source_page_resolvable` | Cited page exists as a stored content unit | database lookup (existence, not support) | automated |
| `questions.kc_coverage` | Questions per knowledge component | stored rows | automated |
| `questions.review_status` | Questions with a recorded human review | verification.reviews | automated |
| `questions.copied_wording` | Copies textbook wording | 10-word shingles at generation time; paraphrase copying not detected | automated |
| `retrieval.index_integrity` | Chunks resolve to units, sources, pages, hashes | database | automated |
| `retrieval.filter_leakage` | Retrieval returns nothing outside the learner scope | scope tests against the live index (tests) | automated |
| `retrieval.recall_mrr_ai_labels` | Recall@k / MRR on AI-derived relevance | relevance derived from AI-generated objectives (not independent) | automated |
| `explanation.citation_resolves` | Every cited label maps to retrieved evidence | captured model outputs + evidence | automated |
| `explanation.lexical_support` | Explanation sentences lexically overlap cited text | token overlap; cannot detect a wrong inference from right words | automated |
| `bkt.known_answers` | Update equations match hand-computed vectors | hand-computed vectors | automated |
| `bkt.fit_pipeline` | Fitting recovers known parameters on synthetic learners | synthetic data (pipeline check only) | automated |
| `adaptive.policy_conformance` | Recommendation matches the written policy | engineer-constructed cases from the written policy | automated |
| `adaptive.simulation` | Policy behaviour on simulated learners | synthetic learners; describes the simulator only | automated |

### B1. AI-assisted review (an AI model reviewing AI content; never a human review)

| Metric | What it is | Needs | Status now |
|---|---|---|---|
| `content.ai_review` | Whole-bank AI review: defects repaired, withdrawn, escalated | AI reviewer judgement (data_pipeline.content_review) | automated |

### B2. Synthetic results (evidence about code and simulators, not learners)

| Metric | What it is | Needs | Status now |
|---|---|---|---|
| `bkt.synthetic_recovery` | Parameter recovery, held-out prediction, robustness on synthetic learners | known generating parameters (evaluation.bkt_synthetic) | automated |
| `adaptive.synthetic_policy_comparison` | Policy vs baselines on simulated learners, adverse conditions | simulator hidden state (evaluation.policy_simulation) | automated |
| `retrieval.synthetic_regression` | Chapter-hit regression on AI-derived queries; abstention probes | KC metadata (ai_generated_unverified) | automated |
| `explanation.synthetic_regression` | Citation validity, abstention, arithmetic, language on AI-authored prompts | deterministic checks on live local-model answers | automated |

### B3/B4/B5. Require independent humans or real learners (blocked today)

| Metric | What it is | Needs | Status now |
|---|---|---|---|
| `questions.key_correct` | Stored answer key is correct (blind reviewer agrees) | independent subject-expert answers | not measured: no human reviews recorded |
| `questions.unambiguous` | Question has one defensible answer | independent subject-expert judgement | not measured: no human reviews recorded |
| `questions.kc_alignment` | Question assesses its knowledge component | reviewer rating | not measured: no human reviews recorded |
| `questions.age_language_fit` | Suitable for the class and language | reviewer rating (Hindi: Hindi-fluent reviewer) | not measured: no human reviews recorded |
| `questions.distractor_quality` | Distractors plausible and instructive | reviewer rating | not measured: no human reviews recorded |
| `retrieval.recall_mrr` | Recall@k / MRR on human-judged relevance | human-labelled query to page relevance | not measured: no human-labelled retrieval cases exist |
| `explanation.supported` | Claims are supported by the cited page | independent reviewer judgement per claim | not measured: no captured outputs, no reviewers |
| `explanation.correct` | Explanation is educationally correct and clear | independent subject-expert rating | not measured: no human-authored prompts, no reviewers |
| `explanation.abstention` | Abstains when evidence is insufficient | human-labelled answerable / unanswerable prompts | not measured: no labelled prompts |
| `bkt.real_prediction` | Held-out log loss / Brier / calibration on real learners | real, consented, longitudinal responses | blocked: 5 real attempts from 1 learner |
| `adaptive.learning_gain` | Recommendations improve learning | controlled comparison on real learners | blocked: no real learners; completion is not learning |

## 4. Commands

```sh
python -m evaluation.full [--quick] [--with-llm]   # everything below, one index report
python -m evaluation.run [--live-retrieval]        # core report (deterministic fingerprint)
python -m evaluation.bkt_synthetic [--quick] [--write-config] [--dump-data]   # synthetic BKT study
python -m evaluation.policy_simulation [--quick]   # synthetic adaptive-policy comparison
python -m evaluation.retrieval_regression          # synthetic retrieval regression (local embedder)
CONTENT_RELEASE_MODE=demo python -m evaluation.explanation_suite   # live explanation checks
python -m data_pipeline.content_review.patch build # AI review -> reviewable patch (read-only)
python -m data_pipeline.content_review.patch apply --database-url URL [--apply]   # disposable copy first
python -m evaluation.review make --n 120 --seed 1  # blind human review packet
python -m evaluation.run --review-packet DIR       # include completed human reviews
python -m scripts.release_gate                     # production gates (fails today, by design)
python -m evaluation.run --seal                    # refresh benchmark hashes after editing cases
```

## 5. Rules for adding data

Edit a case file, run `--seal`, review the diff, commit data and manifest together. Never edit a
case to make a failing check pass without recording why (`revision_note`); a failing
conformance case means either the code or the specification is wrong, and a person decides which.
