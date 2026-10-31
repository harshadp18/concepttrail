# `app/core/` — core configuration and cross-cutting concerns

`config.py` loads validated environment settings; `security.py` handles password/token primitives; `logging.py` provides safe structured logs; `errors.py` defines typed errors and safe API mappings. The application must start with clear configuration errors when required settings are absent, without printing secret values.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Cross-cutting configuration, authentication primitives, error mapping and safe logging.

### 2. Recent Updates Incorporated in This Module

Secrets never appear in logs; no names/contact/roll details in LLM prompts; auth identity is derived server-side; teacher assignments checked per request.

### 3. File Manifest

`config.py` settings; `security.py` password hashing/token/session helpers; `logging.py` structured redaction; `errors.py` typed domain exceptions and API mapping.

### 4. Data Structures, Types & Schemas

Settings loaded from environment with typed validation. Required DB URL and production secrets fail fast. Stable error envelope `{error:{code,message,request_id}}`.

### 5. File-by-File Implementation Specification

Use Pydantic Settings; validate secret length in production; hash PIN/password using Argon2id or an explicitly reviewed secure password-hashing scheme; rate-limit login; never print secret values.

### 6. Integration Points

Imported by app startup, API dependencies and services; must not contain BKT or subject-specific logic.

### 7. Module Verification Checklist

Unit tests for missing config, redaction, password hash verify, token expiry, error mapping and brute-force rate limits.

## Implementation status (2026-10-31)

`config.py` is implemented and tested.

- **API:** `Settings` (pydantic-settings; reads the root `.env`; process environment overrides it), `load_settings()`, the cached `get_settings()` and `ConfigurationError`.
- **Safe errors:** `ConfigurationError` reports field names and rules only and never echoes input values (`hide_input_in_errors`).
- **Declared settings:** app, database and secret/JWT settings only. LLM, embedding and data-path keys are ignored until their phases add typed, tested fields.
- **Placeholders:** blank, `CHANGE_ME*`, `SET_AFTER_*` and `SET_TO_*` values count as unset.
- **Database URL:** must use `postgresql+psycopg`.
- **Production:** `APP_ENV=production` requires `DEBUG=false`, `LOG_REQUEST_BODIES=false`, and distinct `SECRET_KEY`/`JWT_SECRET_KEY` of at least 32 characters.

`security.py`, `logging.py` and `errors.py` are not started.
