# ConceptTrail completion audit (2026-11-01)

Scope: every locally completable non-frontend, non-deployment task. Verified state at the end of
the work session; evidence paths are given for every claim. Labels used: **software correctness**
(code matches its written specification), **AI review** (an AI model reviewed AI-generated
content; not a human review), **synthetic** (evidence about code and simulators, not learners),
**human review** and **real learner evidence** (none exist yet).

## 1. Completed and verified

| Area | Code | Evidence |
|---|---|---|
| Synthetic learner generator | `evaluation/synthetic_learners.py` | `tests/unit/test_evaluation_tools.py` (reproducible by seed, every record marked `SYNTHETIC-NOT-REAL-LEARNERS`) |
| Synthetic BKT calibration, held-out evaluation, robustness | `evaluation/bkt_synthetic.py` | section 2; vectorised equations equal the runtime scalar code to < 1e-12 (test) |
| Experimental (non-runtime) BKT configuration | `evaluation/configs/bkt_synthetic_calibration_v1.json` | labelled `EXPERIMENTAL - synthetic only`; runtime `bkt-provisional-v1` unchanged |
| Adaptive-policy simulation with baselines and adverse conditions | `evaluation/policy_simulation.py` | section 3 |
| Whole-bank AI content review and repair patch | `data_pipeline/content_review/` (`patch.py`, `records.py`; the review records and `patch_v1.json` are private, in `data_pipeline/data/overrides/content_review/`) | section 4; `tests/unit/test_content_review.py` |
| Original synthetic gap-fill (44 items) and verified-outcome gap-fill (6 KCs, 18 items) | `additions.py`, `outcome_kcs.py` | section 5; maths keys re-derived independently with SymPy and brute force |
| Retrieval regression and scope-leakage checks | `evaluation/retrieval_regression.py` | section 6 |
| Explanation and citation regression (live local model) | `evaluation/explanation_suite.py` | section 6 |
| Citation-repair defect fix (uncited answers) | `app/services/ai_generation.py` | `test_uncited_answer_gets_one_citation_repair_and_is_still_validated`; live answer rate 4/12 -> 9/12 |
| Teacher question review over HTTP | `app/api/v1/review.py` | `tests/unit/test_review_api_live.py` |
| Teacher interventions (service + routes, disabled until migration approval) | `app/services/interventions.py`, `app/api/v1/interventions.py`, `app/db/proposed_models.py` | `tests/integration/test_interventions_disposable.py` on a disposable database with `db/proposals/0002` applied |
| Release gate strengthened (coverage and source-rights gates added; AI review cannot satisfy human review) | `scripts/release_gate.py` | `tests/unit/test_release_gate_live.py`; gate fails 7/7 today, by design |
| Evaluation framework: two separated categories, one command | `evaluation/full.py`, `evaluation/catalog.py` (37 metrics) | `.local/evaluation/reports/full_*.md` |
| OpenAPI and frontend contract | `docs/openapi/openapi-v1.json`, `docs/FRONTEND_INTEGRATION.md` | `tests/unit/test_openapi_export.py` (18 paths) |

## 2. Synthetic BKT results (`python -m evaluation.bkt_synthetic`)

Synthetic only. Design: 6 synthetic KC types with known parameters; 400 learners x 15
opportunities per KC type (chosen from the size curve: errors plateau near 0.01-0.03 there);
5 calibration seeds (base 1000) per type; held-out learners from disjoint seeds (base 2000);
30 bootstrap refits; maximum likelihood under guess < 0.5 and slip < 0.5.

