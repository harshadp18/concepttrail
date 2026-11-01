# Phase 5 decision matrix D1–D18 (revision 4: implemented, not approved)

Final dispositions for the Phase 5 data contract and review policy. **No decision is converted into an owner approval by this document.** Earlier "approved in principle" statements (D3, D6, D9, D14) stay exactly that. The only thing approved by explicit owner instruction is the exact header names and column order of the two CSVs.

Dispositions use the owner's vocabulary:

| Disposition | Meaning |
|---|---|
| **Owner-instructed** | an explicit owner instruction exists (CSV headers and order only) |
| **Recommended** | final proposed value, ready for the owner's explicit approval |
| **Owner choice** | a specific choice the owner still has to make (listed as R1–R7) |
| **Investigation** | needs empirical evidence before it can be frozen |
| **Separate authorisation** | needs a separate rights record or owner approval that does not exist |

"Frozen" means no ordinary design question is left open, so the loader can be built against the proposed value without further design discussion. Every limit-setting value lives in one constants module in the loader, so an owner change is a one-line edit.

Details: [`PHASE_5_CSV_CONTRACT.md`](PHASE_5_CSV_CONTRACT.md), [`PHASE_5_REVIEW_GUIDELINES.md`](PHASE_5_REVIEW_GUIDELINES.md), build order in [`PHASE_5_IMPLEMENTATION_HANDOFF.md`](PHASE_5_IMPLEMENTATION_HANDOFF.md).

## Master table

"Loader build" is whether the CSV loader can be implemented against the proposed value now. "Real data" is whether curating or reviewing **real** records needs the decision approved first.

| ID | Topic | Disposition | Loader build | Real data | DB import | AI drafting |
|---|---|---|---|---|---|---|
| D1 | KC ID format | Recommended | ready | approve first | n/a | n/a |
| D2 | Stable keys, domains, facets, aliases | Recommended; **Owner choice R3** (confirm each list entry) | ready (lists read from a file) | **blocked until R3** | n/a | no AI may add entries |
| D3 | Objective in `description` | Recommended (approved in principle earlier) | ready | n/a | **blocks import only** | n/a |
| D4 | Skill taxonomy | **Investigation** (appendix A) | ready with the provisional list | taxonomy not frozen | n/a | n/a |
| D5 | Difficulty tier | Recommended | ready | n/a | n/a | n/a |
| D6 | Misconception objects | Recommended (approved in principle earlier) | ready | approve first | n/a | n/a |
| D7 | Source-reference grammar | Recommended | ready | approve first | n/a | n/a |
| D8 | Digests and versioning | Recommended | ready | approve first | n/a | n/a |
| D9 | Dependency basis | Recommended (approved in principle earlier) | ready | approve first | n/a | n/a |
| D10 | Edge strength | Recommended | ready | n/a | n/a | n/a |
| D11 | Evidence sufficiency | Rules: Recommended. Pilot: **Investigation** (appendix B) | ready | pilot informs the permanent rule | n/a | n/a |
| D12 | Review integrity, independence, custody | Recommended; **Owner choice R2, R4, R5** | ready (synthetic data) | **blocked until R2 and R4** | n/a | n/a |
| D13 | Staleness and reaffirmation | Recommended | ready | approve first | n/a | n/a |
| D14 | Blanket attestation cannot approve | Recommended (approved in principle earlier) | ready | approve first | n/a | n/a |
| D15 | KC retirement, runtime visibility | Recommended sidecar; **Owner choice R1**; mastery transfer: **Investigation** | ready | n/a | **blocks runtime consumption and import** | n/a |
| D16 | File locations, Git safety | Recommended; ignore rule **added and verified** | ready | ready (rule exists) | n/a | n/a |
| D17 | Local Qwen drafting | **Separate authorisation** | n/a | n/a | n/a | **blocks AI drafting only** |
| D18 | Class coverage, foundation KCs | Recommended | ready | approve first | n/a | n/a |

