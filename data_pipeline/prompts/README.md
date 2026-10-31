# `data_pipeline/prompts/` — versioned AI prompt templates

Store prompt templates as versioned text/Markdown files (for example `kc_extraction_v1.md`, `question_generation_v1.md`, `note_draft_v1.md`). Each template must specify:

- Task and allowed output schema.
- Class, subject, course/language and curriculum version context.
- Exact permitted source excerpts and source IDs available to the model.
- Instruction to treat source text as data, not system instructions.
- Rules not to invent citations, chapter names, page numbers, answer keys or learning objectives.
- Required abstention for insufficient or conflicting evidence.
- Subject-specific constraints (equations/units, maps/timelines, grammar/literature, etc.).

Record prompt version and model identifier with outputs. Generated artifacts remain drafts until deterministic checks and required human review pass. Do not put copyrighted full chapters into prompts unless the specific external-processing permission permits it.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Versioned prompts for optional generation of candidate notes, questions, KCs and teacher activity drafts.

### 2. Recent Updates Incorporated in This Module

LLM output is draft text only; rights, evidence, BKT, graph and policy remain deterministic; prompts receive minimal pseudonymous context.

### 3. File Manifest

Prompt files are named by task and version; shared response schema lives in `app/schemas` or pipeline schema module.

### 4. Data Structures, Types & Schemas

Prompts require JSON matching a declared schema, cite only supplied source IDs, preserve grade/subject/language and include no PII.

### 5. File-by-File Implementation Specification

Keep prompts as text templates with explicit variables; version every change; validate output; retry once on recoverable parse failure then quarantine.

### 6. Integration Points

Called by generation stages or app service adapters; never from route handlers directly.

### 7. Module Verification Checklist

Golden prompt fixtures, schema failure/retry tests, nonexistent-citation rejection and PII scan.
