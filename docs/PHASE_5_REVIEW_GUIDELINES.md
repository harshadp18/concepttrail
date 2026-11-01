# Phase 5: review guidelines for KCs and prerequisite edges (revision 4, tooling implemented)

The process the loader and the review tooling are built against. Labels as in `PHASE_5_CSV_CONTRACT.md`: **IN PRINCIPLE**, **RECOMMENDED**, **PROPOSED**, **INVESTIGATION**. **Nothing here is approved by explicit owner instruction.** Revision 4: the tooling is implemented in `data_pipeline/kc_graph/` (section 11) and tested with synthetic data only. No real reviewer, register, review event, custody location or approval exists; the tooling must not be used for real reviews until R2 and R4 are settled. Column definitions are in [`PHASE_5_CSV_CONTRACT.md`](PHASE_5_CSV_CONTRACT.md).

## 1. Principles

1. **Algorithms decide; AI writes.** A model may draft rows. It never sets an approval outcome, reviewer identity, approval, review rationale or expert rationale, and never releases anything.
2. **Review completion is not approval.** They are recorded separately. **IN PRINCIPLE (D14):** a blanket owner attestation can record that a review round finished; it can never approve an individual KC or edge.
3. **Evidence before dependency.** An edge exists because the dependent skill *uses* the prerequisite. Chapter order is never evidence; `chapter_order` is prohibited.
4. **Fail closed.** Missing, stale, unmatched or unrecognised anything blocks release. Nothing is silently downgraded or carried over.
5. **No invented identities.** A reviewer is a registered person known by a code.

## 2. People, qualification and uniqueness (D12, RECOMMENDED)

**Register** `overrides/kc_review/people.json`, one entry per human:

| Field | Meaning |
|---|---|
| `code` | `RV-001`, … ; used as `author_id` and `reviewer_id`; unique |
| `roles` | any of `author`, `reviewer`, `senior_reviewer` |
| `subjects` | subjects the person is competent in |
| `qualification_basis` | short private note on why (for example, teaching experience); never published |
| `active` | boolean |

No names or contact details appear in the repository, the CSVs or the log.

**What the loader checks (it can):** the code exists and is active; the role is `reviewer` or higher; `subjects` covers the record (for an edge, the subjects of **both** endpoint KCs; two reviewers who together cover both subjects are acceptable for a cross-subject edge); the reviewer is not the record's `author_id`; the two approving reviewers have different codes; neither event's basis is an owner attestation; the two rationales are not identical text. A reviewer who authored an endpoint KC (not the edge) raises the warning `REVIEWER_AUTHORED_ENDPOINT`; whether that should be blocking is an owner choice.

**What the loader cannot do:** prove that two codes belong to two different real people, or that a person is qualified. **The owner verifies this privately.** The owner writes a **write-once register verification** `overrides/kc_review/people_verification_<date>.json` stating that each code is one distinct real person who is qualified as recorded, bound by SHA-256 to the register's digest. If the register changes after verification, the loader reports `REGISTER_NOT_VERIFIED` and rejects every event from changed entries. The verification is the owner's own statement, like the Phase 4 attestations; it is not independent proof.

## 3. Workflow

| Stage | Who | Output | Status afterwards |
|---|---|---|---|
| 1. Candidate | a human author (`author_id`) or a model draft (`origin=ai_drafted`) | a CSV row | `needs_review` |
| 2. Intake check | the loader, dry run | shape, key, vocabulary and reference errors | unchanged |
| 3. KC review | one qualified reviewer, not the author | a `review` event | `approved`, `rejected`, or `needs_review` (revision required) |
| 4. Edge proposal | an author or a model draft | an edge row; both endpoint KCs must be approved before the edge can be | `needs_review` |
| 5. Edge review | **two independent qualified reviewers** (pilot) | two `review` events, each with rationale and evidence assessment | `approved` only if both approve |
| 6. Revision | the author | a revised row; a substantive change bumps the KC version | back to stage 3 or 5 |
| 7. Release | the loader, then the owner | a release manifest and a released graph snapshot | edges traversable only here |

`in_review` marks an assignment; it is never a decision. If one reviewer approves and one rejects, the edge is **not** released until an `adjudication` event by a third qualified reviewer or the owner resolves it (`REVIEW_CONFLICT`).

## 4. Review event and hash chain (D12, RECOMMENDED; the exact specification)

**File:** `overrides/kc_review/review_log.jsonl`, one JSON object per line, appended in order. **Tamper-evident, not immutable storage:** it makes most changes detectable; it cannot prevent them.

**Event fields.**