**Nothing blocks loader implementation.** What blocks use with **real** data is, precisely: approval of D1, D2 (and every list entry, R3), D6, D7, D8, D9, D13, D14; the custody and register arrangements (R2, R4); and a decision on D4 (provisional list or the assessment).

**Remaining owner choices**

| ID | Choice | Proposed value |
|---|---|---|
| R1 | How the released graph snapshot reaches a remote runtime | a deployed, access-controlled artifact, verified at load |
| R2 | Anchor custody: which two locations, key holders, cadence | owner-controlled offline encrypted backup plus a separate encrypted store under different credentials; after each session and each release |
| R3 | Confirm each proposed domain and facet entry | contract, section 4 |
| R4 | Who the reviewers are; the register and its verification | owner creates the register and signs the verification |
| R5 | Is a reviewer who authored an endpoint KC blocked (not just warned)? | warn only for the pilot |
| R6 | Thresholds for the taxonomy test and for any relaxation of the two-reviewer rule | the owner sets them before results are seen |
| R7 | Who edits the vocabulary file | the owner only; each change bumps its version |

---

## Implementation decision register (revision 4)

The engineering is implemented and tested on synthetic data (see [`PHASE_5_PROGRESS.md`](PHASE_5_PROGRESS.md)). **Implementing a recommended value does not approve it**; every disposition above and below is unchanged. "Blocks" means the operation must not be performed on **real** data until the decision is resolved; "no" means the tooling handles it safely today (a provisional value is labelled, or the operation fails closed).

| ID | Current status | Parsing | Dry run | Human review | Graph release | DB import | AI drafting |
|---|---|---|---|---|---|---|---|
| D1 | Recommended | no | no | **blocks** | **blocks** | **blocks** | no |
| D2 | Recommended; R3 open | no (built-in provisional lists) | no | **blocks** (R3) | **blocks** (`VOCABULARY_NOT_CONFIRMED`) | **blocks** | no (drafts are validated against the lists; nothing is added) |
| D3 | Approved in principle | no | no | no | no | **blocks** | no |
| D4 | Investigation | no (provisional list) | no | **blocks** (provisional list or assessment) | **blocks** (vocabulary file) | **blocks** | no |
| D5 | Recommended | no | no | no | no | no | no |
| D6 | Approved in principle | no | no | **blocks** | **blocks** | **blocks** | no |
| D7 | Recommended | no | no | **blocks** | **blocks** | **blocks** | no |
| D8 | Recommended | no | no | **blocks** | **blocks** | **blocks** | no |
| D9 | Approved in principle | no | no | **blocks** | **blocks** | **blocks** | no |
| D10 | Recommended | no | no | no | no | no | no |
| D11 | Rules recommended; pilot not performed | no | no | no (pilot rule applies) | no (pilot rule applies) | no | no |
| D12 | Recommended; R2, R4, R5 open | no | no | **blocks** (R2, R4) | **blocks** (`CUSTODY_NOT_CONFIGURED`, `REGISTER_NOT_VERIFIED`) | **blocks** | no |
| D13 | Recommended | no | no | **blocks** | **blocks** | **blocks** | no |
| D14 | Approved in principle | no | no | **blocks** | **blocks** | **blocks** | no |
| D15 | Recommended; R1 open; mastery transfer an investigation | no | no | no | no (snapshot is written) | **blocks** (with R1) | no |
| D16 | Recommended; rule added and verified | no | no | no | no | no | no |
| D17 | Separate authorisation; no record exists | no | no | no | no | no | **blocks** (the gate refuses) |
| D18 | Recommended | no | no | **blocks** | **blocks** | **blocks** | no |
| R1 | Owner choice open | no | no | no | no | **blocks** runtime use | no |
| R2 | Owner choice open; no custody designated | no | no | **blocks** | **blocks** | **blocks** | no |
| R3 | Owner choice open | no | no | **blocks** | **blocks** | **blocks** | no |
| R4 | Owner choice open; no register exists | no | no | **blocks** | **blocks** | **blocks** | no |
| R5 | Owner choice open (warning today) | no | no | no | no | no | no |
| R6 | Owner choice open | no | no | no | no | no | no (blocks freezing D4 and D11) |
| R7 | Owner choice open | no | no | **blocks** (who edits the vocabulary) | **blocks** | no | no |

