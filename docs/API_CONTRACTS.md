# API contracts

All routes are under `/api/v1` except `/health` and `/ready`. The generated, authoritative schema
is [`openapi/openapi-v1.json`](openapi/openapi-v1.json) (`python -m scripts.export_openapi`; a
test fails if it drifts from the code). This file states the rules behind it; examples are in
[`FRONTEND_INTEGRATION.md`](FRONTEND_INTEGRATION.md). Status below is what the code does today.

| Method and path | Purpose | Who |
|---|---|---|
| `POST /auth/login` | Student username + 8-digit PIN; teacher school email + password. Throttled, enumeration-resistant | public |
| `GET /me` | Identity, roles, enrolled or assigned classes (server-derived) | any user |
| `GET /catalog/classes` | All class-subject pairs in the caller's scope with `published` / `demo_release` / `not_available` | student, teacher |
| `GET /curriculum` | Servable curricula and chapters (paginated) | student, teacher |
| `GET /curriculum/items/{item_id}` | Chapter detail, objectives, sub-items, topics | student (in scope), teacher |
| `GET /curriculum/items/{item_id}/topics` | Chapter topics with the learner's own mastery | student, teacher |
| `GET /topics/{kc_id}` | Knowledge component and its servable notes | student (in scope), teacher |
| `GET /topics/{kc_id}/prerequisites` | Direct and transitive prerequisites, readiness, edge provenance | student (in scope), teacher |
| `GET /topics/{kc_id}/questions` | Deliverable questions, never with keys (paginated) | student |
| `POST /attempts` | Deterministic scoring, idempotent, updates BKT once | student |
| `GET /student/progress` | Own mastery estimates and attempt totals | student |
| `GET /student/progress/chapters` | Own chapter and subject roll-ups | student |
| `GET /student/activity` | Own attempts, newest first (paginated) | student |
| `GET /student/weak-areas` | Own low-mastery topics with enough evidence | student |
| `GET /student/review` | Questions last answered wrongly, to retry | student |
| `GET /student/recommendation` | Deterministic next step with the reason | student |
| `POST /doubts` | Grounded explanation or hint, or an explicit abstention | student |
| `GET /student/doubts/conversations`, `GET .../{id}`, `POST .../{id}/archive` | Own tutor history (503 until migration 0003 is approved) | student |
| `GET /teacher/classes` | Assigned classes with learner counts | teacher |
| `GET /teacher/classes/{class_id}/dashboard` | Class aggregates and topic signals | teacher assigned to the class |
| `GET /teacher/classes/{class_id}/learners` | Roster with activity and mastery summaries (paginated) | same |
| `GET /teacher/classes/{class_id}/learners/{learner_id}/progress` | One enrolled learner's progress | same |
| `GET /teacher/classes/{class_id}/weak-areas` | Topics where learners struggle | same |
| `GET /teacher/classes/{class_id}/heatmap` | Learners × topics: current estimate, evidence and attempt counts per cell (`subject_id`, `item_id`, `window_days` filters) | same |
| `GET /teacher/classes/{class_id}/bell-ringer/topics` | Every topic of the class level with unique-learner counts, denominators, window, flagging criteria; flagged topics carry the root gap and a warm-up card | same |
| `GET/POST /teacher/classes/{class_id}/bell-ringer/cycles`, `GET .../{cycle_id}`, `POST .../{cycle_id}/status` | Topic-specific Bell-Ringer cycles with baseline and follow-up (503 until migration 0004 is approved) | same |
| `GET /teacher/review/questions`, `POST .../{question_id}` | Question review queue and attributable decision | teacher, class levels assigned |
| `GET/POST /teacher/classes/{class_id}/interventions`, `POST .../{id}/status` | Planned teacher actions (503 until migration 0002 is approved) | same |
| `GET /notifications`, `POST /notifications/{id}/read`, `POST /notifications/read-all` | Own notifications (503 until migration 0003 is approved) | any user |
| `GET /jobs/{job_id}` | Ingestion/generation job status | operator |
| `GET /health`, `GET /ready` | Liveness; database, limiter and optional local model | public |

Not implemented: short-answer scoring (never served) and any admin or registration endpoint.
Bell-Ringer cycle persistence exists only as the proposed migration 0004 (see below).

## Request and response rules

- Use Pydantic v2 DTOs; never expose SQLAlchemy ORM entities directly.
- Error envelope: `{"error":{"code":"stable_snake_case_code","message":"safe user-facing message","request_id":"opaque-id"}}`. Keep detailed exceptions in redacted logs only.
- Authenticated user and learner IDs are resolved server-side. Client-supplied IDs are context hints only and never authority.
- Attempt request contains `question_id`, `question_version`, `submitted_answer`, optional `hint_tier`, and an idempotency key. It must not contain authoritative correctness, KC IDs or mastery values.
- Server loads the canonical question/version, applies the configured scoring method, inserts an immutable attempt and updates BKT at most once. Multi-KC items require KC-specific evidence.
- Question delivery never includes expected answer, private rubric or scoring internals.
- Doubt request includes class, subject, curriculum version, language, optional KC and question text. Validate these against the user's authorised curriculum. The response carries only database-derived source citations and a grounding status.
- Provider timeout/rate limit, missing content and insufficient evidence must return a controlled outcome; do not fabricate an answer.
- Long-running ingestion/generation jobs are started through an authorised operator command/API and polled by ID; return `202 Accepted` for job creation.
- Use pagination for curriculum, questions, attempts and teacher lists.

## Standard error codes

`invalid_context`, `unauthorised`, `forbidden_classroom`, `rights_blocked`, `no_relevant_content`, `insufficient_evidence`, `model_timeout`, `provider_rate_limited`, `provider_unavailable`, `invalid_model_output`, `answer_verification_failed`, `duplicate_attempt`, `job_not_found`, `job_failed`.

## Persistence caveats

The 26-table baseline has no dedicated doubt-conversation, notification, intervention or Bell-Ringer table. Do not persist those by inventing columns or overloading unrelated records. Doubt requests are stateless by default. Conversation history, notifications and interventions use the additive proposals in `db/proposals/` (0002, 0003); their routes answer `503 feature_not_enabled` until the owner approves and applies them. Bell-Ringer cycles use the additive proposal `0004_bell_ringer_cycle.py` (one open cycle per class and topic, enforced by a partial unique index) and answer `503 feature_not_enabled` until it is approved; the topic analysis and the heatmap are read-only and need no new table.

## Versioning

Breaking changes require a versioned route/schema or an explicit API contract migration. Include curriculum version, content version, question version, BKT config version and index generation where relevant.