| Field | Set by | Meaning |
|---|---|---|
| `seq` | tool | integer from 1, increasing by exactly 1 |
| `event_id` | tool | `RR-` plus `seq` zero-padded to 4 (`RR-0007`): the identity cited in `review_record_ids` |
| `event_type` | reviewer | `review`, `reaffirmation`, `clerical_confirmation`, `adjudication` |
| `record_type`, `record_key` | tool | `kc` with the `kc_id`; `edge` with `<prerequisite_kc_id>-><dependent_kc_id>` |
| `decision` | **reviewer** | `approved`, `rejected`, `revision_required` |
| `reviewer_id` | **reviewer** | register code |
| `decided_on` | **reviewer** | the date the reviewer states they decided |
| `recorded_at` | tool | UTC timestamp from the system clock when the event was written (never filled in by a model) |
| `rationale` | **reviewer** | written text; required for every `rejected`, `revision_required`, edge approval, `reaffirmation` and `clerical_confirmation` |
| `expert_rationale` | **reviewer** | for `expert_judgement` edges: what the dependent skill requires, why the prerequisite is necessary, and that it is not based on sequence |
| `evidence_assessment` | **reviewer** | per evidence token: `supports` (yes/no), a note, and the tool-added `source_sha256` and `passage_sha256` |
| `checklist` | **reviewer** | the section 6 items, each true or false |
| `row_digest` | tool | the full record digest of the row at review time |
| `pedagogical_digest` | tool | the pedagogical content digest at review time |
| `versions` | tool | KC: its `content_version`. Edge: the `content_version` of both endpoint KCs |
| `supersedes` | tool | earlier event IDs this event replaces (reaffirmation, adjudication) |
| `basis` | tool | always `individual_review` |
| `prev_hash` | tool | the previous event's `event_hash`; 64 zeros for `seq` 1 |
| `event_hash` | tool | `SHA-256` of the canonical JSON of the event without `event_hash` (UTF-8, sorted keys, no insignificant whitespace) |

Fields marked **reviewer** are entered by the registered reviewer; a model may not write them. The tool computes the rest.

**Verification** walks the log and checks: each `event_hash` recomputes; each `prev_hash` equals the previous `event_hash`; `seq` is consecutive and `event_id` matches it; every cited or superseded event has a lower `seq`; digests match the current CSV rows (otherwise `REVIEW_STALE`); every anchor matches the log.

**Anchors.** After each review session and before each release the tool writes a **write-once** `overrides/kc_review/anchors/anchor-<seq>.json` holding `seq`, `event_id`, `head_hash`, `event_count`, `recorded_at`. It refuses to overwrite an existing anchor, as the Phase 4 attestation records do, and the release manifest embeds the head hash.

| Tampering | Detected by the chain alone? | Detected against a separately kept anchor? |
|---|---|---|
| Edit an event in the interior | yes, unless every later hash is recomputed | yes, if the event is at or before an anchored `seq` |
| Delete an event in the interior | yes (`seq` gap, broken chain), unless the suffix is renumbered and rehashed | yes, if at or before an anchored `seq` |
| Reorder events | yes, unless rehashed | yes, if at or before an anchored `seq` |
| Truncate the end | **no** | yes, if an anchor has a higher `seq` or a different head |
| Replace the whole log with a consistent forgery | **no** | yes, unless the anchors were replaced too |

**Not detected even with anchors:** changes after the latest anchor; an attacker who controls the log and every anchor copy; a validly chained event written by someone who should not have written it (the chain shows *what* was written, not *who*; authorship rests on the controlled entry process and the register). A test in the repository checks this table against a reference implementation. Do not describe the log as immutable.

## 5. Anchor custody (D12, RECOMMENDED; the owner must confirm)

Every anchor is kept in **two separate, encrypted custody locations, neither of them the Git repository**, so that the copies do not share one failure or one access boundary:

1. **An owner-controlled offline backup:** an encrypted external drive kept disconnected and physically apart from the working machine.
2. **A separate encrypted backup location:** a different encrypted store (for example, another provider or device) under **different credentials**, not synced to the working machine's account.

Each copy has its own encryption key, stored separately from the data. A third copy inside `overrides/kc_review/anchors/` is a convenience only, not custody. Encryption protects confidentiality; **integrity comes from comparing hashes**, so verification never trusts a single location. A tampered log is detected only if at least one custody copy is intact.

**The owner must confirm** which locations, who holds the keys, and the anchoring cadence. Until then, the review log may be implemented and tested with synthetic data, but must not be used for real reviews.

## 6. Event types, quorum, independence and cost

