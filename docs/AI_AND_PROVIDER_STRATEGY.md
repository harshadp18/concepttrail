# AI, BKT, retrieval and provider strategy

## 1. Decision boundary

ConceptTrail's governing rule is: **deterministic algorithms decide; a pretrained LLM drafts language**. BKT estimates per-KC mastery; graph algorithms identify prerequisite relationships/root-gap candidates; deterministic policy selects the next action. The LLM can draft notes, doubt explanations, translations using reviewed glossary context and teacher activity drafts. It never decides score, mastery, permissions, teacher priority, role, classroom access or KC mapping.

The first release does not train an LLM from scratch or fine-tune one. BKT runtime updates are not model training. Offline BKT fitting is optional and requires appropriate, lawful, scored learner-response sequences.

## 2. BKT model contract

For each learner/KC, persist `mastery_probability` and the `bkt_config_version` used. A versioned configuration contains: `p_l0`, `p_t`, `p_g`, `p_s` (or a documented equivalent JSON field shape). The standard update is:

```python
p_correct = p * (1 - p_s) + (1 - p) * p_g
if correct:
    p_after_observation = p * (1 - p_s) / p_correct
else:
    p_incorrect = p * p_s + (1 - p) * (1 - p_g)
    p_after_observation = p * p_s / p_incorrect
p_next = p_after_observation + (1 - p_after_observation) * p_t
```

Validate all parameters and outputs in `[0, 1]`; denominators must be nonzero. Use central, versioned configuration. Example parameter values found in historical project material are illustrations only, not trained/calibrated values. Store attempt history and make attempt replay idempotent.

### Multi-KC scoring

A question may map to multiple KCs in `question_kcs`, but one overall correctness boolean is not valid evidence for every mapped KC by default. Update a KC only when there is explicit KC-specific evidence/component scoring. Otherwise use one designated primary KC for the observation or exclude that item from BKT updates until a reviewed mapping/scoring rule exists. The current `attempts` schema does not provide a separate normalized per-KC observation table; do not add one without an approved migration.

## 3. Keep mastery and quiz policies separate

Proposed quiz-score policy (percentage):

- `score >= 70`: quiz policy passed; re-check after 7 days.
- `30 <= score < 70`: create fresh retest in 1–2 days.
- `score < 30`, or a second failed retest: flag for teacher review.

Proposed BKT mastery bands (probability):

- `P(L) >= 0.85`: high estimated mastery.
- `0.50 <= P(L) < 0.85`: developing/uncertain mastery.
- `P(L) < 0.50`: low estimated mastery.

Do not conflate those values. Thresholds are versioned product heuristics, not scientific facts. Use neutral, non-stigmatising language.

## 4. Additional deterministic policies (proposals to evaluate)

| Policy | Proposed starting rule | Engineering requirement |
|---|---|---|
| Practice ladder | Basic / standard / challenge; up after two consecutive correct; down after two consecutive incorrect | Store consecutive outcome state; cap repetition; test every transition |
| Item selection | Prefer predicted correctness near 0.7 where eligible questions exist | Difficulty is item metadata, never a BKT parameter; test exposure/repetition constraints |
| Spaced review | 1, 3, 7, 14 day cadence | Treat as heuristic; persist policy version and due date |
| Priority score | `3*failed_cycles + 2*doubts_last_14_days + max(0,(30-latest_score)/10) + 1*falling_mastery_trend` | Return a component breakdown and reason codes; weights configurable |
| Bell-Ringer gate | Around 60% recent-response coverage plus minimum affected group around five | Both thresholds configurable; insufficient evidence blocks generation; offer 3-question paper check |
| Doubt clusters | Cosine similarity around 0.8 initial threshold | Tune against human-labelled pairs; never hide unique doubts in a cluster |

No policy is a measured impact claim. Use simulation for deterministic workflow tests only.

## 5. RAG pipeline

`rights-approved source -> acquisition -> page-aware extraction -> clean/structure -> human review -> content units -> semantic chunks -> embeddings -> pgvector -> hard-filter retrieval -> prompt -> LLM -> schema/source/subject validation -> response or abstention`.

Mandatory retrieval filters: class, subject, curriculum version, course/language, source permission state, content review/publication state and index generation. Use the authenticated learner's context resolved server-side. When context is ambiguous, ask instead of guessing.

Citations must be assembled from actual database/retrieval records. Never trust model-generated page numbers or source IDs. A response with no adequate source evidence must return `insufficient_evidence`/teacher escalation rather than a fluent unsupported answer.

Evaluate Recall@k, MRR@k, filter correctness, citation resolvability, abstention quality and latency separately by class/subject/language/content type. A proposed Recall@5 target is 0.85 on a curated internal set; it is not a current measurement.

## 6. Provider posture

Use one configured, approved provider for the initial path. Preserve a provider-neutral interface. Gemini Flash is the proposed primary adapter from current conversation decisions, but the exact model ID, account access, regional availability, request limits, pricing and data terms must be verified before use.

Groq-hosted GPT-OSS-120B is an optional fallback candidate and remains disabled until the owner/account and privacy review are complete and tests prove it follows the same schema, grounding and safety rules. DeepSeek is benchmark-only unless separately approved. Do not enable multi-provider failover simply because an adapter exists.

Fallback can occur only for transient timeouts, network errors, rate limits or temporary 5xx errors. Never fail over around permission denials, safety refusals, invalid inputs, insufficient evidence or verifier failures. Bound retries and total request time. Redact prompts/logs; do not send student names, phone numbers, roll numbers, credentials or unnecessary learner history.

## 7. Embedding model decision

No final embedding model is selected. Benchmark English and Hindi, plus other approved course/language variants, across all five subjects. Record exact model ID/revision, dimensions, normalization, similarity metric, licence, runtime cost and retrieval quality. Keep the current PostgreSQL `VECTOR` column dimension-unbounded until this is chosen. Rebuild a versioned index when model or chunking changes; never mix incompatible vector spaces.

## 8. Fine-tuning readiness gate

Do not fine-tune in the first release. Revisit only after measurable repeated failures remain after retrieval quality, prompts, schemas, deterministic validators and teacher review have been improved; rights allow training; the task dataset is human-reviewed; train/validation/test splits avoid leakage; a locked benchmark and baseline exist; and model licence/privacy/compute costs are approved.
