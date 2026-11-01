# Phase 5: KC and prerequisite CSV contract (revision 4, implemented)

This is the specification the CSV loader is built against. **Only one thing in it is approved by explicit owner instruction: the exact header names and column order of the two CSVs (sections 2 and 3).** Everything else carries one of these labels and stays unapproved until the owner says so:

| Label | Meaning |
|---|---|
| **OWNER-INSTRUCTED** | given by the owner as an explicit instruction (headers and column order only) |
| **IN PRINCIPLE** | the owner approved the direction earlier; explicit final approval still pending (D3, D6, D9, D14) |
| **RECOMMENDED** | final proposed value, for the owner's explicit approval |
| **INVESTIGATION** | needs empirical evidence before it can be frozen |

"Frozen" in this document means *no ordinary design question remains open, so the loader can be built against it*; it does not mean approved. **Revision 4: the loader is implemented** in `data_pipeline/kc_graph/` exactly as specified here; every limit-setting value lives in `data_pipeline/kc_graph/contract.py`, so an owner change is a one-line edit. Implementing a rule does not approve it. Sample values are synthetic, and tests check that the samples and headers here are byte-identical to the code's.

Companions: [`PHASE_5_REVIEW_GUIDELINES.md`](PHASE_5_REVIEW_GUIDELINES.md) (review events, hash chain, custody, retirement, drafting), [`PHASE_5_DECISION_MATRIX.md`](PHASE_5_DECISION_MATRIX.md) (D1–D18 dispositions and the two pilots), [`PHASE_5_IMPLEMENTATION_HANDOFF.md`](PHASE_5_IMPLEMENTATION_HANDOFF.md) (build order), [`PHASE_5_PROGRESS.md`](PHASE_5_PROGRESS.md).

## 1. Principles

- The CSVs are curated, reviewable sources, never the database. PostgreSQL stays the source of truth. **No table, column or migration is added.**
- A field is stored in the database only if a column already exists; everything else stays in the CSV or a private sidecar (section 9).
- **AI generation is never approval.** A model never sets an approval outcome, a reviewer ID, a review rationale or an expert rationale.
- Encoding: UTF-8 without BOM, LF, RFC 4180 quoting, exact header and column order, IDs as strings, empty cell = empty string, no placeholders. List cells use `;`. The one JSON cell is `misconceptions`.

## 2. `kc_components.csv` (OWNER-INSTRUCTED header, 18 columns)

```csv kc_components.csv header
kc_id,stable_key,subject_id,name,learning_objective,kc_type,difficulty_tier,misconceptions,source_refs,declared_class_levels,content_version,origin,origin_ref,review_status,review_record_ids,aliases,scope,author_id
```

| Column | Meaning | Req. | Type and allowed values | Validation | Stored as |
|---|---|---|---|---|---|
| `kc_id` | Immutable identifier. **D1, RECOMMENDED** | yes | `KC-<SUBJ>-<5 digits>`, `<SUBJ>` ∈ `ENG HIN MAT SCI SOC` | unique; code matches `subject_id`; allocated once by one tool or person, never reused | `knowledge_component.kc_id` |
| `stable_key` | Concept identity key. **D2, RECOMMENDED**; section 5 | yes | `<subject>.<domain>.<concept>[.<facet>]` | pattern, closed lists, unique across keys and aliases, no class token, never edited after first approval | `knowledge_component.stable_key` (unique) |
| `subject_id` | Subject | yes | `english`, `hindi`, `mathematics`, `science`, `social_science` | exact; matches the `kc_id` code and the key's first part | `knowledge_component.subject_id` |
| `name` | Display name (clerical; may be reworded) | yes | text | non-empty | `knowledge_component.name` |
| `learning_objective` | One measurable sentence. **D3, IN PRINCIPLE** | yes | text starting with an action verb | non-empty; one sentence (warning otherwise) | `knowledge_component.description` |
| `kc_type` | Skill type. **D4, INVESTIGATION**; provisional list | yes | `concept`, `procedure`, `fact`, `vocabulary`, `application`, `interpretation` | one of the list, read from the vocabulary file | `knowledge_component.kc_type` |
| `difficulty_tier` | Relative difficulty within the subject. **D5, RECOMMENDED**: optional, no logic uses it until calibrated; not a BKT parameter; not question difficulty | no | integer `1`–`5` | in range or empty | `knowledge_component.difficulty_tier` |
| `misconceptions` | Common wrong beliefs. **D6, IN PRINCIPLE** | no | JSON array of `{"id","text"}` | valid JSON; `id` matches `^m[0-9]+$`, unique in the KC and never reused; `text` non-empty and distinct | `knowledge_component.misconceptions` (JSONB) |
| `source_refs` | Where the skill is taught or used. **D7** | yes (≥1) | `;`-separated tokens, section 6 | grammar, accepted source, digest pin, page in range | sidecar |
| `declared_class_levels` | Classes the author **declares**. Not a curriculum mapping. **D18** | `target`: required to count in released class coverage, may be empty in a draft. `foundation`: must be empty | `;`-separated from `6 7 8 9 10` | valid, no duplicates | sidecar; later reconciled with `kc_curriculum_map` |
| `content_version` | KC definition version. **D8** | yes | `kc-v<n>` | bumped only for a substantive change (section 7) | `knowledge_component.content_version` |
| `origin` | How the row was created | yes | `human_authored`, `ai_drafted`, `imported` | one of the list | sidecar |
| `origin_ref` | Generation or import record | if `ai_drafted` | string | non-empty when `ai_drafted` | sidecar |
| `review_status` | Review state | yes | `needs_review`, `in_review`, `approved`, `rejected` | sections 7–8 | `knowledge_component.review_status` |
| `review_record_ids` | The review events that justify the status | when `approved` or `rejected` | `;`-separated event IDs (`RR-0001`) | each resolves to a current, matching event; count meets the quorum | sidecar |
| `aliases` | Other keys for the same concept | no | `;`-separated slugs | globally unique; never equal to any key; changes are clerical events | sidecar |
| `scope` | Where the skill sits relative to Classes 6–10. **D18** | yes | `target` or `foundation` | one of the two | sidecar |
| `author_id` | Register code of the human who curated the row | yes unless untouched `ai_drafted` | a code in the person register | known code; used for independence checks | sidecar |

