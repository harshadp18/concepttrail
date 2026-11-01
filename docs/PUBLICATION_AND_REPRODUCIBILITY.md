# Publication policy and fresh-clone reproducibility

What a public checkout contains, what stays private, and how the private inputs are supplied. Nothing here is a legal opinion. Public decisions are in [`PUBLIC_DECISIONS.md`](PUBLIC_DECISIONS.md).

## 1. What a fresh clone can do

A fresh clone contains every source module, test and published document. It does not contain the private inputs in section 3, so it **cannot run the extraction pipeline end to end**. That is by design.

On a clean copy of exactly the publishable files (no `.env`, no private records, no PDFs) the default test suite runs with **0 failures**. Tests that need a live database, a disposable migration server, the real inventory or a private owner record skip, each with a stated reason. A test checks that published documents contain no broken links and no pointers to private documents (`tests/unit/test_public_docs.py`).

## 2. Publication boundary, file by file

| File or folder | Status | Why |
|---|---|---|
| `app/`, `data_pipeline/*.py`, `data_pipeline/stages/`, `tests/`, `evaluation/`, `db/`, `deploy/`, `.env.example`, `pyproject.toml` | **Public** | Source and synthetic fixtures; `.env.example` holds placeholders only |
| `data_pipeline/teacher_validation.py`, `data_pipeline/owner_attestations.py` | **Public** | Imported by published pipeline modules; they contain rules, not private records |
| `docs/` (specifications, `PUBLIC_DECISIONS.md`, `PROVIDER_READINESS.md`, this file) | **Public** | No secrets, personal paths or source text |
| `docs/DECISIONS.md`, `docs/SOURCE_AUDIT.md`, `docs/reports/` | **Private** | The owner's internal decision register, source audit and phase reports. Not linked from public files |
| `data_pipeline/data/overrides/**` except READMEs | **Private** | Owner attestations, authorisation records, review records, AI-generated drafts |
| `data_pipeline/data/overrides/metadata_enrichment/official_learning_outcomes.json` | **Private pending a rights review** | Verbatim curriculum text; publishing it is a redistribution decision |
| `data_pipeline/data/{raw,interim,processed,logs,final}/**` except READMEs | **Private** | Textbook-derived text, titles and generated data |
| `data_pipeline/data/overrides/content_review/**` (review records, `patch_v1.json`) | **Private pending a rights review** | AI-drafted question text and fixes written against specific textbook chapters. The loader and patch code in `data_pipeline/content_review/` are public; without the records the patch commands refuse and `test_content_review.py` skips |
| `frontend/` | **Public** | Application code, original SVG illustrations and the official logo; `.env.development.local` and `node_modules/` are ignored |
| `resources/textbook_pdfs/`, `resources/teammate_csv/**`, `.env` | **Never published** | Copyrighted PDFs, teammate data, secrets |

Do not force-add ignored folders. The `.gitignore` rules encode this policy. Git and Ruff both skip ignored files, so a source file must never be ignored: an ignored `teacher_validation.py` once hid code that published modules import.

## 3. Runtime dependencies on private files

| Private input | Read by | If absent |
|---|---|---|
| `overrides/authorizations/*.json` | `authorization.check_use`, every processing stage, the pilot CSV builder | **Fails closed.** Every use is refused; nothing is processed |
| `overrides/metadata_enrichment/teacher_validation_attestation_2026-10-31.json` | `run_extraction_pilot` | **Reported, never assumed.** Statuses stay `pending_teacher_review`; the provenance manifest records `teacher_validation.status` (`attestation_absent` or `attestation_does_not_bind`) and a warning is printed |
| `overrides/metadata_enrichment/d053_page_review_attestation_2026-10-31.json` | `run_extraction_pilot`, `triage_review_queue` | **Fails closed.** `absent`, `stale` (bound evidence changed) or `invalid` all mean the page review does not count as completed; queue items stay open |
| `overrides/metadata_enrichment/phase4_pilot_signoff_2026-10-31.json` | `python -m data_pipeline.owner_attestations verify` | Verification reports `absent`, `stale` or `invalid`; nothing is treated as approved |
| `overrides/metadata_enrichment/ai_generated_learning_objectives.json`, `owner_decisions_2026-10-31.json` | pilot runner, CSV builder, triage | No AI objectives; no extraction-status or acquisition-date updates; items stay open |
| `overrides/quality_review/*` | D-053 attestation binding; `test_quality_review_records.py` | Attestation cannot be verified; the test skips with a reason |
| PDFs, teammate CSV, Phase 3 outputs | pipeline, real-inventory test | Pipeline refuses; the test skips |

## 4. Supplying the private records securely

1. The owner transfers the private `overrides/` files by a private channel (an encrypted archive or a private store), never through the public repository.
2. Before use, verify the SHA-256 values below. The pipeline also records the attestation digests in its manifests.

   | File | SHA-256 |
   |---|---|
   | `teacher_validation_attestation_2026-10-31.json` | `d45e84ef30c4231feae76ee3ed73149bd47bf4811c1b20509d1b9a499423c5ba` |
   | `d053_page_review_attestation_2026-10-31.json` | `6dab5d9fb23b9b147aba17efe8f69b6ef76903091cdc15005898665a25f7b8b6` |
   | `phase4_pilot_signoff_2026-10-31.json` | `807f34abe297525cfdf4be23d453987ee6d0dddb0fcb5746312c1dcdf3cb5222` |
   | `ai_generated_learning_objectives.json` (original, unedited) | `7b6de7f1c9c3ecdef68720da11392c1bbd72ca762ce3ae9ea84299618e39acb6` |

3. **Do not regenerate the attestations** on another machine. They record the owner's own confirmations. The `record` commands can reproduce the same bytes from the same evidence, but only the owner runs them; anyone else would be manufacturing an owner attestation. They are write-once and refuse to overwrite.
4. Run `python -m data_pipeline.owner_attestations verify`. All three records must report `valid`. A `stale` result means evidence the record was bound to has changed.
5. The attestations record completion and approval of the pilot only. They do not approve any individual page, objective or topic.