Database import additionally needs a **separate, explicit owner approval of one exact plan** (`import_plan.py`), which is never implied by any decision above.


## D1: KC identifier format. *Recommended*

- **Final value:** `KC-<SUBJ>-<5 digits>`, `<SUBJ>` ∈ `ENG HIN MAT SCI SOC`; allocated once, never reused; example `KC-MAT-00042`.
- **Rationale:** readable, sortable, subject-coded like inventory IDs; UUIDs are unreadable in review; the code is cross-checked against `subject_id`.
- **CSV / schema:** `kc_id` → `knowledge_component.kc_id` (`VARCHAR`; no change). The service accepts any non-blank ID, so the pattern is a loader rule.
- **Depends on:** a single allocator (tool or person).
- **Acceptance:** a test rejects duplicates, a wrong pattern and a subject-code mismatch.

## D2: Stable keys, vocabularies, aliases. *Recommended; owner choice R3*

- **Final value:** `<subject>.<domain>.<concept>[.<facet>]`; the closed domain lists for the five subjects and the facet list in contract section 4; aliases in the `aliases` column.
- **Rationale:** names the concept, not the display wording, so it survives rewording; excludes class; two similar names stay distinct by subject and domain; version and aliases are separate. A closed list stops two authors inventing two spellings.
- **CSV / schema:** `stable_key` → `knowledge_component.stable_key` (unique). `aliases` is a sidecar. Lists live in one private owner-maintained file.
- **Depends on:** R3 (every list entry is unconfirmed); R7 (who edits the file). A model may not create entries; an unknown value is a blocking error.
- **Acceptance:** tests for the pattern, the closed lists, uniqueness across keys and aliases, class-token rejection and `SIMILAR_KEY` warnings, using synthetic keys.

## D3: Objective stored in `description`. *Recommended (approved in principle earlier)*

- **Final value:** `knowledge_component.description` holds exactly the one-sentence objective.
- **Rationale:** no objective column exists; avoids a migration.
- **CSV / schema:** `learning_objective` → `description`. No migration.
- **Depends on:** nothing for the loader. **Blocks database import only.**
- **Acceptance:** the import plan maps the column; a test covers the mapping.

## D4: Skill taxonomy. *Investigation*

- **Final value (provisional):** `concept`, `procedure`, `fact`, `vocabulary`, `application`, `interpretation`, held in the vocabulary file.
- **Rationale:** reasonable starting point; language and Social Science skills may fit poorly. Appendix A is the blind assessment.
- **CSV / schema:** `kc_type` → `knowledge_component.kc_type` (free text, nothing consumes it). Changing the list needs no migration.
- **Depends on:** the appendix A assessment by two independent human reviewers (**not performed**).
- **Acceptance (to freeze):** appendix A, "evidence needed before freezing".

## D5: Difficulty tier. *Recommended*

- **Final value:** optional integer 1–5, relative within the subject; not a BKT parameter, not question difficulty; no logic uses it until calibrated against real responses.
- **Rationale:** an unanchored number is weak evidence; keeping it optional costs nothing.
- **CSV / schema:** `difficulty_tier` → `knowledge_component.difficulty_tier` (`SmallInteger`); the upper bound is a loader rule; an S field.
- **Depends on:** nothing.
- **Acceptance:** tests for range and emptiness.

## D6: Misconception objects. *Recommended (approved in principle earlier)*

- **Final value:** JSON array of `{"id","text"}`; `id` like `m1`, unique in the KC and never reused; `text` non-empty and distinct.
- **Rationale:** lets feedback and questions point at `kc_id` plus misconception `id` instead of relying on text.
- **CSV / schema:** one JSON cell → `knowledge_component.misconceptions` (JSONB). No change.
- **Depends on:** nothing. **Acceptance:** tests for valid JSON, ID pattern, uniqueness and non-reuse.

## D7: Source-reference grammar. *Recommended*

