# Phase 5 owner decision checklist

One review, one pass. For each row write **Approve** (the recommended value becomes your decision), **Change to: …**, or **Defer**. Nothing below is approved until you write it: the engineering is built (see [`PHASE_5_PROGRESS.md`](PHASE_5_PROGRESS.md)) and works with the recommended values, but implementing a value does not approve it. Details live in [`PHASE_5_DECISION_MATRIX.md`](PHASE_5_DECISION_MATRIX.md), [`PHASE_5_CSV_CONTRACT.md`](PHASE_5_CSV_CONTRACT.md) and [`PHASE_5_REVIEW_GUIDELINES.md`](PHASE_5_REVIEW_GUIDELINES.md).

**Already settled by existing instructions (no action):** the two CSV headers and their column order; AI never approves KCs or edges, sets mastery or sets policy; no LLM training; Groq fallback stays disabled and external processing of textbook or student content stays unauthorised; local Qwen drafting needs a separate rights record naming KC and edge drafting (D17's rule); the 26-table schema is unchanged; deterministic code owns prerequisite logic, mastery and policy. These constrain the items below but approve none of them.

**Legend.** Class: **A** an owner decision, recommendation ready; **B** needs a real pilot or human work first; **C** needs real people or custody details. "Without it" says what can still proceed. Every item is **unresolved**.

## 1. Decisions you can settle now (class A)

| ID | Question | Proposed → recommended | Why it matters | Blocks | Your action | Proceed without it? |
|---|---|---|---|---|---|---|
| D1 | KC ID format | `KC-<ENG\|HIN\|MAT\|SCI\|SOC>-<5 digits>`, allocated once, never reused → **approve** | IDs are permanent keys in 7 tables | real review, release, import | Approve or give another format | Yes, with synthetic data |
| D2 | Stable keys: `<subject>.<domain>.<concept>[.<facet>]`, class-independent, aliases never edit a key | as proposed → **approve** | the permanent human lookup for a concept | real review, release, import | Approve the convention | Yes |
| D3 | `learning_objective` stored in `knowledge_component.description` (no column for it) | as proposed → **approve** (approved in principle earlier) | the only place an objective can live without a schema change | **import only** | Confirm | Yes, through release |
| D5 | Difficulty tier 1–5, optional, no logic uses it | as proposed → **approve** | avoids a premature difficulty scale | nothing | Approve | Yes |
| D6 | Misconceptions as JSON `{"id":"m1","text":…}` (ids never reused) | as proposed → **approve** (approved in principle earlier) | stable references for later question mapping | real review, release, import | Confirm | Yes |
| D7 | Source tokens `src:<source_id>@<page>[:para<N>]#<sha12>`, locator required on edge evidence | as proposed → **approve** | traceability to document, version, page, passage, digest | real review, release, import | Approve | Yes |
| D8 | Three digests; versions bump only for pedagogical changes (field classes P/S/C) | as proposed → **approve** | decides what makes an approval stale | real review, release, import | Approve the P/S/C table | Yes |
| D9 | Dependency basis: `uses_concept`, `uses_procedure`, `uses_vocabulary`, `uses_representation`, `expert_judgement`; `chapter_order` prohibited | as proposed → **approve** (approved in principle earlier) | stops sequence being mistaken for dependency | real review, release, import | Confirm | Yes |
| D10 | Edge strength 1–3, optional, unused until Phase 9 | as proposed → **approve** | avoids implying a weight no policy uses | nothing | Approve | Yes |
| D13 | Staleness and reaffirmation: endpoint version change stales edges; a human reaffirmation (two reviewers) is the only way back | as proposed → **approve** | stops silent carry-over of approvals | real review, release, import | Approve | Yes |
| D14 | A blanket owner attestation can record that a review round finished but never approves a KC or edge | as proposed → **approve** (approved in principle earlier) | the line between finished and approved | real review, release, import | Confirm | Yes |
| D16 | Private data locations and Git ignore rules | rule already added and verified → **approve** | keeps curated data out of Git | nothing | Approve | Yes |
| D18 | `declared_class_levels` is the author's declaration, not a curriculum mapping; `scope=foundation` KCs have no class and are reported separately | as proposed → **approve** | class coverage you can trust | real review, release, import | Approve | Yes |
| R3 | Confirm every proposed domain and facet entry (contract section 4) | the list as written → **review each entry**; the likely discussions are algebra/equations/polynomials, matter/atoms-molecules, ecosystems/natural-resources, whether Hindi needs its own domains | closed vocabulary; a model may never add an entry | real review, release (the loader refuses a non-confirmed file) | Mark each domain and facet Approve / Change / Remove | Yes (built-in provisional list) |
| R5 | Block (not just warn) a reviewer who authored an endpoint KC? | warn only for the pilot → **approve** | independence strictness | nothing | Choose warn or block | Yes |
| R7 | Who edits the vocabulary file | the owner only; each change bumps its version → **approve** | stops silent vocabulary growth | release | Approve | Yes |
| D15 (part) | Retirement is a separate lifecycle log, no `retired` review status, no automatic mastery transfer | as proposed → **approve** the sidecar and the fail-closed snapshot | how a KC leaves the graph without a schema change | runtime use, import | Approve | Yes |

## 2. Decisions that need a pilot or human work first (class B)

| ID | Question | Proposed | Recommended | Blocks | Your action | Proceed without it? |
|---|---|---|---|---|---|---|
| D4 | Skill taxonomy (`concept`, `procedure`, `fact`, `vocabulary`, `application`, `interpretation`) | provisional list | run the 30-skill assessment with two independent human reviewers (tooling ready: `taxonomy-forms`, `taxonomy-score`); set thresholds first (R6) | freezing the list; real review uses the provisional list meanwhile | Name two reviewers; decide whether to accept the provisional list or wait for the result | Yes, provisional |
| D11 | How much evidence an approved edge needs; how often `expert_judgement` will be needed | pilot rule: a located `supports: yes` passage for `uses_*`; two separate expert rationales for `expert_judgement` | run the ~100-edge, ~20-per-subject pilot (tooling ready: `evidence-score`); per-subject results are indicative only (about ±22 points) | making the rule permanent | Provide authors and reviewers; set thresholds first (R6) | Yes, pilot rule |
| R6 | Thresholds (for example a kappa floor for D4; any relaxation of the two-reviewer rule) | none set; 0.6 kappa is a reference convention only | set them **before** seeing results | declaring D4 or D11 passed | Write the numbers down first | Yes |
| D15 (part) | Whether old mastery seeds a replacement KC | none; no automatic transfer | decide in the Phase 9 policy design | retirement of a KC that students have practised | Defer to Phase 9 | Yes |

## 3. Needs real people or custody details (class C)

| ID | Question | Proposed → recommended | Blocks | Your action |
|---|---|---|---|---|
| R4 | Who are the reviewers; the register; your verification | codes `RV-001`…, subjects and roles only, no names in the repository → **create `people.json`**, then run `register-verify` with your own statement | all real review, release, import | Decide the people (at least two qualified per subject); create the register; sign the verification |
| R2 | Anchor custody: two locations, key holders, cadence | an owner-controlled offline encrypted backup plus a separate encrypted store under different credentials; anchor after each session and each release → **name both** in `custody.json` (absolute paths outside the repository) | release (the loader refuses without two anchored copies) | Designate both locations and key holders. **No second custodian has been designated; none was invented** |
| R1 | How the released graph snapshot reaches the runtime | a deployed, access-controlled artifact verified on load → **approve** | runtime use and import | Choose the delivery mechanism |
| D12 | Review integrity, independence, custody as a whole | built as specified → **approve** once R2, R4, R5 are settled | real review, release | Approve |

## 4. Gates that stay closed until the above are done

| Gate | Needs | Status |
|---|---|---|
| **D17** local Qwen drafting from textbook content | an owner-created rights record naming `local_llm_kc_drafting` and `local_llm_prerequisite_edge_drafting`; Hindi excluded until evaluated | **Closed.** No record exists; the gate refuses; the adapter is mock-tested only. Optional: nothing else depends on it |
| External provider processing (Groq, others) | rights review of terms, retention and location, then a rights record | **Not authorised.** Fallback stays disabled |
| Real KC and edge curation | D1, D2 (R3), D6, D7, D8, D9, D13, D14, D18; R4; a D4 decision | Not started |
| Graph release | the above + two independent human approvals per edge + R2 custody + R7 + a confirmed vocabulary file | Not started |
| Learning-content database import | a released real snapshot, D3, R1, a rehearsal on a disposable PostgreSQL, and **your separate approval of one exact plan** | Not started |

## 5. Items outside the D/R list (answered by this task, for the teammate to confirm)

| Item | What the dev seed used | Please confirm |
|---|---|---|
| Role codes in `role` | `student`, `teacher` (the table was empty; the codes were not defined anywhere) | teammate: same codes in the API |
| `teacher_class_assignments.assigned_role` | `class_teacher` | teammate |
| Argon2id parameters | `argon2-cffi` defaults (m=65536 KiB, t=3, p=4); hashes are PHC strings, so any Argon2 verifier works whatever its own defaults | teammate: keep, or change the parameters and rehash |
| Synthetic marker | login `dev-student-001`, school email on `.invalid`, `school_label` and display name `SYNTHETIC-DEV-ONLY` (the schema has no synthetic flag) | none |

## 6. What to do, in order

1. Fill sections 1 and 2 (one sitting).
2. Section 3: create the register and name the two custody locations.
3. Optional now or later: a D17 rights record, only if you want local drafting.
4. Then people can start: pilots, curation, review. Release and import wait for real approvals; they are never implied by this checklist.
