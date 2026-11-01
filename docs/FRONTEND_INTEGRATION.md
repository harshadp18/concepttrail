# Frontend integration guide

The React frontend lives in [`frontend/`](../frontend/README.md) (owner instruction, 2026-11-01).
Local start-up commands are in [`LOCAL_DEVELOPMENT.md`](LOCAL_DEVELOPMENT.md); the visual and
functional audit is in [`FRONTEND_UI_AUDIT.md`](FRONTEND_UI_AUDIT.md).
The authoritative, generated contract is [`docs/openapi/openapi-v1.json`](openapi/openapi-v1.json)
(regenerate with `python -m scripts.export_openapi`; a test fails if it drifts from the routes).
This guide covers what the schema alone does not say.

## Connection, authentication and CORS

- Base path `/api/v1`. JSON only. Development backend: `http://127.0.0.1:8010` (Docker stack).
- `POST /auth/login` with `{"login_identifier", "credential"}`. Students use their
  platform-issued username and 8-digit PIN; teachers use their school email and password. There is
  no self-registration and no class-code login; accounts are provisioned by the school.
- The response carries `access_token` (JWT, default 30 minutes, `expires_in` seconds). Send it as
  `Authorization: Bearer <token>`. There is no refresh endpoint: on `401 invalid_token` sign in again.
- Tokens are bearer headers, not cookies; CORS is configured without credentials. Allowed origins
  come from `CORS_ALLOWED_ORIGINS` (explicit list; https only in production). Allowed request
  headers: `Authorization`, `Content-Type`. Exposed: `X-Request-ID`, `Retry-After`.
- Login throttling: repeated failures for one account or from one address return
  `429 too_many_login_attempts` with `Retry-After`. `503` means the server-side protection is
  unavailable; do not retry in a loop.

## Errors

Every error is `{"error": {"code", "message", "request_id"}}`. Show `message`; branch on `code`;
include `request_id` in support reports. Codes in use: `unauthorised`, `invalid_token`,
`invalid_credentials`, `too_many_login_attempts`, `forbidden_role`, `forbidden_classroom`,
`learner_access_required`, `enrollment_required`, `forbidden_grade`, `topic_not_found`,
`item_not_found`, `subject_not_found`, `question_unavailable`, `invalid_answer_option`,
`invalid_answer_format`, `answer_verification_failed`, `unsupported_scoring_method`,
`duplicate_attempt`, `too_many_requests`, `retrieval_not_configured`, `rate_limiter_unavailable`,
`invalid_context`, `validation_error`, `request_too_large`, `internal_error`, `job_not_found`.
Out-of-scope content is reported as not found (404), never as forbidden.

## Scope

A student's class level comes from their active enrollment on the server. `grade_level` on
`/curriculum` only narrows the list (another level returns `403 forbidden_grade`). Topics and
questions outside the enrolled class are not found, except earlier-class prerequisites reached
through the prerequisite graph (remediation).

## Student flow

| Step | Call |
|---|---|
| Profile and class | `GET /me` |
| Subjects and chapters | `GET /curriculum` |
| Topics of a chapter (with own mastery) | `GET /curriculum/items/{item_id}/topics` |
| Topic detail | `GET /topics/{kc_id}` |
| Questions | `GET /topics/{kc_id}/questions` |
| Answer | `POST /attempts` |
| Progress | `GET /student/progress` |
| Next step | `GET /student/recommendation` |
| Ask a doubt / get a hint | `POST /doubts` |

### Questions and answers

- Render options in `display_order` and label them by position (1, 2, 3 or A, B, C on screen).
  `option_key` is an identifier to send back, not a display label; order is shuffled per learner
  and stable across reloads. Answer keys are never sent to the client.
- `answer_shape` says what to send in `submitted_answer`:

