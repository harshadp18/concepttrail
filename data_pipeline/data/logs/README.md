# Pipeline logs

Store structured logs and stage diagnostics with job ID, source ID, stage name/version, status and safe error summary. Do not write API keys, passwords, student data or full protected source text into logs. Apply retention limits.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Machine-readable diagnostics for ingestion and review operations.

### 2. Recent Updates Incorporated in This Module

Never log credentials, full student identifiers or unnecessary protected source text.

### 3. File Manifest

Per-run JSONL event logs, stage report JSON and aggregate coverage report outputs.

### 4. Data Structures, Types & Schemas

Events include job/run ID, source ID, stage/version, status, timestamps, counts and safe error code.

### 5. File-by-File Implementation Specification

Structured logger with bounded error excerpts and redaction; separate audit events from debug logs.

### 6. Integration Points

Written by every pipeline stage; read by retry and coverage-report tools.

### 7. Module Verification Checklist

Redaction tests, malformed event handling and failed-job traceability.
