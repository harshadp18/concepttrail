# `app/schemas/` — Pydantic schema package

Create Pydantic v2 schemas by domain: API common, curriculum, content, question/attempt, learner/progress, teacher/Bell-Ringer and LLM output. Keep them distinct from SQLAlchemy ORM models. Never expose expected answers to students and never accept client-supplied authoritative scores or mastery values.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Pydantic v2 schemas for API and generated content contracts.

### 2. Recent Updates Incorporated in This Module

Keep API DTOs separate from ORM; prohibit client-supplied score/mastery/learner authority; validate source IDs and structured generation output.

### 3. File Manifest

Domain schemas: common errors/pagination; auth; curriculum/topic; source citation; doubt; question/options/attempt; learner progress; teacher summary/Bell-Ringer draft; LLM output.

### 4. Data Structures, Types & Schemas

Doubt response contains answer, database-derived sources, grounding status, needs_teacher and content version. Attempt request includes question/version/answer/idempotency key only.

### 5. File-by-File Implementation Specification

Use strict Pydantic models, enums and bounded strings/numbers; forbid unknown authoritative fields; model generated outputs with explicit schema version.

### 6. Integration Points

Imported by routes/services/verifier; no DB engine dependency.

### 7. Module Verification Checklist

Schema tests for valid/invalid payloads, injection-like check_expr rejection, forbidden `correct`/`mastery` fields and citation ID validation.