| Event type | Purpose | Reviewers |
|---|---|---|
| `review` | the first judgement of a KC or edge | KC: 1. Edge: **2 independent** (pilot) |
| `reaffirmation` | re-judge a stale edge after an endpoint's version changed | 2 independent (pilot) |
| `clerical_confirmation` | confirm a non-substantive correction | 1, not the author |
| `clerical_confirmation` (`wording_only`) | reclassify a wording change to a P field | 2 independent (pilot) |
| `adjudication` | resolve two conflicting reviews | a third qualified reviewer, or the owner |

**Independence checks:** section 2. **By procedure, not code:** each reviewer forms a first judgement without seeing the other's decision; the owner audits a sample. **Cost:** about 2 × E × m reviewer-minutes (E edges, m minutes per review), plus the same per reaffirmation, plus K × m for KCs; the D11 pilot measures real E and m (an illustration of 100 edges at 8 minutes is about 27 reviewer-hours). Relaxing the two-reviewer rule is a separate owner decision and is not assumed.

**KC checklist:** one atomic skill; one measurable objective sentence; type and difficulty appropriate; each misconception real and correctly stated; source references resolve and support it; not a duplicate; subject right; distinct from any `SIMILAR_KEY` match (named). **Edge checklist:** the dependent skill cannot be done or understood without the prerequisite; direction correct; evidence supports it; not based on sequence; direct, not already implied by a longer path; strength reasonable; both endpoint KCs approved.

## 7. Re-review

Digests, versions and the `reaffirmation` procedure: contract, section 7. A substantive change invalidates approval and bumps the version; a non-substantive correction needs a documented `clerical_confirmation`; a stale edge needs a human `reaffirmation`; **nothing carries over automatically**.

## 8. Retirement and runtime visibility (D15, RECOMMENDED; implemented)

**Lifecycle is separate from review status.** Review status says whether a *definition is accepted*; lifecycle (`active` or `retired`) says whether the KC is *in use*. A retired KC stays `approved`. **No `retired` review status exists, and no database column or table is added.**

**Lifecycle log** `overrides/kc_review/lifecycle_log.jsonl`, hash-chained and anchored exactly as in sections 4 and 5. Each event (`LC-` plus `seq`) has:

| Field | Meaning |
|---|---|
| `kc_id`, `action` (`retire` or `reinstate`) | the KC and the action |
| `authorised_by` | register code of the owner or a `senior_reviewer`; a model cannot |
| `reason` | written text, required |
| `effective_at` | the timestamp the authoriser gives; never filled in by a model |
| `replacement_kc_ids` | zero or more KCs (a split has several; a merge points at one) |
| `edge_resolution` | one entry per prerequisite edge touching the KC (below) |
| `learner_history_note` | the policy decision on learner records (below) |
| `kc_row_digest` | the KC's full digest at retirement, so a later edit is visible (`LIFECYCLE_STALE`) |
| chain fields | `seq`, `prev_hash`, `event_hash`, `recorded_at` |

**Existing prerequisite edges.** No edge is deleted or rewritten. Before a retirement takes effect, every approved edge touching the KC must be resolved: **rejected** through ordinary review events, or **superseded** by a new proposed edge on the replacement KC that goes through normal review. `edge_resolution` records which. An approved edge still using a retired KC is `EDGE_TOUCHES_RETIRED_KC` and blocks release.

**Historical mastery.** `student_kc_state` rows are never deleted or altered. A retired KC receives no new practice or recommendations. **No automatic mastery transfer exists:** whether old mastery seeds a replacement is a Phase 9 policy decision.

**Runtime visibility (the open problem, with a proposed answer).** With no lifecycle column, runtime services reading PostgreSQL cannot see retirement. **Proposal:** runtime consumers do not read raw KC and edge rows. They load an explicitly **released graph snapshot** (contract, section 12), written only by a passing loader run, which excludes retired KCs and records the review-log and lifecycle-log head hashes. The consumer **fails closed** when: the snapshot digest does not verify; its lifecycle head differs from the lifecycle log (`SNAPSHOT_LIFECYCLE_MISMATCH`); a retirement record is missing (`LIFECYCLE_MISSING`) or its digest is stale (`LIFECYCLE_STALE`); or a retired KC appears in a traversable path (`RETIRED_KC_IN_PATH`). It then serves no remediation graph and escalates to the teacher; it never falls back to unfiltered rows. Implemented: `data_pipeline/kc_graph/lifecycle.py` (log and checks), `release.py` (snapshot) and `app/services/graph_snapshot.py` (`verify_snapshot`, `load_released_graph`, which returns None on any failure). Lifecycle anchors are `lifecycle-anchor-<seq>.json`, in the same custody locations. How the snapshot reaches a remote runtime (a deployed artifact versus another mechanism) is an open owner choice (matrix, R1); no schema change is needed to decide it.

