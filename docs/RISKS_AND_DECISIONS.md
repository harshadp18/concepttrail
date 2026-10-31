# Risks, open decisions and mitigations

| Risk / unresolved issue | Impact | Required action |
|---|---|---|
| No separate PRD or actual application repository supplied | Some product/UI details and implementation status cannot be verified | Inspect code before changing it; keep unspecified features behind explicit implementation gates |
| NCERT/third-party copyright and external processing permissions | Can block core extraction, RAG, model submission, display or redistribution | Obtain written permission or use content licensed for the exact intended operation; record separate rights flags |
| All-class/all-subject coverage too broad for one pilot | Misleading support claims | Maintain all 25 class-subject combinations and per-chapter status; pilot does not equal coverage |
| `subject_id VARCHAR` vs older INTEGER discussion | Migration inconsistency | Preserve executed schema; explicit migration only after owner approval |
| Embedding model/dimension not selected | Wrong index dimensions or incompatible vectors | Benchmark first; preserve unbounded `VECTOR`; rebuild indexes version-safely |
| Gemini/Groq/DeepSeek availability, terms and model IDs change | Outage, unexpected cost or data-use risk | Verify live account/model/terms; Groq fallback disabled pending tests; DeepSeek benchmark-only |
| BKT priors/thresholds are illustrative | Poor calibration or misleading learner status | Centralise versioned configuration; evaluate separately from quiz-score policy |
| Multi-KC item has one overall score | Evidence can be misattributed to several KCs | Require KC-specific component scoring; otherwise update only the designated primary KC or do not use item for BKT |
| Bell-Ringer persistence not represented in 26-table schema | Draft/approval/audit state cannot be safely persisted in current contract | Implement draft logic only in an approved persistence design; propose migration; never add table silently |
| Doubt-thread history not represented in schema | Persisted chat transcript would require schema/retention design | Keep request stateless/minimal initially or submit a reviewed schema/retention proposal |
| Frontend is separately owned by user | Claude may accidentally scaffold or modify UI code | Review Phase 0 repository findings | Leave frontend files untouched; provide REST/OpenAPI contracts and integration guide |
| Synthetic learner results mistaken for real efficacy | Unsupported performance claims | Mark fixtures and reports as simulation; exclude from calibration and outcomes claims |
| OCR/formula/table/map errors | Incorrect learning content is published | Page-level diagnostics, human visual review and subject-specific fixtures |
| Teacher access leakage | Exposure of minors' learning records | Backend classroom-assignment checks and negative authorization tests |
| Stale vector index after source withdrawal | Withdrawn/outdated or no-longer-permitted content could be retrieved | Source withdrawal state, index generation, cache purge and rollback/rebuild process |
| Free-tier access assumed | Unexpected bill or interrupted demo | No free/unlimited claims; quotas, spend caps, caching and controlled failure paths |

## Owner decisions still needed

1. Confirm the fourth derived CSV name and exact columns (`notes.csv` is the current proposal).
2. Approve any desired schema evolution, including Bell-Ringer activity/approval persistence.
3. Select an embedding model, revision, dimension, normalization and distance metric after benchmark.
4. Confirm Gemini model ID/account, permitted data use and retention terms.
5. Decide whether/when Groq fallback should be activated after acceptance tests; keep DeepSeek benchmark-only until selected.
6. Supply the PRD or approved UI specification and actual frontend repository, if available.
7. Confirm authentication and classroom onboarding details with the school; no parent role is assumed in the current three-role schema.
8. Record source-specific rights for processing, external model calls, indexing/RAG, training, display and redistribution.
9. Complete legal/privacy review, data retention/deletion, consent/authority, school/vendor terms and deployment region before real student use.

| Teammate CSV meaning/schema unknown | Incorrect field mapping or factual corruption | Profile headers/values and compare candidate fields to permitted source pages | Preserve original, use explicit mapping, split accepted/rejected rows and require owner review for ambiguous fields |
| PDF use rights unknown | Processing may exceed permitted use | Inspect per-source permission record before extraction/OCR | Metadata-only inventory until internal processing is permitted; no external provider use without separate permission |