| `item_type` | `answer_shape` | `submitted_answer` |
|---|---|---|
| `single_choice` | `option_key` | `{"option_key": "C"}` |
| `true_false` | `option_key` | `{"option_key": "A"}` (or `{"value": true}`) |
| `multiple_select` | `option_keys` | `{"option_keys": ["A", "D"]}` (exact set, all-or-nothing) |
| `numeric` | `value` | `{"value": 3.5}` |

  Only question types the server can score are listed; short-answer items are never delivered.
- `POST /attempts` needs a client-generated `idempotency_key` (16-128 chars, one per answer). A
  retry with the same key returns the stored result with `duplicate_replay: true`; reusing a key for
  another question is `409 duplicate_attempt`. `hint_tier` 0-3: with tier 2 or more, a correct
  answer is recorded but counted as incorrect evidence for mastery.
- `bkt.mastery_probability` is a model estimate (0-1), not a percentage score. Parameters are
  provisional and uncalibrated: do not present it as a grade.

### Recommendation

`status: "ok"` gives `kc_id`, `question_id`, `category` (`remediate_prerequisite`, `continue` or
`new`) and a human-readable `rationale` to show. `status: "insufficient_data"` with `reason` (for
example `no_active_enrollment`, `graph_not_released`, `all_scoped_kcs_mastered`) is a normal state:
show an explanatory message, not an error.

### Doubts

`POST /doubts` with `{"question", "mode": "explanation" | "hint", "kc_id"?, "subject_id"?}`.
Always `200` for a processed request; check `grounding`:

- `grounded` (`status: ok`): show `explanation`, `steps` or `hint`, and the `citations` (source and
  page). The answer is built only from the cited pages.
- `abstained`: `status` is `insufficient_evidence`, `not_authorized`, `model_unavailable`,
  `model_timeout` or `invalid_model_output`; show `message` (suggests asking the teacher).

Limited per learner (`DOUBT_REQUESTS_PER_HOUR`, default 30): `429 too_many_requests` with
`Retry-After`. Answers can take tens of seconds on the local model; use a long client timeout and
a loading state. No conversation is stored.

## Demo content labelling

Responses carry `content_release` (`"production"` or `"demo"`) and curriculum coverage states
(`published`, `demo_release`, `not_available`). In demo mode the content is AI-generated and has
not been reviewed by a teacher: the UI must say so wherever `demo` / `demo_release` appears.

## Teacher

`GET /teacher/classes/{class_id}/dashboard` (class from `GET /me` `assigned_classrooms`). Other
classes return `403 forbidden_classroom`.

Question review: `GET /teacher/review/questions?status=demo_release|validated_draft|in_review`
lists items for the class levels the teacher is assigned to, with keys, explanations, sources,
the AI review verdict (labelled as AI) and earlier human reviews. `POST /teacher/review/questions/{id}`
with `{"decision": "approved" | "rejected" | "revision_required", "rationale"}` records an
attributable human review. Approval is accepted only for a validated draft: demo content returns
`409 review_refused` and must be revalidated first. Show the AI verdict as "AI check", never as a
teacher review.

Interventions: `GET/POST /teacher/classes/{class_id}/interventions` and
`POST .../interventions/{id}/status` (`in_progress`, `completed`, `cancelled`). They answer
`503 feature_not_enabled` until the owner approves and applies the proposed migration; build the
UI so that this state is shown as "not available yet".

## Progress, catalog and history (added routes)

All list routes take `limit` (1-100) and `offset` (>= 0) and return `{count, limit, offset, <items>}`;
`count` is the total, so a client can page until `offset + limit >= count`. `limit=0` or a negative
`offset` is `422 validation_error`.

