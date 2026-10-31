# `tests/` — software test suite

## Layers

- `unit/`: pure functions: CSV validation, text cleaning, page locator handling, chunking, schemas, BKT equations, graph direction/cycle detection, policy rules, retry classification.
- `integration/`: PostgreSQL repository queries, Alembic migration checks, idempotent curriculum import, question/attempt transactions, pgvector query tests. Use an isolated test database, never the owner's working database.
- `e2e/`: full API flows with mocked external providers: authenticated doubt, insufficient-evidence abstention, question attempt, BKT update, teacher authorization, Bell-Ringer approval.
- `fixtures/`: synthetic/permission-safe PDFs, JSON, CSV rows and mocked provider outputs. No real student PII or restricted textbook material.

## Commands

```powershell
python -m pytest tests/unit -q
python -m pytest tests/integration -q
python -m pytest tests/e2e -q
python -m pytest -q
```

## Required edge cases

- Repeated source import and repeated attempt idempotency.
- Missing class/subject context, wrong subject filter, out-of-scope question.
- Empty or contradictory retrieval, fabricated source ID, provider timeout/429/5xx, malformed JSON.
- PDF with no text, OCR failure, wrong language pack, lost equation/table/map, missing page reference.
- Graph self-edge, cycle, orphan endpoint and cross-subject/version mismatch.
- Multi-KC question with no defined per-KC evidence policy.
- Duplicate notes/questions and stale embedding generation.
- Teacher accessing an unassigned classroom.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Automated protection for schemas, pipeline integrity, learning algorithms, API authorization and release flows.

### 2. Recent Updates Incorporated in This Module

Cover source rights filters, multi-KC evidence, idempotent BKT, teacher classroom scoping, Bell-Ringer coverage gate and provider transient-only fallback.

### 3. File Manifest

`unit/`, `integration/`, `e2e/`, `fixtures/`; fixtures contain synthetic, clearly labelled learner data and licensed sample content only.

### 4. Data Structures, Types & Schemas

Use pytest; pytest-asyncio for async tests; HTTPX test client for API; fake provider adapter; disposable DB/index.

### 5. File-by-File Implementation Specification

Pure algorithm tests first; integration tests on isolated schema; E2E full student/teacher flows; data regression fixtures for PDFs/JSON/CSV.

### 6. Integration Points

Tests all app services, API routes, data pipeline, DB migrations, retrieval and evaluation metrics.

### 7. Module Verification Checklist

`pytest -q`; `ruff check .`; `ruff format --check .`; optionally coverage; never delete tests to obtain a pass.


## Teammate CSV quality tests

Add `tests/unit/test_csv_cleaning.py` and `tests/unit/test_csv_validation.py` before implementing the respective stages. Fixtures must cover UTF-8 BOM, Hindi/Unicode, quotes/embedded newlines, leading-zero identifiers, null-token policy, exact/near duplicate distinction, malformed rows, row reconciliation, source/PDF mismatch and idempotent hashes. Do not put real textbook passages or personal learner data into fixtures.

## Current suites (2026-10-31)

```bash
python -m pytest -q tests/unit                               # config, session, ORM, offline migration SQL
python -m pytest -q -rs -m live_db tests/integration         # read-only owner-database comparison
python -m pytest -q -rs -m migration_db tests/integration    # Alembic lifecycle, disposable server only
```

```bash
python -m pytest -q tests/integration/test_teammate_csv_pipeline.py   # CSV pipeline, synthetic fixtures
python -m pytest -q -m real_inventory tests/integration               # real 386-row inventory, outputs in tmp
python -m pytest -q tests/integration/test_extraction_pilot.py      # extraction pilot, synthetic PDFs, paths in tmp
```

Phase 4 unit tests (`test_pdf_extraction.py`, `test_ocr_and_normalization.py`, `test_authorization_and_enrichment.py`, `test_hindi_diagnostics.py`, `test_pilot_enriched_csv.py`, `test_review_triage.py`, `test_inspection_pack.py`, `test_devanagari_repair.py`) build synthetic PDFs, fake glyph pages or tiny CSV/JSON fixtures at runtime. `test_quality_review_records.py` checks the committed AI-assisted review record (coverage; never marked as human review) with `conftest.PdfFactory`. The fixtures use generic sentences only, never textbook text. Tesseract is mocked through an injected command runner, and URL checks use an injected fetcher, so no test needs the network or an OCR install.

**`live_db`**
- Connects with `default_transaction_read_only=on` and reads only system catalogs.
- Includes Alembic's own `compare_metadata`.
- Skipped when `DATABASE_URL` is unset or the server is unreachable.

**`migration_db`**
- Needs `CONCEPTTRAIL_MIGRATION_TEST_ADMIN_URL`, pointing at a disposable server (see `app/db/migrations/README.md`).
- Creates and drops only its own `ct_migtest_*` databases.
- Refuses to run against the `.env` server or any server hosting `concepttrail_db`.