### Sample (synthetic)

```csv kc_components.csv sample
kc_id,stable_key,subject_id,name,learning_objective,kc_type,difficulty_tier,misconceptions,source_refs,declared_class_levels,content_version,origin,origin_ref,review_status,review_record_ids,aliases,scope,author_id
KC-MAT-00001,mathematics.fractions.equivalent-fractions.recognise,mathematics,Recognise equivalent fractions,Identify whether two fractions represent the same quantity.,concept,1,"[{""id"":""m1"",""text"":""Believes a larger denominator always means a larger fraction""}]",src:SRC-C07-MAT-EXMP1-01@3#a1b2c3d4e5f6,6;7,kc-v1,human_authored,,approved,RR-0001,,target,RV-001
KC-MAT-00002,mathematics.fractions.add-unlike-denominators.compute,mathematics,Add fractions with unlike denominators,Add two fractions by rewriting them over a common denominator.,procedure,2,"[{""id"":""m1"",""text"":""Adds the numerators and the denominators separately""}]",src:SRC-C07-MAT-EXMP1-01@5#a1b2c3d4e5f6,7,kc-v1,human_authored,,approved,RR-0002,mathematics.fractions.fraction-addition,target,RV-001
KC-MAT-00003,mathematics.fractions.mixed-numbers.construct,mathematics,Convert between improper fractions and mixed numbers,Rewrite an improper fraction as a mixed number and back.,procedure,2,,src:SRC-C07-MAT-EXMP1-01@6#a1b2c3d4e5f6,7,kc-v1,ai_drafted,GEN-EXAMPLE-01,needs_review,,,target,
KC-MAT-00004,mathematics.number-sense.equal-sharing.recognise,mathematics,Recognise equal sharing,Identify whether a whole has been shared into equal parts.,concept,1,,src:SRC-C07-MAT-EXMP1-01@2#a1b2c3d4e5f6,,kc-v1,human_authored,,approved,RR-0003,,foundation,RV-001
```

## 3. `prerequisites.csv` (OWNER-INSTRUCTED header, 11 columns)

Direction: `prerequisite_kc_id` is learned **before** `dependent_kc_id` (as in `kc_edge`).

```csv prerequisites.csv header
prerequisite_kc_id,dependent_kc_id,dependency_basis,reason,strength,evidence_refs,origin,origin_ref,review_status,review_record_ids,author_id
```

| Column | Meaning | Req. | Type and allowed values | Validation | Stored as |
|---|---|---|---|---|---|
| `prerequisite_kc_id` | The KC learned first | yes | a `kc_id` | exists; ≠ `dependent_kc_id` | `kc_edge.prerequisite_kc_id` |
| `dependent_kc_id` | The KC that needs it | yes | a `kc_id` | exists | `kc_edge.dependent_kc_id` |
| `dependency_basis` | Why. **D9, IN PRINCIPLE** | yes | `uses_concept`, `uses_procedure`, `uses_vocabulary`, `uses_representation`, `expert_judgement`; **`chapter_order` is prohibited** | one of the five | sidecar |
| `reason` | What the dependent skill takes from the prerequisite (supporting field) | yes | text | non-empty; warning if it leans on sequence | `kc_edge.reason` |
| `strength` | Reliance. **D10, RECOMMENDED**: no logic uses it until the Phase 9 policy design says how | no | `1` helpful, `2` important, `3` essential | in range or empty | `kc_edge.strength` |
| `evidence_refs` | **Existing** source evidence only | `uses_*`: ≥1 to approve. `expert_judgement`: may be empty | `;`-separated tokens, section 6 (locator **required**) | as section 6. **A `rev:` token is never allowed in this column** | sidecar |
| `origin`, `origin_ref` | As for KCs | yes / if `ai_drafted` | as for KCs | as for KCs | sidecar |
| `review_status` | Review state | yes | `needs_review`, `in_review`, `approved`, `rejected` | sections 7–8 | `kc_edge.review_status` |
| `review_record_ids` | The review events | when `approved` or `rejected` | `;`-separated event IDs | **two** current approving events from independent qualified reviewers (pilot, D12) | sidecar |
| `author_id` | As for KCs | yes unless untouched `ai_drafted` | register code | known code | sidecar |