| Need | Call | Empty state |
|---|---|---|
| Which class-subject pairs exist | `GET /catalog/classes` | pair has `state: "not_available"`, `chapters: 0` |
| Chapter page | `GET /curriculum/items/{item_id}` | `topics: []`, `topics_available: false` |
| "What should I learn first" | `GET /topics/{kc_id}/prerequisites` | `graph_available: false` with a `reason` |
| Chapter and subject progress | `GET /student/progress/chapters` | `topics_started: 0`, averages and `accuracy` are `null` (never 0) |
| Recent activity | `GET /student/activity` | `count: 0`, `attempts: []` |
| Weak topics | `GET /student/weak-areas` | `weak_areas: []` |
| Retry wrong answers | `GET /student/review` then `POST /attempts` with a new `idempotency_key` | `questions: []` |

Mastery numbers are provisional model estimates (`thresholds_provisional: true`): label them as
estimates, not grades. Treat `null` as "no evidence yet", not as zero.

### Tutor conversations

`POST /doubts` accepts an optional `conversation_id`. When history is enabled the first call
returns a new `conversation_id` in the response; send it back for follow-ups. When history is not
enabled `conversation_id` is `null` and every call is independent; sending one then returns
`200` with `null` (the id is ignored). Read history with `GET /student/doubts/conversations`
(paginated) and `GET /student/doubts/conversations/{id}`; those answer `503 feature_not_enabled`
while the feature is off. A follow-up question only borrows the previous student question to find
evidence; the answer is still built from cited pages or the tutor abstains.

### Teacher

`GET /teacher/classes` first (it lists the classes the teacher may open), then
`/teacher/classes/{class_id}/learners` (paginated roster with `attempts`, `accuracy`,
`average_mastery_probability`, `last_attempt_at`), `/learners/{learner_id}/progress` (chapters,
subjects, weak areas, recent activity), `/weak-areas` and `/dashboard`. A class the teacher is not
assigned to is `403 forbidden_classroom`; a learner who is not actively enrolled in the class is
`404 learner_not_found`.

### Notifications

`GET /notifications?unread_only=true`, `POST /notifications/{id}/read`, `POST /notifications/read-all`.
Every notification has `kind` (`class_weak_area`, `intervention_update`, `review_outcome`,
`system`) and `is_synthetic`; show a "demo" marker when it is true. Another user's notification is
`404`. Poll (no push channel exists); once a minute is plenty.

## Features unavailable until the owner approves a migration

| Feature | Routes | Behaviour until approved | Enabled by |
|---|---|---|---|
| Interventions | `/teacher/classes/{id}/interventions*` | `503 feature_not_enabled` | migration 0002, `INTERVENTIONS_ENABLED=true` |
| Notifications | `/notifications*` | `503 feature_not_enabled` | migration 0003, `NOTIFICATIONS_ENABLED=true` |
| Tutor history | `/student/doubts/conversations*`, `conversation_id` | `503` on the history routes; `/doubts` stays stateless | migration 0003, `DOUBT_HISTORY_ENABLED=true` |

Design the UI so a `503 feature_not_enabled` means "not available yet", never an error banner.

## Demo data

A demo backend (see `docs/MVP_SCOPE.md`) serves a fictional population: learners named
`DEMO Learner 7-01`, classrooms labelled `SYNTHETIC-DEMO`, logins starting `demo-` or `demo.`.
Their attempts, mastery, interventions and notifications are synthetic and are not evidence of
real learning; show the demo banner whenever `content_release` is `"demo"`. Demo credentials are
generated into `.local/demo_credentials.json` (Git-ignored), not documented here.

## Configuration and access rules for the frontend

- Read the API base URL from build-time configuration (`VITE_API_BASE_URL`). The committed
  `frontend/.env.development` points at the demo backend, `http://localhost:8020/api/v1`; the dev
  stack on port 8010 serves the persistent database, which has no demo learners. Add the browser
  origin (`http://localhost:5173`) to `CORS_ALLOWED_ORIGINS` on the server.
- The frontend talks only to this API. It never connects to PostgreSQL, Redis or Ollama, and never
  holds a provider key.
