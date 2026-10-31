# `training/` — BKT fitting and optional future model training

## First-release decision

The first release does not fine-tune an LLM and does not train a language model from scratch. It uses a pretrained LLM with RAG. The adaptive-learning model in the project design is BKT. Live BKT updates are runtime calculations, not model-training jobs.

## Data categories (keep separate)

- Raw PDFs: source documents, not training examples.
- Cleaned textbook JSON/content units: knowledge sources for RAG, not automatically supervised examples.
- KC/prerequisite/question exports: reviewed educational structures and assessment items.
- Student response sequences: potentially eligible for BKT parameter fitting only when scoring is reliable and use is lawful/approved.
- Supervised LLM examples: separate, task-specific, permission-cleared, human-reviewed instruction/target records; none are currently established.
- Validation/test cases: locked benchmarks, not training data.

## `build_dataset.py`

Build explicit, versioned datasets. Store source/annotation provenance, task, language, class/subject, review status, and split-group IDs. Prevent near-duplicate content/source/question templates from leaking across train/validation/test. Keep the final test set locked.

## `fit_bkt.py`

Optional offline fitting of BKT parameters from eligible learner response sequences. Do not fit from synthetic data and call it CBSE calibration. Compare fitted parameters with versioned defaults and check convergence, plausibility, predictive likelihood and calibration.

## `evaluate_bkt.py`

Evaluate on held-out learners/sequences. Include likelihood, calibration, parameter stability and per-KC/per-item-type slices where sample size supports it. Training/fit completion alone is not acceptance.

## `llm_finetuning/`

Future-only. Revisit only if repeatable failures remain after retrieval, prompting, structured output, deterministic checks and human review; source rights explicitly allow training; a human-reviewed task-specific dataset exists; test set is locked; model licence and compute/cost/privacy plan are accepted. See `llm_finetuning/README.md` and `docs/AI_AND_PROVIDER_STRATEGY.md`.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Optional offline fitting of BKT parameters; not normal inference, ingestion or LLM training.

### 2. Recent Updates Incorporated in This Module

No LLM fine-tuning/from-scratch training in first release; BKT live update is deterministic runtime calculation.

### 3. File Manifest

`build_dataset.py`, `fit_bkt.py`, `evaluate_bkt.py`; `llm_finetuning/` is future-only.

### 4. Data Structures, Types & Schemas

Eligible input is lawful learner response sequences with stable KC labels and trustworthy scoring; synthetic cohort is excluded from calibration.

### 5. File-by-File Implementation Specification

Build versioned grouped train/validation/test sets; prevent learner/source/template leakage; check convergence, parameter plausibility, held-out likelihood and calibration.

### 6. Integration Points

Outputs versioned BKT config candidates for admin review; runtime service consumes only approved `bkt_config_version`.

### 7. Module Verification Checklist

Dataset provenance/license checks, learner-level splits, calibration report and no synthetic data in fit set.