| KC type | truth (l0, t, g, s) | fitted (seed 0) | mean abs error over 5 seeds | truth in bootstrap 95% CI |
|---|---|---|---|---|
| typical | 0.25, 0.12, 0.20, 0.08 | 0.263, 0.129, 0.187, 0.088 | 0.028, 0.006, 0.007, 0.004 | 4/4 |
| hard | 0.10, 0.06, 0.15, 0.10 | 0.087, 0.060, 0.151, 0.103 | 0.019, 0.004, 0.003, 0.003 | 4/4 |
| guessy | 0.30, 0.10, 0.35, 0.08 | 0.327, 0.088, 0.353, 0.083 | 0.020, 0.009, 0.006, 0.005 | 4/4 |
| careless | 0.35, 0.15, 0.15, 0.18 | 0.355, 0.151, 0.135, 0.188 | 0.011, 0.005, 0.011, 0.010 | 3/4 |
| fast | 0.15, 0.30, 0.20, 0.06 | 0.140, 0.314, 0.169, 0.060 | 0.016, 0.015, 0.016, 0.002 | 3/4 |
| high_prior | 0.60, 0.10, 0.20, 0.07 | 0.607, 0.114, 0.188, 0.071 | 0.023, 0.011, 0.018, 0.003 | 4/4 |

- Coverage of the bootstrap intervals: 22/24 parameters (nominal 95%).
- Held-out prediction: fitted BKT is close to the true-parameter oracle (typical KC log loss
  0.479 vs oracle within 0.001) and better than non-adaptive baselines (global mean, learner
  running mean) on log loss, Brier and expected calibration error for every KC type. The
  provisional runtime parameters are close on typical skills and worse on guess-prone, fast and
  high-prior skills.
- Mastery decisions at the 0.95 threshold are conservative: false mastery about 1% of
  opportunities, missed mastery 24-53% of truly known opportunities.
- Sample size: at 50 learners x 5 opportunities the worst parameter error is about 0.08; it falls
  to about 0.01-0.03 at 400-800 learners; p_l0 is the hardest to pin down, p_s the easiest.
- Sparse/incomplete histories (variable length, 30% truncated): parameters still recovered
  within about 0.02; held-out log loss rises from 0.48 to 0.52.
- Model mismatch (forgetting, learner heterogeneity, item variation, irregular practice, all
  combined): fitted BKT stays best among the compared models but its parameters absorb the
  mismatch (e.g. forgetting shows up as higher slip), so "recovered" values are no longer the
  generating ones. Calibrating on a homogeneous population and testing on a heterogeneous one
  costs little log loss in this generator.
- Identifiability: bootstrap correlations between l0 and t and between g and s are reported per
  KC type; with short sequences l0 trades off against t, which is why p_l0 has the widest
  intervals.
- Limitation: none of this is evidence about real CBSE learners. Real data: 5 attempts from 1
  learner; `python -m evaluation.bkt_calibration real` refuses to fit (needs >= 2000 events and
  >= 30 learners). Runtime parameters remain `bkt-provisional-v1`, provisional and uncalibrated.

## 3. Synthetic learning-outcome (policy) results (`python -m evaluation.policy_simulation`)

Synthetic only. 12 KCs (4 class-6 foundations, 8 class-7 targets), learning gated by true
prerequisites, 80 practice opportunities, 5 held-out seeds (100-104) x 60 learners per condition
and policy; the same simulated learners and noise for every policy. Final simulated mastery of
target KCs (mean [95% CI]):

| condition | random | fixed difficulty | non-adaptive sequence | prerequisite-first | ConceptTrail |
|---|---|---|---|---|---|
| base | 0.430 [0.40-0.46] | 0.437 [0.40-0.47] | 0.533 [0.50-0.57] | 0.690 [0.66-0.72] | 0.716 [0.68-0.75] |
| noisy answers | 0.430 | 0.437 | 0.533 | 0.610 [0.58-0.64] | 0.630 [0.59-0.67] |
| wrong prerequisite graph | 0.430 | 0.437 | 0.530 | **0.609 [0.57-0.65]** | 0.573 [0.53-0.61] |
| miscalibrated BKT | 0.430 | 0.437 | 0.533 | **0.690 [0.66-0.72]** | 0.452 [0.42-0.48] |
| wrong difficulty labels | 0.430 | 0.437 | 0.533 | 0.685 | 0.711 |
| sparse budget (25) | 0.195 | 0.203 | 0.236 | 0.138 | 0.231 |
| forgetting 4% | 0.084 | 0.094 | 0.076 | 0.083 | 0.100 |
| slower held-out population | 0.190 | 0.198 | 0.237 | 0.323 | 0.376 |