- Keep the token in memory (or `sessionStorage`; the app uses `sessionStorage`); never in a URL. There is no refresh: on `401`
  with `invalid_token`, return to the login screen.
- Student routes need a student token; teacher routes need a teacher token. A role mismatch is
  `403 forbidden_role` or `403 forbidden_classroom`. Do not infer permissions from the UI; the
  server decides.

## Health

`GET /health` (liveness) and `GET /ready` (database and rate limiter; `503` when not ready; the
local model is reported but optional). Neither needs authentication.

## Sample calls

```sh
B=http://127.0.0.1:8010/api/v1
TOKEN=$(curl -s -X POST $B/auth/login -H 'Content-Type: application/json' \
  -d '{"login_identifier":"<username>","credential":"<pin>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
H="Authorization: Bearer $TOKEN"
curl -s $B/me -H "$H"
curl -s $B/curriculum -H "$H"
curl -s $B/curriculum/items/<item_id>/topics -H "$H"
curl -s $B/topics/<kc_id> -H "$H"
curl -s $B/topics/<kc_id>/questions -H "$H"
curl -s -X POST $B/attempts -H "$H" -H 'Content-Type: application/json' \
  -d '{"question_id":"<id>","question_version":1,"submitted_answer":{"option_key":"C"},"idempotency_key":"<uuid>"}'
curl -s $B/student/progress -H "$H"
curl -s $B/student/recommendation -H "$H"
curl -s -X POST $B/doubts -H "$H" -H 'Content-Type: application/json' \
  -d '{"question":"How do I add fractions with the same denominator?","mode":"hint"}'
curl -s $B/teacher/classes/<class_id>/dashboard -H "Authorization: Bearer <teacher token>"
curl -s $B/jobs/<job_id> -H "$H"
```

## The frontend in this repository

Stack: Vite 5, React 18, TypeScript (strict), React Router 6, TanStack Query 5, Tailwind CSS 3,
Framer Motion 11 (one animation library), Radix primitives for the account menu and switches,
lucide icons. Tests: Vitest + Testing Library (unit), Playwright (end-to-end against the live
local stack).

```
frontend/
  src/api/http.ts        fetch wrapper: base URL, bearer token, error envelope -> ApiError, 401 handling
  src/api/types.ts       response types (from the OpenAPI schema and the route code)
  src/api/endpoints.ts   one function per backend route; no other file builds URLs
  src/api/hooks.ts       React Query hooks and cache invalidation after writes
  src/context/           AuthContext (login, /me, logout, expiry), TeacherClassContext
  src/components/        layout (AppShell), ui (primitives, states, motion), student, teacher, brand
  src/pages/             public, auth, student, teacher, shared (alerts, profile)
  src/__tests__/         unit tests, including the OpenAPI contract test
  e2e/flows.spec.ts      browser journeys against the running stack
  scripts/ui-audit.mjs   screenshots of every page at four viewports
```

### Authentication and routing

`POST /auth/login` returns the token and the identity; the role comes from `identity.roles`. If a
student signs in on the teacher tab (or the reverse) the app refuses with a clear message instead
of guessing. The token is stored with its expiry in `sessionStorage`; on reload the app calls
`GET /me` to restore the session. Any `401` clears the session and shows "Your session ended".
`/student/*` and `/teacher/*` are guarded by role in the client for navigation only — every
request is still authorised by the server (a teacher of Class 7 calling a Class 8 route gets
`403`, verified in the end-to-end tests).

### Screen-to-API map