An edge is never inferred from chapter order. Expert rationale lives inside the approving review events (section 8), never in the CSV.

### Sample (synthetic)

```csv prerequisites.csv sample
prerequisite_kc_id,dependent_kc_id,dependency_basis,reason,strength,evidence_refs,origin,origin_ref,review_status,review_record_ids,author_id
KC-MAT-00001,KC-MAT-00002,uses_concept,Finding a common denominator means rewriting each fraction as an equivalent fraction.,3,src:SRC-C07-MAT-EXMP1-01@5:para2#a1b2c3d4e5f6,human_authored,,approved,RR-0004;RR-0005,RV-001
KC-MAT-00004,KC-MAT-00001,uses_concept,Comparing fractions as the same quantity builds on equal sharing of a whole.,2,src:SRC-C07-MAT-EXMP1-01@3:para1#a1b2c3d4e5f6,human_authored,,approved,RR-0006;RR-0007,RV-001
KC-MAT-00002,KC-MAT-00003,uses_procedure,Converting a sum to a mixed number follows the addition step.,2,,ai_drafted,GEN-EXAMPLE-01,needs_review,,
```

## 4. Closed vocabularies (D2, D4, D9; owner-maintained)

All vocabularies are read from one private, versioned file, `data/curated/kc_graph/kc_vocabularies.json` (owner-maintained; its version and digest are recorded in every report and release manifest). Shape: `{"version", "status": "owner_confirmed" | "provisional", "domains": {<subject>: [...]}, "facets", "kc_types", "dependency_bases", "change_log"}`. **Until the owner creates it, the loader uses the proposal below as a built-in provisional vocabulary** (`VOCABULARY_PROVISIONAL`): enough for parsing, dry runs and synthetic tests, never for release (`VOCABULARY_NOT_CONFIRMED`). **Every entry below is a proposal and needs the owner's explicit confirmation; none is approved.** A model may not add, change or "silently create" an entry: an unknown domain or facet is a blocking error (`UNKNOWN_DOMAIN`, `UNKNOWN_FACET`), and a new value enters only by an owner edit that bumps the file's version.

**Domains per subject (PROPOSED, English slugs, class-independent).**

| Subject | Domains |
|---|---|
| `mathematics` | `number-sense`, `integers`, `fractions`, `decimals`, `ratio-proportion`, `percentages`, `exponents-powers`, `algebra`, `equations`, `polynomials`, `sequences-series`, `geometry`, `mensuration`, `coordinate-geometry`, `trigonometry`, `data-handling`, `probability` |
| `science` | `matter`, `atoms-molecules`, `chemical-reactions`, `acids-bases-salts`, `metals-nonmetals`, `carbon-compounds`, `periodic-classification`, `motion-force`, `work-energy`, `heat`, `light`, `sound`, `electricity`, `magnetism`, `cells-tissues`, `nutrition`, `respiration`, `reproduction`, `heredity-evolution`, `human-body`, `ecosystems`, `natural-resources` |
| `english` | `reading`, `writing`, `grammar`, `vocabulary`, `literature`, `speaking-listening` |
| `hindi` | `reading`, `writing`, `grammar`, `vocabulary`, `literature`, `speaking-listening` (slugs stay English; the Hindi concept goes in `<concept>`, for example `hindi.grammar.sandhi.explain`) |
| `social_science` | `history`, `geography`, `civics`, `economics` |

**Facets (PROPOSED, optional, shared by all subjects):** `recall`, `recognise`, `define`, `classify`, `compute`, `construct`, `apply`, `explain`, `compare`, `interpret`, `evaluate`.

**Entries most likely to need owner discussion:** overlaps between `algebra`/`equations`/`polynomials` and between `matter`/`atoms-molecules`, `ecosystems`/`natural-resources`; whether `sequences-series` and `probability` are separate domains for the pilot; whether `literature` should be split by genre; whether Hindi should use its own domain names. These stay as proposed until confirmed.