- ConceptTrail and the simple prerequisite-first rule are not distinguishable in the base
  condition (overlapping intervals); both beat random and non-adaptive practice.
- ConceptTrail is worse when its graph is wrong and much worse when its BKT is miscalibrated
  (false mastery about 4 KCs per learner); with forgetting it neglects prerequisites more.
- Threshold sensitivity: lowering the mastery target to 0.85 raises false mastery from 0.18 to
  0.77 per learner with no gain in final mastery; 0.98 reduces it to 0.02 at the cost of more
  practice on already-known KCs.
- No implementation defect was found in the recommender during simulation; the weaknesses are
  dependencies on graph quality and BKT calibration, which is why both are release-gated.
- Not a claim about real learning gain.

## 4. AI-assisted content review (`data_pipeline/content_review`)

Reviewer: an AI model (Claude), reading every item in full. Not a human or academic review;
recorded as `ai_review` with `human_reviewed: false`; `review_status` unchanged (`demo_release`).

- Inspected: 460 questions (with options, keys, explanations, KC mapping, difficulty, source
  references), 137 KCs, 97 prerequisite edges. Disputed facts were checked against the stored
  chapter text (e.g. who sprinkles the drops in "A Bottle of Dew", King Bruce and the spider in
  "Try Again", the swan story in "माँ, कह एक कहानी", the land-use percentages), and maths keys with
  SymPy.
- Verdicts: 363 no defect found, 44 repaired, 30 withdrawn (`active = false`), 23 escalated.
- Defects repaired include: 6 wrong answer keys (e.g. 1+...+10+...+1 = 100 keyed False; Paris
  not keyed as Eastern Hemisphere; 45.64% vs 23.41% net sown area swapped; Ca(OH)2 + CO2 called a
  single-product combination), 4 items with no correct option, 2 with two correct options,
  factual errors in stems (aluminium as Group 1/2, copper-silver nitrate colour change reversed,
  soil as biotic), explanations contradicting their key or missing, answer clues in options,
  corrupted Devanagari, misleading "International system" stems.
- Withdrawn (cannot be safely corrected): false premises (e.g. seven Hindi items saying a hunter
  killed a child), FeS "does not react with HCl", unsound language items, off-KC items.
- Graph: 21 indefensible edges removed (e.g. latitude -> startup ecosystem), 17 weak edges
  escalated; 7 KC names/descriptions corrected (four KCs all named "Scientific method"; a KC
  description that misread the poem); 3 duplicate/overlapping KC pairs escalated.
- 44 findings escalated for human judgement are listed in `patch_v1.json` (`escalations`).
- Application: the patch (with before/after values for every change) was applied and verified
  on a disposable restored copy only: 522 questions, 492 active, all deliverable, every KC >= 3
  active questions, graph acyclic (76 edges), all `demo_release`, idempotent re-run, refuses rows
  that changed or are not `demo_release`. **It was not applied to the persistent database**
  (owner decision): `python -m data_pipeline.content_review.patch apply --database-url URL --apply`
  after a backup.
- Remaining AI-review limitations: lexical support of each question by its cited page was not
  verified for all 460 items (page existence was: 460/460); stored single-choice keys of older
  items still favour B (learners see a per-learner shuffled order); about half of older
  single-choice items still have the correct option as the longest.

## 5. Content coverage (all 25 class-subject combinations)

Verified (human-approved) coverage: **0/25**. Demo coverage is one chapter per combination
(seven chapters for Class 10 Social Science after the outcome-based gap fill).