| Screen | Calls |
|---|---|
| Student home | `/catalog/classes`, `/student/progress/chapters`, `/student/weak-areas`, `/student/recommendation`, `/topics/{kc}` |
| Subjects, subject chapters | `/catalog/classes`, `/curriculum`, `/student/progress/chapters` |
| Chapter | `/curriculum/items/{item_id}` |
| Topic | `/topics/{kc}`, `/topics/{kc}/prerequisites`, `/student/progress` |
| Practice | `/topics/{kc}/questions`, `POST /attempts` (one idempotency key per answer), optional `POST /doubts` (`mode: hint`, sent with `hint_tier: 1`) |
| Progress, next steps, retry, history | `/student/progress/chapters`, `/student/weak-areas`, `/student/recommendation`, `/student/review`, `/student/activity` |
| Buddy | `POST /doubts`, `/student/doubts/conversations[/{id}]` |
| Alerts (both roles) | `/notifications`, `POST /notifications/{id}/read`, `POST /notifications/read-all` |
| Teacher classes overview | `/teacher/classes`, `/teacher/classes/{id}/dashboard`, `.../bell-ringer/topics`, `.../heatmap` |
| Heatmap | `/teacher/classes/{id}/heatmap` |
| Bell Ringer, cycle | `.../bell-ringer/topics`, `.../bell-ringer/cycles`, `.../cycles/{cycle_id}`, `.../cycles/{cycle_id}/status` |
| Learners, learner | `/teacher/classes/{id}/learners`, `.../learners/{learner_id}/progress` |
| Question review | `/teacher/review/questions`, `POST /teacher/review/questions/{id}` |
| Support plans | `/teacher/classes/{id}/interventions`, `POST ...`, `POST .../{id}/status` |

### Bell Ringer

`GET /teacher/classes/{class_id}/bell-ringer/topics?subject_id=&window_days=` returns every topic
of the class level. Each row reports, for the class's actively enrolled learners (the
denominator): learners with an estimate, *unique* learners below the weak cut-off, learners who
never attempted it, and — inside the stated window — failed attempts and the unique learners
behind them. `criteria` echoes the thresholds (`BELL_RINGER_MIN_COVERAGE`,
`BELL_RINGER_MIN_AFFECTED_LEARNERS`, `BELL_RINGER_MIN_AFFECTED_SHARE`, `BELL_RINGER_WINDOW_DAYS`);
`unmet_criteria` says why a topic was not flagged. Flagged topics are ranked and carry
`root_gap` (prerequisite search over the runtime graph, with edge provenance) and `activity`
(the deck's 1/3/1-minute warm-up, a board question on the target topic, a bridge question on the
flagged topic, the answer key, and "watch for": the class's most common wrong option, else the
question's stored misconception note). No language model is involved.

`POST .../bell-ringer/cycles {kc_id, note?}` opens a cycle for that topic and returns `201`; if an
open cycle already exists for the class and topic it is returned with `200`, so reloading or
double-clicking never duplicates a plan. Several topics may have open cycles at once. Status moves
`planned -> in_progress -> completed` (or `cancelled`). `GET .../cycles/{id}` includes
`follow_up`: the learners affected at creation, re-checked now with the same cut-off. Cycle routes
answer `503 feature_not_enabled` until migration 0004 is approved; the topic analysis does not.

### Heatmap

`GET /teacher/classes/{class_id}/heatmap?subject_id=&item_id=&window_days=` returns `topics`
(columns), `learners` (rows, sorted by name) and one cell per learner and topic with
`mastery_probability` (or `null`), `evidence_count`, `attempts`, `correct`, `last_attempt_at` and
`band` (`mastered`, `developing`, `needs_practice`, `insufficient_evidence`, `no_data`). The window
only limits attempt counts; estimates are always current. Missing data is never zero. One request
per view; at most 80 topics (`truncated: true` beyond that).

### States the UI handles

Loading skeletons; empty states with an explanation; `null` shown as "Not started" or "—";
`503 feature_not_enabled` shown as "not available yet" (never an error banner); `403` as no
access; `404` as not found; network failure and timeouts with a retry; `429` with the
`Retry-After` time; tutor abstentions (`insufficient_evidence`, `model_unavailable`,
`model_timeout`, ...) shown as honest "could not answer" messages. Success messages appear only
after the server confirms the write.
