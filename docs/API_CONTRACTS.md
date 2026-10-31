# Proposed API contracts (not verified existing endpoints)

All routes are under `/api/v1`. These are target backend contracts based on the user-designated ConceptTrail README, not claims that an application server currently exists. The user will build the frontend separately; Claude Code must not create or modify frontend code. The backend must publish OpenAPI and a separate frontend integration guide. Inspect the actual repository before changing a working route.

| Method/path | Purpose | Authentication / authorization |
|---|---|---|
| `POST /api/v1/auth/login` | Class-code / learner login | Public endpoint with strict rate limit and enumeration resistance |
| `GET /api/v1/me` | Current identity, role and permitted school/class context | Authenticated session; derive identity server-side |
| `GET /api/v1/curriculum` | Curriculum options visible to this user | Authenticated; only published/current records; include explicit coverage states |
| `GET /api/v1/topics/{kc_id}` | KC metadata and approved notes/content | Authenticated; verify class/course and rights/review filters |
| `POST /api/v1/doubts` | Grounded explanation request | Learner session; validate context; retrieve approved evidence; abstain/escalate if weak |
| `POST /api/v1/attempts` | Submit an answer, score server-side, write attempt and update eligible KC state | Learner session; identity from session; idempotency key required |
| `GET /api/v1/student/progress` | Own mastery estimates and review schedule | Learner session; only own state |
| `GET /api/v1/teacher/classes/{class_id}/dashboard` | Class-level signals, priority explanations and topic gaps | Teacher must have active assignment to this class |
| `POST /api/v1/teacher/classes/{class_id}/bell-ringers` | Request a Bell-Ringer draft after evidence gate | Assigned teacher or authorised scheduler; draft only |
| `POST /api/v1/teacher/bell-ringers/{bell_ringer_id}/review` | Approve, edit or reject a Bell-Ringer draft | Assigned teacher only; persistence requires approved schema design |
| `GET /api/v1/jobs/{job_id}` | Read ingestion/generation job status | Creator/admin or permitted operator |

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

The 26-table baseline has no dedicated doubt-conversation table and no Bell-Ringer activity/approval table. Do not persist transcripts or activity approval state by inventing columns or overloading unrelated records. Implement stateless doubt requests and a non-persistent draft until the owner approves a dedicated migration and retention/audit design.

## Versioning

Breaking changes require a versioned route/schema or an explicit API contract migration. Include curriculum version, content version, question version, BKT config version and index generation where relevant.