- **Final value:** `src:<source_id>@<pdf_page_index>[:para<N>]#<sha12>`; the locator is required on edge evidence, the pin always (contract, section 6).
- **Rationale:** traces to source document, edition (via the inventory), page, passage and exact bytes; a generic mention is not evidence.
- **CSV / schema:** `source_refs`, `evidence_refs` are sidecar columns; later `content_unit_kcs` for KC sources. No change.
- **Depends on:** the accepted inventory and extraction artifacts available locally. **Acceptance:** tests for grammar, unknown or rights-blocked source, range, pin mismatch and stale passage digest.

## D8: Digests and versioning. *Recommended*

- **Final value:** full digest, pedagogical digest and `content_version` kept distinct; field classes P/S/C (contract, section 7); a clerical confirmation for every non-substantive correction; a version bump only for a P-field change.
- **Rationale:** corrections stay documented and cheap; substantive changes cannot hide as clerical.
- **CSV / schema:** `content_version` → `knowledge_component.content_version`. The service knows nothing of digests (loader logic).
- **Depends on:** the review log. **Acceptance:** tests that each field class produces its stated effect and that a clerical event on a P change is refused.

## D9: Dependency basis. *Recommended (approved in principle earlier)*

- **Final value:** `uses_concept`, `uses_procedure`, `uses_vocabulary`, `uses_representation`, `expert_judgement`; `chapter_order` prohibited; the expert rationale is written inside the approving events.
- **CSV / schema:** `dependency_basis`, sidecar.
- **Rationale and acceptance:** gives each edge a defined question; tests for the vocabulary, `FORBIDDEN_BASIS`, no `rev:` in the CSV, and no circular reference.
- **Depends on:** nothing.

## D10: Edge strength. *Recommended*

- **Final value:** `1` helpful, `2` important, `3` essential; optional; unused by any logic until the Phase 9 policy design.
- **CSV / schema:** `strength` → `kc_edge.strength` (`SmallInteger`); ignored by the service; an S field.
- **Rationale and acceptance:** minimal and clear; tests for range.
- **Depends on:** nothing.

## D11: Evidence sufficiency. *Rules recommended; pilot is an investigation*

- **Final value (pilot):** two independent qualified approving events; for `uses_*` at least one token assessed `supports: yes` showing the dependent skill using the prerequisite (digest-pinned, located); for `expert_judgement` two separate written rationales (contract, section 6).
- **Rationale:** many real dependencies are not on any page; the pilot measures how many.
- **CSV / schema:** `evidence_refs` sidecar; the service sees only non-empty evidence plus derived `rev:` tokens.
- **Depends on:** appendix B (**not performed**). **Acceptance:** tests for each invalid and stale evidence case; pilot report.

## D12: Review integrity, independence, custody. *Recommended; owner choices R2, R4, R5*

- **Final value:** the event and hash-chain specification (guidelines, section 4), write-once anchors in two encrypted custody locations outside Git (section 5), a person register with a write-once owner verification (section 2), two independent qualified approvals per pilot edge.
- **Rationale:** gives the review history tamper evidence without claiming immutability; makes independence checkable where code can check it and owner-verified where it cannot.
- **CSV / schema:** `author_id`, `review_record_ids` sidecar. No database change.
- **Depends on:** R2 (custody), R4 (people), R5. The loader cannot prove two codes are two real people.
- **Acceptance:** tests that interior edit, deletion, reordering, truncation and replacement are detected as documented (a reference-implementation test exists); tests for each independence check.

## D13: Stale approvals and endpoint changes. *Recommended*

- **Final value:** an edge is stale if its own P field changes or an endpoint's `content_version` changes; recovery only by a human `reaffirmation` by two independent reviewers; nothing carries over automatically.
- **CSV / schema:** loader logic; the service is unchanged.
- **Rationale and acceptance:** protects released edges from a changed KC meaning without staling them on editorial fixes; tests for each stale path.
- **Depends on:** D8, D12.

## D14: Blanket attestation cannot approve. *Recommended (approved in principle earlier)*

