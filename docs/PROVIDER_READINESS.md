# LLM provider readiness (D-055)

Architecture: **Qwen 3.5 9B via local Ollama (primary) → GPT-OSS 120B via Groq (fallback candidate, disabled)**.
This page states what exists, what is missing, and the design for the missing parts. It is a readiness assessment, not an integration: **no provider adapter has been written.**

## 1. What exists today

| Question | Finding |
|---|---|
| Ollama adapter | **Does not exist.** `app/services/` contains only a README. No `*provider*`, `*ollama*`, `*groq*` or `*llm*` module exists anywhere in `app/` or `data_pipeline/`. |
| Groq adapter | **Does not exist.** |
| Provider SDK imports | None. A repository search found no import of `groq`, `google`, `openai` or `ollama` in `app/`, `data_pipeline/`, `tests/`, `training/` or `evaluation/`. |
| Typed configuration | **Added** in `app/core/config.py` and covered by `tests/unit/test_config_llm.py`. Configuration only; nothing reads it yet. |
| Fallback | Configured off. `LLM_FALLBACK_ENABLED=false`; enabling it also requires a valid Groq key (validated). |
| Embeddings | Undecided. No embedding setting was added. |

## 2. Environment variables (`.env.example`; the real `.env` was neither read nor changed)

| Variable | Default | Rule enforced by `Settings` |
|---|---|---|
| `LLM_PRIMARY_PROVIDER` | `ollama` | `ollama` or `groq` only; `gemini`/`deepseek` are rejected |
| `LLM_FALLBACK_PROVIDER` | `groq` | same set; must differ from the primary when fallback is enabled |
| `LLM_FALLBACK_ENABLED` | `false` | boolean |
| `LLM_TIMEOUT_SECONDS` | `120` | 1–600; must be ≥ the connect timeout |
| `LLM_CONNECT_TIMEOUT_SECONDS` | `5` | 0.5–60 |
| `LLM_MAX_OUTPUT_TOKENS` | `1200` | 16–8192; must be < `OLLAMA_NUM_CTX` |
| `LLM_MAX_RETRIES` | `0` | 0–5 |
| `LLM_TEMPERATURE` | `0.2` | 0–2 (initially 0.1–0.2) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | http(s) with a host; no credentials, query or fragment; **in production, plain http only to loopback or an RFC 1918/link-local/ULA address, otherwise https** |
| `OLLAMA_MODEL` | `qwen3.5:9b` | model-identifier pattern; placeholders rejected |
| `OLLAMA_NUM_CTX` | `4096` | 512–262144 (the model advertises 262144) |
| `OLLAMA_THINK` | `false` | boolean |
| `OLLAMA_KEEP_ALIVE` | `5m` | `30s`/`5m`/`1h`, seconds, `0` or `-1` |
| `GROQ_API_KEY` | placeholder | `SecretStr`; placeholder → unset; **required only if Groq is primary or fallback is enabled**; never shown in reprs or errors |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | https only; no credentials |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | model-identifier pattern |

There is no `DEEPSEEK_*` or `GEMINI_*` variable. Stale keys of those names in a developer's `.env` are ignored (`extra="ignore"`). A stale `LLM_PRIMARY_PROVIDER=gemini` in a real `.env` now fails validation with a value-free message naming the field.

## 3. Dependencies

| Need | Status |
|---|---|
| HTTP client for Ollama | `httpx` is a **core** dependency (0.28.1 installed). Enough for `/api/chat`; no Ollama SDK is needed. |
| Groq | `groq` is in the optional `llm` extra (1.7.0 installed). The OpenAI-compatible endpoint can also be called with `httpx`; prefer one approach per adapter. |
| OpenAI SDK | Not installed and not needed. |
| `google-genai` | **Removed from the `llm` extra**: no import or Gemini integration exists. Still installed in the current virtual environment (nothing was installed or uninstalled in this task). |
| Retry helper | `tenacity` is installed but is **not declared** in `pyproject.toml` (a transitive dependency). Declare it if the adapter uses it; a small hand-written bounded backoff avoids the dependency. |

## 4. Design for the adapters (not implemented)

### 4.1 Ollama (`POST {OLLAMA_BASE_URL}/api/chat`)

