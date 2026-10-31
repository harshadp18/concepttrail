# `evaluation/` — educational quality benchmarks

This directory contains benchmark cases and reports, not application runtime logic.

## Files

- `retrieval_cases.jsonl`: question/context metadata and the expected relevant source/chunk IDs for Recall@k and ranking evaluation.
- `answer_cases.jsonl`: reviewed question, permitted evidence references, rubric/reference answer and slice metadata for educator evaluation.
- `policy_cases.jsonl`: expected deterministic policy outcome for ambiguity, unsupported topics, insufficient evidence, coverage gates, hint policies and permissions.
- `reports/`: timestamped, versioned results and regressions.

## Minimum metadata per case

`case_id`, class, subject, course/language, curriculum version, task, expected source IDs or reference rubric, reviewer/status, dataset version, and split (`dev` or locked `test`). Do not include student PII. Use synthetic learner identifiers for simulations.

## Metrics

- Retrieval: Recall@k, MRR@k, nDCG@k if relevance grades exist, source citation resolvability, filter leakage.
- Answers: expert-rated correctness, curriculum alignment, grounding, age suitability, citation validity, unsupported-claim rate, appropriate abstention.
- Policy: expected decision accuracy on deterministic cases and correct abstention/teacher escalation.
- Provider comparison: paired Gemini/Groq/DeepSeek candidate tests on identical prompts and retrieval context; report latency, token use/cost under the provider's current pricing, parse failure, quality slices.
- BKT: held-out likelihood, calibration, stability and per-skill slices where data support.

A model response being syntactically valid or having a low training loss does not establish educational correctness.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Versioned held-out benchmarks for retrieval, generated answers, policy behavior, BKT and subject-slice quality.

### 2. Recent Updates Incorporated in This Module

Separate simulation from real learner evidence; report by class, subject, language and content type; provider comparisons are optional benchmark work.

### 3. File Manifest

`retrieval_cases.jsonl`, `answer_cases.jsonl`, `policy_cases.jsonl`, `reports/`.

### 4. Data Structures, Types & Schemas

Each case records ID, class/subject/course/curriculum, prompt/query, expected sources or rubric, scorer, review date, split group and status.

### 5. File-by-File Implementation Specification

Keep a locked test set; avoid source/question-template leakage; compute Recall@k/MRR@k, citation/filter validity, abstention, answer quality and latency.

### 6. Integration Points

Consumes approved chunks and service outputs; called during release gates, not production request handling.

### 7. Module Verification Checklist

Deterministic metric tests, no filter leaks, citation resolution and slice-level reports; synthetic data labelled clearly.