## 9. Release eligibility

A record is traversable only if all hold:

1. validation has no errors anywhere, including log verification, anchor matching and register verification;
2. the edge is `approved` with the required number of current, individual approving events from independent qualified reviewers, none superseded or in conflict;
3. its evidence is valid, assessed and not stale (contract, section 6);
4. both endpoint KCs are `approved`, **active**, with current approving events and matching versions;
5. the approved graph is acyclic;
6. the released snapshot's digests and lifecycle head match.

Everything else (`needs_review`, `in_review`, `rejected`, revision required, stale, unmatched, retired) is excluded and reported.

## 10. Local drafting with a model (D17, RECOMMENDED, conditional)

**No drafting is authorised yet.** A model may draft KC and edge rows only if **all** hold:

1. Local inference only: Qwen 3.5 9B through Ollama on the owner's machine. Nothing leaves it.
2. A **separate rights record** created by the owner **explicitly names KC drafting and prerequisite-edge drafting** (proposed use names `local_llm_kc_drafting`, `local_llm_prerequisite_edge_drafting`). The existing named uses cover objective drafting, not these; **no existing record authorises this use**, and the authorisation gate refuses unknown uses by default.
3. A provider adapter exists, tested with mocks.
4. Output is constrained to a schema, then validated; a draft that fails is discarded, not repaired by hand into an approval.
5. Every draft enters review as `needs_review` with `origin=ai_drafted` and an `origin_ref` to a generation record (model ID and digest, prompt version, a hash of the input references; no textbook text).
6. **Hindi drafting is excluded** until output quality is evaluated.
7. **A model may never set** an approval outcome, reviewer identity, approval, rationale or expert rationale, nor create vocabulary entries.

**External processing of textbook content remains unapproved.** No rights record allows a provider to receive it, the gate refuses external uses by design, choosing Groq is not a rights decision, and terms, retention and data location are unreviewed.

| A model may | A model may not |
|---|---|
| draft rows within the conditions above | set `review_status` above `needs_review` |
| pre-fill a checklist as a suggestion for a human to confirm | write an event, rationale, reviewer code, approval outcome or expert rationale |
| run the loader's checks | approve, reject, adjudicate, retire or release anything; add a domain, facet or other vocabulary value |

The loader reports `AI_FIELD_VIOLATION` and `AI_SELF_APPROVAL` for violations.

## 11. Operating the tooling (revision 4)

`python -m data_pipeline.kc_graph <command>`. Every command is read-only unless it says otherwise; none validates and imports in one step.

| Step | Who | Command | Writes |
|---|---|---|---|
| Dry-run validation and coverage | anyone | `validate` | `logs/kc_graph/` only |
| Check the register and its verification | anyone | `verify-register` | nothing |
| Verify the review and lifecycle chains and anchors | anyone | `verify-logs` | nothing |
| Record the register verification | **owner** | `register-verify --statement-file F --date D` | write-once `people_verification_<date>.json` |
| Record one review | the **registered reviewer** fills an entry file with the reviewer fields only; the tool adds the rest | `review-append --entry F` | appends one event |
| Record one retirement or reinstatement | a verified **senior reviewer** or the owner | `lifecycle-append --entry F` | appends one lifecycle event |
| Anchor after each session | the owner | `anchor` (needs `custody.json` with two absolute locations outside the repository) | write-once anchors in `anchors/` and both custody locations |
| Release | the owner | `release` | write-once snapshot and manifest in `final/kc_graph/` |
| Verify a snapshot | anyone | `verify-snapshot --snapshot S` | nothing |
| Pilots | reviewers fill sheets; anyone scores | `taxonomy-forms`, `taxonomy-score`, `evidence-score` | sheets in `curated/kc_graph/pilot/`, reports in `logs/` |

An entry file holds only the reviewer fields of section 4 (`event_type`, `record_type`, `record_key`, `decision`, `reviewer_id`, `decided_on`, `rationale`, `expert_rationale`, `evidence_assessment` with `token`, `supports`, `note`, `checklist`, `supersedes`, `clerical_class`, `old_pedagogical_digest`); any other field is refused. The tool refuses an entry from an unregistered, unverified, unqualified or authoring reviewer, an entry without a required rationale or a complete checklist, and an append to a log that does not verify. **The tool cannot tell who typed the entry**: authorship rests on the controlled entry process and the register, as section 4 says. A model must never write an entry file.

`custody.json` (owner-created, private): `{"locations": [{"label": "...", "path": "/absolute/path"}, {"label": "...", "path": "/absolute/path"}]}`. Two distinct locations, neither inside the repository. **No custody location has been designated.**