- **Request:** `model`, `messages`, `stream: false`, `format` (a JSON Schema object), `think: false`, `keep_alive`, `options: {num_ctx, temperature, num_predict}` with `num_predict = LLM_MAX_OUTPUT_TOKENS`.
- **Disable thinking:** send `"think": false` as a top-level field (not inside `options`), then assert that the response carries no thinking content. Verify the exact field against the installed Ollama (reported 0.40.13) when the adapter is first tested.
- **Structured output:** pass the Pydantic model's JSON Schema in `format`; parse `message.content` as JSON; then **validate again with the Pydantic model** (the grammar constraint is not a substitute for validation). Reject missing, extra or wrong-typed fields and malformed JSON as `invalid_structured_response`.
- **Model identifier:** from `OLLAMA_MODEL`; record the digest Ollama reports (owner-reported prefix `d63f830f28d5`) in telemetry so a silent model change is visible.
- **Measurement:** Ollama returns `total_duration`, `load_duration`, `prompt_eval_count`, `prompt_eval_duration`, `eval_count`, `eval_duration` (nanoseconds). Tokens/s = `eval_count / eval_duration`; model-load latency = `load_duration`. Time to first token needs `stream: true`.
- **Context budget:** the 4096 window must hold the system prompt, retrieved context, the question and the output. Estimate before sending and cap retrieved context. Ollama may truncate an over-long prompt instead of failing; treat `prompt_eval_count` near `num_ctx` as a truncation signal.

### 4.2 Groq (`POST {GROQ_BASE_URL}/chat/completions`)

OpenAI-compatible request/response. Structured output uses `response_format` with a JSON Schema where the model supports it, and a reasoning-effort setting for GPT-OSS; confirm both against the account's current model documentation at integration time. Usage comes from the response `usage` object; the request ID from the response.

### 4.3 Invoking fallback without enabling it by default

The router calls the fallback only when **all** hold: `LLM_FALLBACK_ENABLED` is true; the primary failed with a *transient* category (below); the request's data class is permitted for Groq (see section 7); and the retry/time budget allows it. With the default configuration the router returns the typed primary error. A test forces each condition false and asserts no call is made. A manual, explicit one-off call to the fallback (for a synthetic smoke test) is a separate code path that does not read `LLM_FALLBACK_ENABLED`.

## 5. Error handling

### 5.1 Ollama (local)

| Condition | Typical signal | Category | Retry | Fallback (only if enabled) |
|---|---|---|---|---|
| Service unavailable | connection refused / connect timeout | `provider_unavailable` | bounded | yes, if data class allows |
| Model not installed | HTTP 404, "model not found" | `model_not_installed` (configuration) | no; tell the operator to `ollama pull` | no |
| Model loading failure | HTTP 500 during load, or a very long `load_duration` | `model_load_failed` | once | yes |
| Request timeout | read timeout | `timeout` | bounded | yes |
| Invalid structured response | JSON or schema validation fails | `invalid_structured_response` | no (a validation outcome) | **no** |
| Generation failure / truncation | `done_reason` other than `stop` (e.g. `length`) | `generation_failed` / `output_truncated` | no | no |
| Context limit exceeded | truncation signal or error | `context_exceeded` | no; shrink the context | no |

### 5.2 Groq

| Status | Meaning | Category | Retry |
|---|---|---|---|
| 401 | bad or revoked key | `auth_failed` | **no** (never transient) |
| 403 | access or region restriction | `forbidden` | **no** |
| 404 | wrong endpoint or model | `not_found` (configuration) | no |
| 400 / 413 / 422 | invalid or oversized request | `invalid_request` | no |
| 429 | rate limit | `rate_limited` | yes, honour `Retry-After` |
| 5xx | provider error | `provider_error` | bounded |
| billing/account restriction | surfaces as an error body or 4xx | `account_restricted` | **no**; alert the owner |
| network timeout | read/connect timeout | `timeout` | bounded |

Retry policy: only the transient rows; exponential backoff with jitter (e.g. 0.5 s, 1 s, 2 s) capped at `LLM_MAX_RETRIES` and a total deadline of `LLM_TIMEOUT_SECONDS`; if `Retry-After` exceeds the remaining budget, fail instead of waiting. Never fail over around safety, rights, validation or insufficient-evidence outcomes. Invalid credentials and permissions are never treated as transient.

