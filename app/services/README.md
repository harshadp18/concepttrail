# Services

> **Status (2026-10-31):** only the Phase 5 graph modules exist: `prerequisite_graph.py` (graph validation, retired-aware release gate, traversal, scope- and lifecycle-aware coverage), `graph_snapshot.py` (verify a released snapshot; `load_released_graph` returns None on any failure, so callers serve no remediation graph and escalate to the teacher) and `audit_chain.py` (canonical JSON and hash-chain verification). None of the other modules listed below exist yet. No provider adapter exists. `llm_provider` is planned as an Ollama (Qwen 3.5 9B, primary) adapter and a disabled Groq (GPT-OSS 120B) fallback (D-055). Typed settings exist in `app/core/config.py`; the adapters do not. See `docs/PROVIDER_READINESS.md`.

Services implement domain logic. Keep interfaces typed, side effects explicit and pure logic independently testable. `bkt_service` owns mastery probability updates; `prerequisite_graph` owns graph traversal; `policy_engine` owns decisions; `retrieval_service` owns filtered retrieval; `llm_provider` owns provider adapters/fallback; `answer_verifier` owns structural/source/subject checks; `content_cache` owns safe content caching; `bell_ringer_service` owns draft workflow. Do not place these responsibilities in API route files.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Application/domain logic separated from routes and persistence.

### 2. Recent Updates Incorporated in This Module

BKT and policies deterministic; graph is NetworkX over relational edges; RAG filters hard; provider fallback is transient-only and disabled until acceptance; Bell-Ringer (`bell_ringer.py`) chooses topics by deterministic unique-learner rules and builds its warm-up card from stored questions by a fixed template (no model); cycles use proposed migration 0004 and stay disabled until approved.

### 3. File Manifest

`bkt_service.py`, `prerequisite_graph.py`, `policy_engine.py`, `retrieval_service.py`, `llm_provider.py`, `answer_verifier.py`, `content_cache.py`, `bell_ringer_service.py`.

### 4. Data Structures, Types & Schemas

BKT inputs: learner/KC state, correct observation, versioned P(L0/T/G/S), scoring provenance. Retrieval output carries chunk/source/content unit/page locator/index generation. Provider returns schema-bound text only.

### 5. File-by-File Implementation Specification

Implement pure BKT and graph/policy functions first. Attempt service owns idempotent transaction. Retrieval enforces class/subject/version/language/rights/review filters. Verifier validates source IDs and subject-specific answers. LLM receives minimum context only.

### 6. Integration Points

Services use schemas and repositories; routes call services; data pipeline publishes records consumed by retrieval.

### 7. Module Verification Checklist

Hand-computed BKT; graph cycle/root-frontier fixtures; policy boundary cases; hard-filter leakage; citation validity; transient fallback classification; Bell-Ringer low-coverage, unique-learner and idempotent-cycle tests.
