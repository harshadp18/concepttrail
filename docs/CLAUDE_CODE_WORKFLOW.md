# Claude Code workflow in a VS Code workspace

## 1. Open the repository

1. Extract the ZIP to a local project folder.
2. Open that folder (the folder containing `CLAUDE.md` and root `README.md`) in VS Code.
3. Install/enable the Claude Code extension or CLI according to the current official docs.
4. Confirm Claude Code can see the workspace root and terminal. Start with read-only reconnaissance; do not authorize destructive shell/database actions.

Claude Code uses project instructions such as root `CLAUDE.md` for persistent repository context. Keep that file concise and commit it. Module-specific `app/CLAUDE.md` and `data_pipeline/CLAUDE.md` hold targeted constraints when Claude works in those paths. See the official [Claude Code memory docs](https://code.claude.com/docs/en/memory) and [VS Code guide](https://code.claude.com/docs/en/vs-code).

## 2. First prompt to Claude Code

```text
Read CLAUDE.md and README.md, then read docs/SOURCE_AUDIT.md,
docs/DECISIONS.md, docs/DATABASE_SCHEMA.md and the module README
for every area you inspect. Do not edit files or run database DDL yet.
Inspect this repository, Python environment, Git status, current
FastAPI/API code, ORM models, Alembic history, tests, and the actual
PostgreSQL schema. If frontend code exists, inspect it read-only and do not
create or modify any frontend code. Report existing / partial / missing items, compare
the live DB to the 26-table contract, and propose a phased implementation
plan. Do not delete, reset, or overwrite data.
```

## 3. Phase-specific prompts

### Database baseline

```text
Implement only the DB connectivity and ORM baseline after the live
schema has been introspected. Match the actual concepttrail schema.
Do not rerun db/schema/001_initial_schema.sql. Create SQLAlchemy 2.x
models, configure Alembic, verify autogenerate on a disposable test DB,
and describe the baseline/stamp plan before touching the user's DB.
Add connection and repository integration tests.
```

### Curriculum importer

```text
Profile, clean and validate the teammate CSV in resources/teammate_csv/incoming/. Read docs/CSV_CLEANING_SPEC.md. Snapshot the original bytes, preserve columns/order and identifiers, emit accepted/rejected outputs and a reconciled quality report. Only map into the single-master data_pipeline/curriculum.csv after purpose and all field mappings are reviewed. Never create resources.csv or sources.yaml. The canonical header has exactly 29 columns. Validate all 25 class-subject combinations, stable IDs, source
rights fields and references. Make import idempotent and emit a coverage
report. Do not import or process any source that fails the rights gate.
```

### PDF extraction

```text
Implement the PDF extraction pipeline using PyMuPDF first and Tesseract
only for flagged scanned pages. Preserve source hash, PDF page index,
printed page label, chapter boundaries, equations, tables, assets and
review status in raw/cleaned JSON. Do not send content to external AI
providers unless its rights explicitly allow that use. Add fixtures and
QC tests before expanding to all classes and subjects.
```

### BKT and graph

```text
Implement and test BKT online updates, graph direction/cycle validation,
and deterministic next-action policy. Use only server-scored attempts
and versioned BKT configuration. Do not add LLM calls to BKT or use
synthetic data as real learner evidence. Explain how multi-KC questions
are scored before updating multiple mastery states.
```

### Retrieval and LLM

```text
Implement retrieval only after an embedding model/dimension is selected
from a benchmark. Use pgvector and hard filters for class, subject,
curriculum version, language, publication/review and permission status.
Add a provider-neutral Gemini-primary / Groq GPT-OSS fallback interface;
DeepSeek stays a challenger until approved. Fallback only on transient
provider failures. Validate structured outputs and source IDs before
returning them. Mock providers in tests.
```

## 4. Required agent completion report

At the end of each phase, report:
- Files created/changed.
- Behavior implemented (not planned behavior).
- Commands and tests actually run, with results.
- DB migrations generated/applied or intentionally not applied.
- Known gaps, assumptions and owner decisions required.
- Security/rights implications.
- Next smallest safe task.

## 5. Permission discipline

Claude Code may edit code and run safe local tests. Require owner confirmation before: destructive DB commands, deleting/replacing source files, downloading/processing copyrighted sources, sending real learner data or restricted content to external providers, creating paid provider resources, deploying, rotating secrets, or running irreversible migrations.


### Teammate CSV cleaning and PDF cross-check

```text
Read resources/README.md and docs/CSV_CLEANING_SPEC.md. The user has copied original PDF resources to resources/textbook_pdfs/ and teammate CSV exports to resources/teammate_csv/incoming/. First create a byte-identical hash-addressed raw snapshot. Profile that snapshot without modifying it, then write a data-quality report. Do not assume the CSV is the curriculum inventory. Define explicit schema, field mapping, null-token and duplicate rules from the actual file. Preserve source columns/order, leading-zero IDs and Unicode. Write accepted and rejected records separately with reason codes and reconcile every input row. Compare selected values against the matching PDFs only after confirming the source pairing and permitted internal processing. Keep mismatches for human review; do not autofill. Do not overwrite the raw files or data_pipeline/curriculum.csv. Add fixtures and idempotency tests.
```

### Backend-only scope

```text
Implement backend, database, data pipeline, AI/RAG, BKT, graph/policy, teacher services, API contracts, testing, evaluation and deployment documentation. Do not build or modify frontend code. Produce OpenAPI and docs/FRONTEND_INTEGRATION.md for the frontend the owner will build separately.
```