## 6. Usage and latency telemetry

Record one row per request in a local append-only ledger (a table needs a reviewed migration; use a JSONL file until then):

`ts`, `provider`, `model_id`, `model_digest` (Ollama), `request_id`, `input_tokens`, `output_tokens`, `total_tokens`, `latency_ms`, `load_ms` (Ollama), `tokens_per_second`, `outcome` (status or category), `attempts`, `fallback_reason` (if used), `pricing_version` and `cost_estimate` (cloud only), `prompt_sha256` (a hash, never the text).

**Never log:** API keys, student prompts, student identifiers or PII, textbook excerpts, or complete model responses (unless an explicitly approved diagnostic requires it). `LOG_REQUEST_BODIES` stays false.

**Cost.** Local Ollama has no per-token API charge but uses hardware and electricity. Groq cost is `tokens × price` from a **versioned pricing reference** (a file with `effective_date`, `source_url` and the prices, entered from Groq's current pricing page when the adapter is built). Do not hard-code prices in code.

## 7. Rights and data rules for providers

- **Local Ollama:** inference stays on the owner's machine. It is the development route.
- **Groq:** selecting it is **not** a rights decision. No textbook excerpt, PDF, page image, student personal data, student account identifier or school identifier goes to Groq, and no textbook-derived RAG context, until the owner approves the exact scope and the retention conditions are recorded in a new authorisation record. The gate already refuses `external_groq_processing`. No such record exists.
- **Allowed now:** synthetic, non-personal technical tests.
- **Minimisation:** never send student names, phone numbers, roll numbers, passwords, tokens or unnecessary learner history to any model provider.

## 8. Local development versus remote production

| | Development (now) | Remote production |
|---|---|---|
| Inference host | the owner's Mac (Apple M5, 24 GB, Ollama 0.40.13) | a dedicated inference server, or other approved infrastructure |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | `https://…` or a private-network address; the app rejects public plain-http |
| Reachability | only from the same machine | the app server must reach the inference host |
| Exposure | loopback | **never** a public port 11434; put authentication/TLS in front |
| Capacity | one user, 4096-token window | needs sizing for concurrency, memory and queueing |

## 9. Synthetic smoke-test plan (design; not run)

Cases are in `evaluation/provider_smoke_cases.json`. All inputs are synthetic and contain no textbook content or personal data. They run only on explicit instruction, once the adapters exist. **An LLM never scores these; checks are deterministic and educator review decides quality.**

| # | Case | Deterministic checks | Human review |
|---|---|---|---|
| 1 | Arithmetic, `27 × 14` | structured `answer == 378` | none |
| 2 | Class 7 fractions, `3/4 + 2/3` | `17/12`, mixed form `1 5/12`, steps present | age-appropriate language |
| 3 | Class 8 photosynthesis | required concept groups present (sunlight, chlorophyll, CO₂, water, glucose, oxygen); length bound | scientific accuracy, simplicity |
| 4 | Hindi Class 8 science/maths | Devanagari share, no U+FFFD, no doubled virama or repeated vowel sign, expected terms, schema valid | natural Hindi, terminology, spacing, grammar |
| 5 | Structured-output validation | offline: missing field, extra field, wrong type, malformed JSON are each rejected | none |
| 6 | Performance | total time, output tokens, tokens/s, model-load time, memory pressure (Ollama) | none |

**Preliminary observations (owner-reported, single runs, not a benchmark):** Qwen English structured maths 36.74 tokens/s, 6.06 s, 3/4 + 2/3 correct; Qwen Hindi structured science 34.31 tokens/s, 14.88 s, with spacing and scientific-explanation problems; Groq synthetic connectivity HTTP 200, 137 tokens, about 0.61 s. Repeat each case several times, on cold and warm models, before drawing any conclusion.

## 10. Open items

1. Write the Ollama adapter and the schema/validation layer; then the Groq adapter and router with fallback tests.
2. Decide the embedding provider and model separately (benchmark English and Hindi).
3. Owner approval and a rights/retention record before any Groq content processing.
4. Plan remote inference infrastructure.
5. Improve and measure Hindi output quality; repeat benchmarks.