| | English | Hindi | Mathematics | Science | Social Science |
|---|---|---|---|---|---|
| 6 | demo 1 ch, 6 KC | demo 1 ch, 6 KC (+5 synthetic items) | demo 1 ch, 6 KC | demo 1 ch, 6 KC (+1) | demo 1 ch, 6 KC |
| 7 | demo 1 ch, 6 KC | demo 1 ch, 6 KC (+6) | demo 1 ch, 6 KC (+3) | demo 1 ch, 4 KC | demo 1 ch, 6 KC |
| 8 | demo 1 ch, 6 KC | demo 1 ch, 3 KC (+2) | demo 1 ch, 6 KC (+1) | demo 1 ch, 6 KC (+6) | demo 1 ch, 6 KC (+1) |
| 9 | demo 1 ch, 6 KC (+3) | demo 1 ch, 6 KC (+8) | demo 1 ch, 6 KC (+2) | demo 1 ch, 5 KC | demo 1 ch, 6 KC |
| 10 | demo 1 ch, 5 KC | **gap** | demo 1 ch, 6 KC (+4) | demo 1 ch, 6 KC | demo 7 ch, 12 KC (+18 outcome-based) |

- "+n" = original synthetic gap-fill items (no textbook citation). The 6 Class 10 Social Science
  outcome-based KCs quote official CBSE learning outcomes verbatim (catalogue awaiting a human
  spot-check).
- Class 10 Hindi: no usable source text (2 of 28 PDFs yield only `text_unusable` pages) and no
  verified learning objectives in the project; nothing was generated, and nothing synthetic can
  satisfy the coverage gate.
- Other chapters (about 300) have no KCs: extending them needs verified objectives or
  authorised source processing; generating KCs from chapter titles would invent objectives.

## 6. Retrieval and explanation evaluation (synthetic regression; no human labels exist)

- Retrieval regression, 137 AI-derived chapter queries + 10 probes: chapter hit@5 100% with a
  class+subject filter (nearly trivial), 96.4% subject-only, 89.0% unfiltered (Hindi subject
  66.7% unfiltered). Scope leakage 0 of 2,055 returned pages. Finding: the 0.35 retrieval floor
  does **not** gate off-corpus or vague queries (5/6 and 4/4 scored above it); abstention relies
  on the model's sufficiency check. Not re-tuned on 10 probes; needs human-labelled cases.
- Explanation suite (16 AI-authored prompts, live Qwen, demo retrieval): unanswerable prompts
  abstained 4/4 in every run; answerable answered 4/12 before the citation-repair fix, then 9/12
  and 8/12 (one local-model timeout) in the two runs after it; every answered response had valid
  citations; 0 invented citations; 0 arithmetic or language mismatches; 2-5 sentences per run
  below the lexical-support proxy floor. Run-to-run variation is from the local model. Captured
  answers are in `.local/evaluation/explanations_*.jsonl` for human review.
- Reports: `.local/evaluation/reports/full_20261101T102123Z.md` (index of all categories),
  `bkt_synthetic_20261101T102919Z.md`, `explanation_suite_20261101T101631Z.md`, and the
  policy-simulation and retrieval-regression reports in the same folder.
- Human-labelled retrieval, explanation correctness and claim support: not measured (no data).

## 7. Backend and API verification

- Tests: 972 passed, 1 skipped with disposable Redis and PostgreSQL services running; the
  skipped seed rollback test passes on a fresh disposable baseline database (its counterpart runs
  on the development database). Ruff check and format clean; OpenAPI export current; `git diff
  --check` clean; `pip-audit` on the locked runtime set: no known vulnerabilities.
- Workflows covered by tests: login (student PIN, teacher password), enrollment and grade scope,
  curriculum and chapter topics, question delivery, all scorable types (single choice, multiple
  select, true/false, numeric; short answer never served), invalid answers, idempotent replay,
  concurrent attempts on disposable PostgreSQL (row lock, no lost events), BKT updates,
  recommendation, doubts with citations and abstention, model timeout, teacher isolation,
  teacher review, interventions (disposable DB), rate limiting (shared Redis), CORS, trusted hosts,
  security headers, body limit, readiness, error envelope.
