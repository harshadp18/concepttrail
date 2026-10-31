# Repositories

Add focused repository modules for curriculum/source, content/KC, question bank, learner/attempt/mastery, classroom/teacher, and ingestion jobs. Repositories own database queries/persistence only. Do not put HTTP responses, prompt templates or provider calls here. Enforce stable ordering and pagination; use explicit transactions from services for multi-table operations.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Typed database query/persistence methods; no HTTP/provider logic.

### 2. Recent Updates Incorporated in This Module

Always include class/teacher scope; idempotent attempt lookup; source rights/review/index filters; preserve the exact `embedding_chunk` table shape.

### 3. File Manifest

Repository modules by domain: subject/curriculum/source/content/KC/question/attempt/learner/mastery/classroom/ingestion/vector; create a module only when needed.

### 4. Data Structures, Types & Schemas

Methods accept typed IDs/filter DTOs and return domain records; session passed explicitly. Do not accept client identity as authority.

### 5. File-by-File Implementation Specification

Keep SQLAlchemy expressions in repositories; eager-load deliberately; page large queries; make attempt+mastery transaction coordination explicit in service layer.

### 6. Integration Points

Called only by services/importers; must not import FastAPI or LLM provider SDKs.

### 7. Module Verification Checklist

Repository integration tests with isolated PostgreSQL schema; test foreign-key scope, pagination, no cross-class visibility and idempotency.