- **Final value:** only individually recorded events approve a KC or edge; an owner attestation records completion only (`REVIEW_NOT_INDIVIDUAL`).
- **CSV / schema:** none.
- **Rationale and acceptance:** matches the Phase 4 distinction; test that an attestation-basis event never satisfies the quorum.
- **Depends on:** nothing.

## D15: KC retirement and runtime visibility. *Recommended sidecar; owner choice R1; mastery transfer is an investigation*

- **Final value:** lifecycle (`active`/`retired`) kept separate from review status; no `retired` review status; hash-chained lifecycle log with authoriser, reason, timestamp, replacement KCs, per-edge resolution and learner-history note; no automatic mastery transfer; runtime consumers use a released graph snapshot and fail closed on any lifecycle mismatch (guidelines, section 8; contract, section 12). **This is a proposal, not implemented behaviour.**
- **CSV / schema:** none; no column or table added.
- **Rationale:** a runtime service cannot see a sidecar, so it must load a validated snapshot rather than raw rows.
- **Depends on:** R1; a Phase 9 policy decision on mastery transfer. **Blocks runtime consumption and database import only.**
- **Acceptance:** tests for each fail-closed case (missing record, stale digest, snapshot mismatch, retired KC in a path).

## D16: File locations and Git safety. *Recommended; rule added and verified*

- **Final value:** curated sources `data/curated/kc_graph/`; review log, register and anchors `overrides/kc_review/`; reports `logs/kc_graph/`; generated exports `final/kc_graph/`.
- **CSV / schema:** none.
- **Rationale:** curated sources do not sit in a generated-output folder; the four roles stay separate.
- **Status:** the minimal rule `data_pipeline/data/curated/**` (with README and `.gitkeep` exceptions) was appended to `.gitignore` without altering any existing line; checked with `git check-ignore` in the repository and in a throwaway repository (data files ignored, READMEs visible, all existing exclusions still ignored). `.gitignore` is a staged file, so the change is an unstaged hunk.
- **Depends on:** nothing; blocks no decision.
- **Acceptance:** `test_public_docs` checks the rule text and, when Git is available, the ignore behaviour.

## D17: Local Qwen drafting. *Separate authorisation*

- **Final value:** conditional policy in guidelines, section 10: local Ollama Qwen 3.5 9B only; a separate rights record naming KC and prerequisite-edge drafting; a mock-tested adapter; schema-constrained, validated output; every draft enters as `needs_review`, `ai_drafted`; a model never sets outcomes, reviewer identity, approval, rationale or expert rationale, nor vocabulary; Hindi excluded.
- **CSV / schema:** `origin`, `origin_ref`; none in the database.
- **Rationale:** no existing record authorises this use; external processing stays unapproved.
- **Depends on:** the new rights record, an adapter (none exists), quality evaluation. **Blocks AI candidate generation only.**
- **Acceptance:** `AI_FIELD_VIOLATION` and `AI_SELF_APPROVAL` tests.

## D18: Class coverage and foundation KCs. *Recommended*

- **Final value:** `declared_class_levels` optional for drafts, required to count in released class coverage; declared is not mapped; `scope=foundation` with no declared classes, reported separately, still usable as a prerequisite for Classes 6–10 (contract, section 10).
- **CSV / schema:** sidecar columns; no database change. **Future service change:** `KcRecord` gains `scope` and a lifecycle flag, and `coverage_report` becomes scope- and lifecycle-aware.
- **Rationale:** keeps the roadmap rule that roots need not lie in Class 6.
- **Depends on:** nothing for the loader. **Acceptance:** coverage tests with foundation KCs, retired KCs and empty declarations.

---

## Appendix A: D4 taxonomy assessment package (not performed)

**Status: not performed.** No human has assessed these skills; no reviewer has been named and no score exists. The package is ready for two independent registered human reviewers. A model must not assess it.