- Running dev container rebuilt with current code: review queue 200 for the teacher, 403 for the
  student; interventions 503 (disabled).
- Teammate sign-off still needed for owner-added routes in teammate areas: recommendation,
  doubts, chapter topics, teacher review, interventions.

## 8. Database and Git preservation

- Persistent database: row-level MD5 fingerprint of all 26 tables plus the Alembic version taken
  at the start and at the end are identical. No migration applied (Alembic `0001`); the
  intervention migration exists only in `db/proposals/` and was tested on disposable databases.
- Backups taken before work: `.local/backups/` (git-ignored), restore verified.
- Git: HEAD `7bf3cc9`, staged tree `c86bd749...` unchanged (41 staged files); nothing staged,
  committed or pushed. `.env` and `.local/` remain ignored; secret scan clean.
- New in this phase: `app/api/v1/review.py`, `app/api/v1/interventions.py`,
  `app/db/proposed_models.py`, `app/services/interventions.py`, `data_pipeline/content_review/*`,
  `evaluation/{synthetic_learners,bkt_synthetic,policy_simulation,retrieval_regression,explanation_suite,full}.py`,
  `evaluation/configs/bkt_synthetic_calibration_v1.json`, `tests/unit/test_content_review.py`,
  `tests/unit/test_review_api_live.py`, `tests/integration/test_interventions_disposable.py`,
  this file. Modified: `app/main.py`, `app/core/config.py`, `app/services/learner_scope.py`,
  `app/services/ai_generation.py`, `scripts/release_gate.py`, `evaluation/catalog.py`,
  `docs/TECHNICAL_REFERENCE.md` (section 13), `evaluation/benchmarks/v1/manifest.json`,
  `docs/FRONTEND_INTEGRATION.md`, `docs/openapi/openapi-v1.json`, and tests
  (`test_evaluation_framework.py`, `test_evaluation_tools.py`, `test_ai_adaptive_graph.py`,
  `test_openapi_export.py`, `test_release_gate_live.py`).

## 9. External dependencies (cannot be completed by local code or synthetic data)

| Dependency | Evidence or decision required |
|---|---|
| Independent subject-expert review | Blind reviews of the bank (packet: `python -m evaluation.review make`), two reviewers per item, adjudication; decisions on the 44 escalations and the patch |
| Owner decision on the content patch | Approve applying `patch_v1.json` to the persistent database (after a backup) |
| Owner acknowledgement of external-model processing | During the requested AI review, short stored textbook passages were read by an external model (Claude) to verify disputed items; the rights records authorise only local processing. Record a decision or exclusion |
| Independent Hindi review | Hindi-fluent reviewer for Hindi items and for the legacy-font extraction corruption |
| Verified curriculum material | Official learning outcomes for subjects other than Class 10 Social Science; usable Class 10 Hindi source text |
| Human spot-check of the official outcomes catalogue | Confirm the 63 parsed Class 10 Social Science outcomes |
| Source-rights authorisation for production display | Purpose-specific permissions recorded for production use |
| School/teacher approval | Genuine approvals through the review workflow (AI review never counts) |
| Consent-based real learner data | >= 2000 scored events from >= 30 learners for BKT fitting; a controlled study for learning outcomes |
| Owner approval of the intervention migration | Apply `db/proposals/0002` after backup, then set `INTERVENTIONS_ENABLED=true` |
| Teammate sign-off | Owner-added routes in teammate-owned areas (section 7) |

## 10. Remaining engineering work

- Frontend implementation and integration (contract: `docs/FRONTEND_INTEGRATION.md`, OpenAPI).
- Deployment and production infrastructure (`deploy/`).

Everything else that remains is blocked on the external dependencies above, not on local code.
The production release gate (`python -m scripts.release_gate`) correctly fails all seven gates.
