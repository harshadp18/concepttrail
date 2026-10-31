# Optional LLM fine-tuning — not part of the first release

Do not implement or run LLM fine-tuning until the owner explicitly approves a task and all readiness gates pass.

## Readiness gates

1. Define one narrow task (for example, output formatting or hint style), not “learn all textbooks”.
2. Prove the failure is not caused by missing/incorrect retrieval, wrong metadata filters, poor prompts, missing schema validation or incorrect source data.
3. Confirm rights for every training example and provider/model licence.
4. Build a human-reviewed dataset with source/annotation provenance.
5. Group-split by source/KC/question template/learner to prevent leakage; lock the final test set.
6. Establish a pretrained baseline and acceptance metrics before training.
7. Estimate and cap cloud GPU or hosted training cost; do not assume the developer laptop has a suitable GPU.
8. Compare candidate against baseline on identical held-out data, including class/subject/language slices and human blind review.
9. Version artifacts and maintain rollback to the baseline.

LoRA/QLoRA may be considered for an eligible pretrained model; full fine-tuning is not the default. Training a large language model from scratch is out of scope absent a documented, funded justification.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

A future-only holding area for a separately approved pretrained-LLM fine-tuning experiment. It is not part of the first release and must not be imported by runtime application code.

### 2. Recent Updates Incorporated in This Module

- No LLM training from scratch or LLM fine-tuning is approved for v1.
- Prefer fixing retrieval, source quality, prompts, schema validation and deterministic checks before considering fine-tuning.
- BKT fitting is separate from LLM fine-tuning and does not belong in this directory.

### 3. File Manifest

| File/path | Purpose | Exports | Dependencies |
|---|---|---|---|
| `training/llm_finetuning/README.md` | Approval and readiness gate | Process contract only | Owner approval; legal/licensing review |
| `training/llm_finetuning/.gitkeep` | Preserve future-only directory | None | Git |

### 4. Data Structures, Types & Schemas

Any future experiment must declare `experiment_id`, task definition, base model/revision, dataset version/hash, source licences, annotation protocol, split strategy, training configuration, evaluation metrics, cost cap, artifact version and rollback target. No student PII may appear in a dataset sent to a provider without separately approved lawful basis and data-protection review.

### 5. File-by-File Implementation Specification

Do not create training scripts, download model weights or call training APIs until the owner approves a written experiment plan and all rights/data/model gates pass. Any later implementation must keep dataset preparation, train, validation, locked test and report artifacts separate; split by source/template/learner to reduce leakage; compare against the unchanged pretrained baseline; and preserve a rollback path.

### 6. Integration Points

No runtime application dependency is permitted. A future approved experiment may consume a versioned, legally cleared dataset from `evaluation/` and publish an independently versioned candidate artifact for review; it must not silently replace the production provider/model.

### 7. Module Verification Checklist

- Confirm explicit owner approval and documented experiment scope.
- Verify dataset rights, privacy review, grouping/split integrity and locked test isolation.
- Compare the candidate with the pretrained baseline on the same held-out cases and all class/subject/language slices.
- Verify cost cap, artifact provenance and rollback before any deployment consideration.