**Contents.** Exactly 30 synthetic skills, six per subject family, each with a provisional type (the **author's key**, hidden from reviewers until both finish). The set is designed so each subject has one skill per type, which keeps the test varied. The examples are generic and drawn from no textbook.

| # | Subject | Skill | Provisional type (hidden) |
|---|---|---|---|
| 1 | english | Identify the main idea of a short paragraph | interpretation |
| 2 | english | Make a verb agree with its subject | procedure |
| 3 | english | State the meaning of common prefixes | vocabulary |
| 4 | english | Write a paragraph with a topic sentence | application |
| 5 | english | Recall the parts of a formal letter | fact |
| 6 | english | Explain what a metaphor is | concept |
| 7 | hindi | Identify nouns and verbs in a sentence | concept |
| 8 | hindi | Join two words by a sandhi rule | procedure |
| 9 | hindi | Give the meaning of common idioms | vocabulary |
| 10 | hindi | Answer an inference question on a short passage | interpretation |
| 11 | hindi | Write a short formal leave application | application |
| 12 | hindi | Recall the gender of everyday nouns | fact |
| 13 | mathematics | Add two fractions with unlike denominators | procedure |
| 14 | mathematics | Explain what equivalent fractions are | concept |
| 15 | mathematics | Recall the multiplication tables up to 10 | fact |
| 16 | mathematics | Solve a word problem using a ratio | application |
| 17 | mathematics | Read a value from a bar graph | interpretation |
| 18 | mathematics | State what "perimeter" means | vocabulary |
| 19 | science | Classify materials as mixtures or pure substances | concept |
| 20 | science | Name the three states of matter | fact |
| 21 | science | Read a volume with a measuring cylinder | procedure |
| 22 | science | Explain why ice floats on water | application |
| 23 | science | Read a food-chain diagram | interpretation |
| 24 | science | State what "habitat" means | vocabulary |
| 25 | social_science | Locate a place on a map using its coordinates | procedure |
| 26 | social_science | Place events in order on a timeline | application |
| 27 | social_science | Explain what a fundamental right is | concept |
| 28 | social_science | Read a trend from a population table | interpretation |
| 29 | social_science | Recall the capital of a given state | fact |
| 30 | social_science | State what "democracy" means | vocabulary |

**Instructions to each reviewer (working alone, without seeing the other's sheet or the key).** For each skill assign exactly one type, or mark "none fits". Use these definitions and tests:

| Type | Definition | Test |
|---|---|---|
| `concept` | understanding an idea or category | can the learner explain or classify it in their own words? |
| `procedure` | carrying out steps that lead to a determinable result | is there a correct sequence of steps? |
| `fact` | recalling a specific item or association | is it recall with no reasoning needed? |
| `vocabulary` | knowing the meaning or use of a term or word | is the point the term and its meaning? |
| `application` | using knowledge in a new situation or to produce something | is the task new or open rather than routine? |
| `interpretation` | deriving meaning from a text, table, graph, diagram or map | is the input something to read or decode? |

Tie-breaks: if both `concept` and `vocabulary` apply, choose `vocabulary` only when the point is the term's definition; if both `procedure` and `application` apply, choose `application` only when the situation is non-routine.

**Recording sheet (one row per reviewer per skill):** `skill #`, `assigned_type`, `confidence` (1 unsure, 2 fairly sure, 3 sure), `none_fits` (yes/no), `if none fits: what fits and why`, `note`, `minutes`. Reviewer identity is the register code.

**Scoring rubric.** Computed by tooling or an analyst, never by a model judging reviewers: percent agreement (overall, per subject, per type); Cohen's kappa (overall, per subject); the confusion matrix; the "none fits" rate (overall, per subject); the share of skills where each reviewer's choice matches the provisional key (reported only **after** both finish, and not used to grade the reviewers); mean confidence.

**Disagreement and adjudication.** Each skill with different types, or any "none fits", goes to a third registered reviewer (or the owner), who sees both answers and assigns a final type with a written note. If the adjudicator picks neither answer, or "none fits", the skill is **ambiguous**. A confusion pair that recurs across skills (for example `concept` versus `vocabulary`) or a subject with many ambiguous skills means the definitions or the list need revising, followed by a retest on a **fresh** set of 30 synthetic skills.

**Evidence needed before the taxonomy is frozen:**

1. complete sheets from two independent registered human reviewers for all 30 skills, with reviewer codes;
2. the computed metrics above, overall and per subject, with the confusion matrix;
3. the disagreement log with each adjudication and its note;
4. the owner's pre-set thresholds (R6), for example a kappa floor; the reference convention that 0.6 is "substantial agreement" is offered as a starting point, not a rule;
5. for English and Hindi, a written account of any language skill for which "none fits" was chosen;
6. the final vocabulary file with a version number and change log;
7. a retest result if the vocabulary changed.

## Appendix B: D11 evidence pilot protocol (not performed)

**Status: not performed.** No candidate edges, citations, approvals or outcomes exist. This is the protocol only.

**Question.** Among proposed prerequisite edges that are real dependencies, how many can be supported by a source passage, and how many rest on expert judgement alone?

**Candidate edges.** Hand-authored by registered authors from KCs on the pilot documents (no model drafting; D17 is not authorised). Every candidate is an ordinary edge row with `dependency_basis`, a `reason`, and, where one exists, a located, pinned evidence token.

**Sampling.** Frame: every candidate edge. If there are about 100 or fewer, review all (a census). If more, draw a stratified random sample of about **100 edges, about 20 from each of the five subject families**, with the random seed recorded. For a proportion near one half, 100 edges gives roughly ±10 percentage points at 95% confidence overall; **a subject with 20 edges gives only about ±22 points**, so per-subject results are indicative, not conclusive. A smaller pilot is allowed but must state its width.

**Procedure.** Two independent qualified reviewers classify every sampled edge without seeing each other's answer:

| Class | Meaning |
|---|---|
| (a) source-backed | they can point to a located passage where the dependent skill **uses** the prerequisite |
| (b) expert-supported | the dependency is real but no passage shows it |
| (c) not a real dependency | rejected |

They also record: evidence availability (tokens found, assessed yes/no), minutes spent, their decision (`approved`, `rejected`, `revision_required`), and a written rationale (expert rationale for class (b)). A disagreement on class or decision is resolved by adjudication (guidelines, section 6) and counted.

**Recording sheet** in `data/curated/kc_graph/pilot/`: `edge_key`, `subject`, `stratum`, `reviewer_code`, `class`, `evidence_tokens`, `supports`, `decision`, `minutes`, `disagreed`, `adjudicated_class`.

**Outputs.** The share of (b) among real dependencies overall and per subject, with Wilson 95% intervals; reviewer agreement (percent and kappa) on (a) versus (b); disagreement and approval counts; measured minutes per review (m); evidence availability by subject and basis.

**Locally authorised source material needed.** Only material already covered by the existing local-processing records, kept local: the **10 pilot documents** (two per subject family): their PDFs for reading pages, and their normalised artifacts (the Hindi artifact with the approved duplicate-glyph repair) for locating paragraphs and computing passage digests; the accepted inventory rows for digest pins; the extraction run manifest. Reviewers read these **locally, as people**, through an owner-controlled private channel. No model reads them, nothing is uploaded, and no external provider is involved. Pages with unreliable text (maths equations, legacy-font Hindi) must be checked against the original page image.

**Limitations to state in the report.** (1) Per-subject samples of 20 have wide intervals (about ±22 points). (2) The pilot covers only 10 documents spanning Classes 8–10, so it says little about Class 6–7 content. (3) Candidates are authored by the pilot's own authors from the pilot documents, so the evidence rate is biased toward what those documents contain. (4) A census of fewer than 100 edges is not a random sample. (5) Classifying (a) versus (b) is a judgement; agreement is measured, not assumed. (6) Early edges take longer while reviewers learn, which inflates m. (7) A rate measured on this pilot does not transfer automatically to other subjects, classes or sources.

**What it informs.** Whether two reviewers per edge are workable (cost 2 × E × m with the measured m); how many edges take the `expert_judgement` path; whether the minimum-evidence rule needs changing. The owner sets any thresholds before the results are seen (R6).