**Other vocabularies (all PROPOSED):** `kc_type` (D4, provisional), `dependency_basis` (D9, IN PRINCIPLE), `strength` 1–3, `scope`, `origin`, review statuses (the project's existing four), review event types and decisions (guidelines).

## 5. Stable-key convention (D2, RECOMMENDED)

`<subject>.<domain>.<concept>[.<facet>]`, for example `science.matter.pure-substance.classify`.

1. **Concept identity, not display wording.** `<concept>` is the underlying learning concept in neutral English (noun phrase, hyphenated lowercase), **not** the textbook heading or `name`. Reworded `name` or `learning_objective` never changes the key.
2. **Class-independent.** No class or grade token; the loader rejects obvious ones (`KEY_HAS_CLASS_TOKEN`) and warns on lookalikes.
3. **Ordinary rewording survives.** A key never changes after first approval. Rewording changes `name` or the objective (a clerical or wording-only event, section 7), not the key.
4. **Genuinely distinct concepts keep distinct keys**, even with similar names: uniqueness is on the whole key, so `science.light.reflection.explain` and `mathematics.geometry.reflection.construct` (the same word, two different concepts) stay distinct by subject and domain. The loader warns (`SIMILAR_KEY`) when two keys share a concept slug or differ by a small edit distance; the reviewer records, in the event, which KC it is distinct from and why.
5. **Versioning is separate.** The key has no version. A substantive redefinition of the same concept keeps the key and bumps `content_version`; a *different* concept gets a new key and a new `kc_id`.
6. **Aliases.** If a published key is later judged poorly named, add an alias; never edit the key. Aliases are globally unique, never equal to any key, and each change is a documented clerical event. A split or merge is not an alias: it is retirement plus new KCs (guidelines, section 8).
7. **Determinism.** Keys are authored, then normalised and verified by the loader (lowercase, ASCII, pattern, closed lists, uniqueness). The loader never generates or silently repairs a key. English ASCII is used for Hindi content.
8. **`kc_id` is the canonical identity** for edges and the database; `stable_key` is the stable human lookup.

Synthetic examples: `english.reading.main-idea.identify`, `hindi.grammar.sandhi.explain`, `mathematics.fractions.equivalent-fractions.recognise`, `science.matter.pure-substance.classify`, `social_science.civics.local-government.compare`.

## 6. Source references and evidence tokens (D7, RECOMMENDED)

**Grammar (one token per page):**

```
src:<source_id>@<pdf_page_index>[:para<N>]#<sha12>
```

| Part | Meaning and rule |
|---|---|
| `source_id` | an accepted inventory source (`SRC-C06…` to `SRC-C10…`); quarantined, rejected or rights-blocked sources are refused |
| `pdf_page_index` | the PDF's zero-based page index (not the printed label); an integer in `[0, page_count)` |
| `:para<N>` | optional for KC `source_refs`; **required for edge `evidence_refs`**. The zero-based paragraph index on that page in the normalised artifact: the passage location |
| `#<sha12>` | **required.** The first 12 hex characters of the source PDF's SHA-256 from the inventory. It pins the exact edition and bytes |

**Resolution (implemented, `sources.py`).** Only existing local material is used: the accepted rows of the cleaned inventory (`validation_status=passed`), the existing normalised extraction artifacts in `data/processed/textbook_json/`, and the rights overlay, which must permit `local_text_normalization` for the exact bytes (otherwise `SOURCE_RIGHTS_BLOCKED`). When the local PDF copy is present its bytes are re-hashed. Nothing is downloaded, extracted or OCR'd; paragraph text is hashed, never copied into a report. Today 10 documents (the pilot) have artifacts; a token for any other source is `SOURCE_ARTIFACT_MISSING`. The Hindi artifact's approved repair overlay is not applied, so Hindi passage digests are of the normalised text.

**Traceability.** The loader resolves a token to: the inventory row (source ID, title, `publication_or_revision`, academic session = the *source version*), the PDF's full SHA-256, and the page and paragraph in the normalised artifact. It records all of that in the manifest.

**Digest pinning.** The pin must equal the inventory digest *and* the digest recorded in the extraction artifacts (`SOURCE_PIN_MISMATCH` otherwise). When a reviewer assesses an edge, the event records the full source SHA-256 and `passage_sha256` (SHA-256 of that paragraph's text at review time). A later mismatch (a replaced PDF, or re-extraction that changes the paragraph) makes the evidence **stale**.

**Source-backed evidence (`uses_*`).** At least one token for which the reviewer recorded `supports: yes`, with a note saying where the **dependent skill uses the prerequisite**. A page that merely mentions both topics, or a definition of the prerequisite alone, is **not** sufficient.

**Expert rationale (`expert_judgement`).** Written by each reviewer inside their own approving event, stating (a) what the dependent skill requires, (b) why the prerequisite is necessary (what fails without it), (c) that it does not rest on chapter or textbook sequence. It may cite supporting `src:` tokens and *earlier* events only. A model may not write it. No row or event cites a future event: the circular reference of revision 1 cannot occur, because rationale lives in the event, not the row.

**Minimum for an approved edge (pilot):** two independent qualified approving events from different reviewers, each with a written rationale; for `uses_*`, at least one `supports: yes` source token; for `expert_judgement`, two separate expert rationales.

**Derived evidence for the graph service.** The service requires non-empty `evidence_refs` on approved edges. The loader builds the service's `EdgeRecord` with the CSV tokens plus derived `rev:<event_id>` tokens for the approving events, **at load time**. They are never stored in the CSV, so there is no circularity and the service needs no change.

**Invalid:** unresolved or malformed token; page or paragraph out of range; unaccepted or rights-blocked source; wrong digest pin; `supports: no`; empty, non-human or copied rationale; a `rev:` token in the CSV; an event citing a later event. **Stale:** source SHA-256 or `passage_sha256` no longer matches; page out of range after re-extraction; a cited event superseded by a rejection.

## 7. Digests, versions and what counts as substantive (D8, D13, RECOMMENDED)

| Term | Definition |
|---|---|
| **Full record digest** | SHA-256 of canonical JSON of every column except `review_status` and `review_record_ids`. Any edit changes it |
| **Pedagogical content digest** | SHA-256 of the P fields below only |
| **KC content version** (`content_version`) | `kc-v<n>`, bumped **only** when the pedagogical digest changes |

| Class | KC fields | Edge fields | Effect of a change |
|---|---|---|---|
| **P** pedagogical | `subject_id`, `kc_type`, `learning_objective`, `misconceptions`, `scope` | `prerequisite_kc_id`, `dependent_kc_id`, `dependency_basis`, `evidence_refs` | substantive: approvals stale; KC version must be bumped; edges touching the KC go stale |
| **S** supporting | `source_refs`, `difficulty_tier`, `declared_class_levels`, `aliases` | `reason`, `strength` | full digest changes; approval stale until a documented clerical confirmation; version and edges unaffected |
| **C** clerical | `name`, `origin`, `origin_ref`, `author_id` | `origin`, `origin_ref`, `author_id` | as S |

Identity fields `kc_id` and `stable_key` never change after first approval.

**Which changes do what:**

- **Clerical (S or C only):** needs a documented `clerical_confirmation` event (one qualified reviewer who is not the author), recording what changed and confirming the pedagogical digest is unchanged. Until then the approval is stale. **Nothing reviewed is ever altered silently.**
- **Affects pedagogical content (a P field changes):** the approval is invalidated and the row returns to review. The loader demands a version bump (`VERSION_NOT_BUMPED`), and refuses a clerical event for it (`CLERICAL_EVENT_ON_SUBSTANTIVE_CHANGE`).
- **Requires a KC version increment:** exactly the P-field changes above.
- **Invalidates edge approvals:** an edge is stale if its own P field changes, **or** if either endpoint's `content_version` changes. Editorial KC fixes never stale edges.
- **Wording-only change to a P field** (for example a typo in `learning_objective`): substantive by default. A reviewer pair may instead issue a `clerical_confirmation` classed `wording_only` linking the old pedagogical digest to the new, with a rationale; two independent reviewers in the pilot. Version and edges are then unaffected.

**Human reaffirmation (new, auditable event, never automatic).** When an edge is stale only because an endpoint's version changed: the author sets it to `needs_review`; two independent qualified reviewers each read the **current** definitions and evidence and write a `reaffirmation` event (a written statement that the dependency still holds, or does not; new endpoint versions; the events superseded). The old approval stays in the log as history and is never reused. The loader never copies an approval across a version.

## 8. Validation rules the loader must enforce

Implemented in `data_pipeline/kc_graph/` (registry: `contract.CODES`). **Errors** block release; **warnings** are reported only. Every problem is reported, not only the first. Graph rules are the service's (`app.services.prerequisite_graph`), reused, not reimplemented.

**M1: files, rows, keys, vocabularies and the graph service**

| Code | Severity | Rule |
|---|---|---|
| `INVALID_ENCODING` | error | the file is not UTF-8 |
| `BOM_PRESENT` | warning | a UTF-8 BOM was stripped |
| `INVALID_CSV` | error | RFC 4180 quoting error |
| `FILE_MISSING` | error | a CSV file does not exist |
| `HEADER_MISMATCH` | error | header names, order or uniqueness differ from sections 2 and 3 |
| `ROW_WIDTH` | error | a row has the wrong number of cells |
| `BLANK_ROW` | warning | a blank line was skipped |
| `MISSING_REQUIRED` | error | a required cell is empty |
| `UNTRIMMED_CELL` | error | leading or trailing whitespace (reported, never trimmed) |
| `PLACEHOLDER_VALUE` | error | `NA`, `null`, `-` and similar instead of an empty cell |
| `INVALID_LIST` | error | empty, untrimmed or repeated `;` list item |
| `INVALID_KC_ID` | error | not `KC-<SUBJ>-<5 digits>` |
| `DUPLICATE_KC_ID` | error | graph service |
| `DUPLICATE_STABLE_KEY` | error | graph service |
| `DUPLICATE_ALIAS` | error | an alias is used twice |
| `ALIAS_COLLIDES_WITH_KEY` | error | an alias equals a stable key |
| `INVALID_SUBJECT` | error | subject not in the five |
| `SUBJECT_ID_MISMATCH` | error | `kc_id` code or key subject differs from `subject_id` |
| `INVALID_KC_TYPE` | error | not in the vocabulary |
| `INVALID_DIFFICULTY` | error | not 1-5 |
| `INVALID_STRENGTH` | error | not 1-3 |
| `INVALID_SCOPE` | error | not `target`/`foundation` |
| `INVALID_CLASS_LEVEL` | error | not 6-10 |
| `INVALID_STATUS` | error | not one of the four review statuses |
| `INVALID_ORIGIN` | error | not one of the three origins |
| `INVALID_VERSION` | error | not `kc-v<n>` |
| `INVALID_PERSON_CODE` | error | `author_id` is not `RV-<digits>` |
| `INVALID_REVIEW_REF` | error | a review ID is not `RR-<4+ digits>` |
| `INVALID_KEY` | error | key or alias does not match the convention |
| `KEY_HAS_CLASS_TOKEN` | error | an obvious class token (`class-7`, `c07`, `7th`) |
| `KEY_CLASS_LOOKALIKE` | warning | a part contains 6-10 and may be a class token |
| `UNKNOWN_DOMAIN` | error | domain not in the closed list |
| `UNKNOWN_FACET` | error | facet not in the closed list |
| `INVALID_MISCONCEPTIONS` | error | not a non-empty array of `{"id","text"}` with unique IDs and distinct text |
| `FOUNDATION_HAS_CLASSES` | error | `scope=foundation` with declared classes |
| `FOUNDATION_DEPENDS_ON_TARGET` | error | a foundation KC as the dependent of a target KC (wrong direction) |
| `INVALID_SOURCE_REF` | error | KC `source_refs` grammar |
| `INVALID_EVIDENCE_REF` | error | edge `evidence_refs` grammar |
| `MISSING_LOCATOR` | error | edge evidence without `:para<N>` |
| `REV_TOKEN_IN_CSV` | error | a `rev:` token typed into the CSV |
| `FORBIDDEN_BASIS` | error | `chapter_order` or any basis outside the vocabulary |
| `EDGE_WITHOUT_EVIDENCE` | error | an approved `uses_*` edge without a source token (loader), or an approved edge with no evidence at all (service) |
| `AI_FIELD_VIOLATION` | error | an uncurated model draft carrying review fields, or a draft field a model may not set |
| `VOCABULARY_INVALID` | error | the vocabulary file is malformed |
| `VOCABULARY_PROVISIONAL` | warning | no confirmed vocabulary file; the contract proposal is used |
| `REASON_MENTIONS_ORDER` | warning | the reason seems to rely on sequence |
| `SIMILAR_KEY` | warning | keys share a concept slug or differ by at most 2 edits |
| `KC_WITHOUT_CLASS_DECLARATION` | warning | a target KC with no declared class (not counted in released coverage) |
| `KC_WITHOUT_EDGES` | warning | no edge touches an active KC |
| `FOUNDATION_WITHOUT_TARGET_EDGE` | warning | no target KC depends on a foundation KC |
| `REDUNDANT_EDGE` | warning | an approved edge implied by a longer approved path |
| `CROSS_SUBJECT_EDGE` | warning | endpoints in different subjects |
| `EDGE_AGAINST_CLASS_ORDER` | warning | prerequisite declared only for later classes than the dependent |
| `DUPLICATE_NAME` | warning | same name twice in a subject |
| `LONG_OBJECTIVE` | warning | objective over 40 words or more than one sentence |
| `MISSING_ENDPOINT` | error | graph service |
| `SELF_EDGE` | error | graph service |
| `DUPLICATE_EDGE` | error | graph service |
| `CYCLE` | error | graph service (approved graph) |
| `EDGE_ENDPOINT_KC_NOT_APPROVED` | error | graph service |
| `EDGE_TOUCHES_REJECTED_KC` | error | graph service |
| `CYCLE_IN_PROPOSALS` | warning | graph service |
| `PROPOSAL_WITHOUT_EVIDENCE` | warning | graph service |

**M2: sources and evidence**

| Code | Severity | Rule |
|---|---|---|
| `SOURCE_INDEX_UNAVAILABLE` | error | references could not be resolved (no index) |
| `SOURCE_UNKNOWN` | error | source not in the accepted inventory |
| `SOURCE_NOT_ACCEPTED` | error | inventory row not validated |
| `SOURCE_RIGHTS_BLOCKED` | error | the rights gate refuses `local_text_normalization` for these bytes |
| `SOURCE_ARTIFACT_MISSING` | error | no normalised extraction artifact exists |
| `SOURCE_PIN_MISMATCH` | error | pin, artifact digest or local PDF bytes differ from the inventory SHA-256 |
| `SOURCE_FILE_ABSENT` | warning | the local PDF copy is absent, so its bytes were not re-hashed |
| `PAGE_OUT_OF_RANGE` | error | page not in `[0, page_count)` |
| `PARAGRAPH_OUT_OF_RANGE` | error | paragraph not on that page |
| `SOURCE_TEXT_UNUSABLE` | error | a passage locator on a page whose text is unusable |

**M3: register, review log and approvals**

| Code | Severity | Rule |
|---|---|---|
| `REGISTER_MISSING` | error | no person register |
| `REGISTER_INVALID` | error | malformed register (including duplicate codes or contact details) or verification |
| `REGISTER_NOT_VERIFIED` | error | no owner verification, or the register or an entry changed after it |
| `AUTHOR_UNKNOWN` | error | `author_id` not in the register |
| `SYNTHETIC_DATA` | error | synthetic register, vocabulary or events in a real run |
| `LOG_INVALID` | error | a log line is not JSON or has invalid values |
| `LOG_CHAIN_BROKEN` | error | hash, `prev_hash`, `seq` or ID does not verify |
| `LOG_ANCHOR_MISMATCH` | error | an anchor disagrees with the log (edit, truncation or replacement) |
| `LOG_ANCHOR_MISSING` | error | release: a custody location has no anchor of the current head |
| `CUSTODY_NOT_CONFIGURED` | error | release: no valid two-location custody configuration (R2) |
| `REVIEW_RECORD_MISSING` | error | a cited event is not in the log |
| `REVIEW_MISMATCH` | error | a cited event is about another record, or its decision contradicts the status |
| `REVIEW_NOT_INDIVIDUAL` | error | an event's basis is not an individual review |
| `REVIEWER_UNKNOWN` | error | reviewer not registered |
| `REVIEWER_NOT_QUALIFIED` | error | inactive, no reviewer role, or subjects not covered |
| `QUORUM_NOT_MET` | error | fewer current independent approvals than required (KC 1, edge 2) |
| `REVIEWER_NOT_INDEPENDENT` | error | the author reviewed, one reviewer counted twice, or the adjudicator was a party |
| `REVIEW_CONFLICT` | error | an unsuperseded rejection or revision request on the current content |
| `REVIEW_STALE` | error | an approval no longer matches the row, its version or its endpoints' versions |
| `VERSION_NOT_BUMPED` | error | pedagogical content changed at the same `content_version` |
| `CLERICAL_EVENT_ON_SUBSTANTIVE_CHANGE` | error | a clerical confirmation of a pedagogical change |
| `CHECKLIST_INCOMPLETE` | error | an approval without every checklist item confirmed |
| `EVIDENCE_NOT_ASSESSED` | error | an approving event did not assess every evidence token |
| `EVIDENCE_NOT_SUPPORTING` | error | no `supports: yes` passage with a note for a `uses_*` edge |
| `EVIDENCE_STALE` | error | source or passage digest changed since assessment |
| `RATIONALE_MISSING` | error | a required rationale or expert rationale is empty |
| `RATIONALE_DUPLICATED` | error | two approvals carry the same rationale text |
| `EVENT_CITES_FUTURE` | error | an event cites an event with an equal or later `seq` |
| `AI_SELF_APPROVAL` | error | a model-drafted row approved without current human approvals |
| `REVIEWER_AUTHORED_ENDPOINT` | warning | an edge reviewer authored an endpoint KC (R5: warning) |
| `VERSION_BUMPED_WITHOUT_CHANGE` | warning | version changed without a pedagogical change |

**M4: lifecycle, snapshot and release**

| Code | Severity | Rule |
|---|---|---|
| `EDGE_TOUCHES_RETIRED_KC` | error | an approved edge uses a retired KC |
| `LIFECYCLE_STALE` | error | the KC changed after its retirement record |
| `LIFECYCLE_MISSING` | error | snapshot: no retirement record in force for an excluded KC |
| `LIFECYCLE_INVALID` | error | malformed lifecycle event |
| `LIFECYCLE_UNAUTHORISED` | error | the authoriser is not a verified senior reviewer |
| `LIFECYCLE_EDGE_UNRESOLVED` | error | an approved edge on the KC has no valid resolution |
| `SNAPSHOT_LIFECYCLE_MISMATCH` | error | snapshot and lifecycle log disagree |
| `RETIRED_KC_IN_PATH` | error | a retired KC in the traversable snapshot |
| `SNAPSHOT_INVALID` | error | unknown format or invalid snapshot records |
| `SNAPSHOT_DIGEST_MISMATCH` | error | the snapshot digest does not verify |
| `VOCABULARY_NOT_CONFIRMED` | error | release: the vocabulary is not an owner-confirmed file |

**M5: reports**

| Code | Severity | Rule |
|---|---|---|
| `CLASS_MAPPING_MISMATCH` | error | declared classes differ from approved curriculum mappings (when supplied) |

## 9. Database mapping and sidecars

No table, column or migration is added. Verified against the ORM.

| CSV column | Database column |
|---|---|
| `kc_id` | `knowledge_component.kc_id` |
| `stable_key` | `knowledge_component.stable_key` |
| `subject_id` | `knowledge_component.subject_id` |
| `name` | `knowledge_component.name` |
| `learning_objective` | `knowledge_component.description` |
| `kc_type` | `knowledge_component.kc_type` |
| `difficulty_tier` | `knowledge_component.difficulty_tier` |
| `misconceptions` | `knowledge_component.misconceptions` |
| `content_version` | `knowledge_component.content_version` |
| `review_status` (KC) | `knowledge_component.review_status` |
| `prerequisite_kc_id` | `kc_edge.prerequisite_kc_id` |
| `dependent_kc_id` | `kc_edge.dependent_kc_id` |
| `strength` | `kc_edge.strength` |
| `reason` | `kc_edge.reason` |
| `review_status` (edge) | `kc_edge.review_status` |

**No column exists for** `aliases`, `source_refs`, `scope`, `declared_class_levels`, `origin`, `origin_ref`, `author_id`, `review_record_ids`, `dependency_basis`, `evidence_refs`, review provenance and KC lifecycle. They stay in the CSV and private sidecars. Later links: `content_unit_kcs` for source references once content units exist; `kc_curriculum_map` for classes once curriculum items exist. **Database-import-only metadata:** `learning_objective` mapping (D3), the released-edge set.

## 10. Class applicability, foundation KCs and the coverage specification (D18, RECOMMENDED)

- `declared_class_levels` is optional for a draft `target` KC and **mandatory for any KC counted in released class coverage**. It is the author's declaration, not a curriculum mapping. Reports label it "declared"; when `kc_curriculum_map` rows exist the loader compares and reports the mapped figure separately (`CLASS_MAPPING_MISMATCH`).
- `scope=foundation` marks a skill that Classes 6–10 rely on but that is taught earlier. A foundation KC is a normal KC (identified, individually reviewed, approved), has **no declared classes**, may be the prerequisite in an edge, and cites a Class 6–10 source that *assumes* it. It is **reported separately and not counted under any class**.
- **Released class coverage** counts only KCs that are `target`, `approved`, **active** (not retired) and have declared classes. The report has these sections: per subject and class (declared), foundation KCs (count, roots, edges into target KCs), target KCs excluded and why (no class, not approved, retired), edges by review status, roots by class (target KCs with no approved prerequisite) and foundation roots.
- **Service change (made in revision 4):** `KcRecord` has `scope` and `lifecycle`; `coverage_report` is scope- and lifecycle-aware, adds `released_class_coverage` (declared, mapped, declared-not-mapped per class; classes without coverage; excluded KCs and why) and a `foundation` section, and accepts approved curriculum mappings as a separate input. Mapped figures stay `null` until approved `kc_curriculum_map` rows exist; a declaration is never counted as a mapping.

## 11. File locations (D16, RECOMMENDED; rule added and verified)

| Role | Path | Git |
|---|---|---|
| **Curated source** (the two CSVs, `kc_vocabularies.json`, the pilot sheets) | `data_pipeline/data/curated/kc_graph/` | ignored by `data_pipeline/data/curated/**` (added in this revision; tested in the repository and in a throwaway repository: data files ignored, READMEs visible) |
| **Review log, lifecycle log, person register and its verification, anchors** | `data_pipeline/data/overrides/kc_review/` | ignored (`overrides/**`) |
| **Generated validation reports** | `data_pipeline/data/logs/kc_graph/` | ignored (`logs/**`) |
| **Generated final exports** (release manifest, released graph snapshot) | `data_pipeline/data/final/kc_graph/` | ignored (`final/**`), generated only |
| **Private operational records** (`custody.json`: the owner's two custody locations; `generation/`: drafting records; `import_approval_*.json`) | `data_pipeline/data/overrides/kc_review/` | ignored (`overrides/**`) |

The older header-only `final/kc_components.csv`, `final/prerequisites.csv` (and `questions.csv`, `notes.csv`) placeholders predate this contract, use a different header and are not read or written by the loader; they are left untouched.

No curated file exists yet. Neither Git nor the database keeps history of private files, so the owner needs dated snapshots and a private backup.

## 12. Released graph snapshot and lifecycle overlay (D15, RECOMMENDED; implemented)

Runtime consumers must **never traverse raw KC and edge rows**. They load an explicitly released snapshot, `final/kc_graph/released_graph_<seq>.json`, written only by a passing loader run and containing: the active, approved KCs; the released edges; the vocabulary version; the review-log head hash and anchor reference; the lifecycle-log head hash; the source pins used; and a digest of the whole snapshot.

A consumer (`app.services.graph_snapshot.load_released_graph`, implemented) **refuses to load, and the caller falls back to "no remediation graph available" plus teacher escalation, never to unfiltered rows**, when: the snapshot's digest does not verify; its lifecycle head hash differs from the lifecycle log's current head (`SNAPSHOT_LIFECYCLE_MISMATCH`); a retirement record is missing for a KC the snapshot excludes (`LIFECYCLE_MISSING`); a retirement's digest is stale (`LIFECYCLE_STALE`); or any retired KC appears in a traversable path (`RETIRED_KC_IN_PATH`). How the snapshot file reaches a remote runtime is an open owner choice (R1). No database column or table is added. The snapshot also carries a digest-covered `kc_content` section (objective, misconceptions, version) used only by the import plan.

## 13. Decision status

See the full table, with blockers, in [`PHASE_5_DECISION_MATRIX.md`](PHASE_5_DECISION_MATRIX.md). Only the header names and column order (sections 2 and 3) are OWNER-INSTRUCTED.
