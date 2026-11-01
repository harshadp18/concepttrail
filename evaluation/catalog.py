"""The metric catalogue: what can be measured automatically, what needs people, what is blocked.

`kind`:
  software_correctness  the software does what its specification says (ground truth is the spec)
  automated_property    a countable property of stored content (not a quality judgement)
  proxy                 a computable stand-in for quality; useful for triage, never an accuracy
  human_quality         educational quality; ONLY independent human review can establish it
  outcome               learning effect; needs real longitudinal learner data
  ai_review             an AI model reviewed AI-generated content; never a human review
  synthetic             behaviour on synthetic data; evidence about code/simulator, not learners
`automation`: automated | human_required | blocked (cannot be measured until data/decisions exist).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    id: str
    suite: str
    name: str
    kind: str
    automation: str
    ground_truth: str
    blocker: str = ""


M = Metric
CATALOG: tuple[Metric, ...] = (
    # --- deterministic answer scoring ---------------------------------------------------
    M(
        "scoring.conformance",
        "scoring",
        "Evaluator agrees with the scoring specification",
        "software_correctness",
        "automated",
        "engineer-constructed cases from the written rules",
    ),
    M(
        "scoring.type_coverage",
        "scoring",
        "Question types covered by constructed cases",
        "software_correctness",
        "automated",
        "case file",
    ),
    # --- question generation / bank --------------------------------------------------------
    M(
        "questions.structure",
        "questions",
        "Servable: deterministic key, option and type rules hold",
        "automated_property",
        "automated",
        "stored rows",
    ),
    M(
        "questions.key_position_bias",
        "questions",
        "Correct-answer position distribution",
        "automated_property",
        "automated",
        "stored rows",
    ),
    M(
        "questions.longest_correct_cue",
        "questions",
        "Correct option is also the longest",
        "proxy",
        "automated",
        "stored rows",
    ),
    M(
        "questions.passage_dependence",
        "questions",
        "Stem refers to text the student cannot see",
        "proxy",
        "automated",
        "regex over stems; misses unlabelled dependence",
    ),
    M(
        "questions.near_duplicates",
        "questions",
        "Near-duplicate stems within the bank",
        "proxy",
        "automated",
        "word-trigram similarity",
    ),
    M(
        "questions.option_explanations",
        "questions",
        "Options with an explanation",
        "automated_property",
        "automated",
        "stored rows",
    ),
    M(
        "questions.source_page_resolvable",
        "questions",
        "Cited page exists as a stored content unit",
        "automated_property",
        "automated",
        "database lookup (existence, not support)",
    ),
    M(
        "questions.kc_coverage",
        "questions",
        "Questions per knowledge component",
        "automated_property",
        "automated",
        "stored rows",
    ),
    M(
        "questions.review_status",
        "questions",
        "Questions with a recorded human review",
        "automated_property",
        "automated",
        "verification.reviews",
    ),
    M(
        "questions.key_correct",
        "questions",
        "Stored answer key is correct (blind reviewer agrees)",
        "human_quality",
        "human_required",
        "independent subject-expert answers",
        "no human reviews recorded",
    ),
    M(
        "questions.unambiguous",
        "questions",
        "Question has one defensible answer",
        "human_quality",
        "human_required",
        "independent subject-expert judgement",
        "no human reviews recorded",
    ),
    M(
        "questions.kc_alignment",
        "questions",
        "Question assesses its knowledge component",
        "human_quality",
        "human_required",
        "reviewer rating",
        "no human reviews recorded",
    ),
    M(
        "questions.age_language_fit",
        "questions",
        "Suitable for the class and language",
        "human_quality",
        "human_required",
        "reviewer rating (Hindi: Hindi-fluent reviewer)",
        "no human reviews recorded",
    ),
    M(
        "questions.distractor_quality",
        "questions",
        "Distractors plausible and instructive",
        "human_quality",
        "human_required",
        "reviewer rating",
        "no human reviews recorded",
    ),
    M(
        "questions.copied_wording",
        "questions",
        "Copies textbook wording",
        "proxy",
        "automated",
        "10-word shingles at generation time; paraphrase copying not detected",
    ),
    # --- retrieval ---------------------------------------------------------------------------
    M(
        "retrieval.index_integrity",
        "retrieval",
        "Chunks resolve to units, sources, pages, hashes",
        "automated_property",
        "automated",
        "database",
    ),
    M(
        "retrieval.filter_leakage",
        "retrieval",
        "Retrieval returns nothing outside the learner scope",
        "software_correctness",
        "automated",
        "scope tests against the live index (tests)",
    ),
    M(
        "retrieval.recall_mrr_ai_labels",
        "retrieval",
        "Recall@k / MRR on AI-derived relevance",
        "proxy",
        "automated",
        "relevance derived from AI-generated objectives (not independent)",
    ),
    M(
        "retrieval.recall_mrr",
        "retrieval",
        "Recall@k / MRR on human-judged relevance",
        "human_quality",
        "human_required",
        "human-labelled query to page relevance",
        "no human-labelled retrieval cases exist",
    ),
    # --- explanations / citations --------------------------------------------------------------
    M(
        "explanation.citation_resolves",
        "explanation",
        "Every cited label maps to retrieved evidence",
        "software_correctness",
        "automated",
        "captured model outputs + evidence",
    ),
    M(
        "explanation.lexical_support",
        "explanation",
        "Explanation sentences lexically overlap cited text",
        "proxy",
        "automated",
        "token overlap; cannot detect a wrong inference from right words",
        "no captured outputs",
    ),
    M(
        "explanation.supported",
        "explanation",
        "Claims are supported by the cited page",
        "human_quality",
        "human_required",
        "independent reviewer judgement per claim",
        "no captured outputs, no reviewers",
    ),
    M(
        "explanation.correct",
        "explanation",
        "Explanation is educationally correct and clear",
        "human_quality",
        "human_required",
        "independent subject-expert rating",
        "no human-authored prompts, no reviewers",
    ),
    M(
        "explanation.abstention",
        "explanation",
        "Abstains when evidence is insufficient",
        "human_quality",
        "human_required",
        "human-labelled answerable / unanswerable prompts",
        "no labelled prompts",
    ),
    # --- BKT ---------------------------------------------------------------------------------
    M(
        "bkt.known_answers",
        "bkt",
        "Update equations match hand-computed vectors",
        "software_correctness",
        "automated",
        "hand-computed vectors",
    ),
    M(
        "bkt.fit_pipeline",
        "bkt",
        "Fitting recovers known parameters on synthetic learners",
        "software_correctness",
        "automated",
        "synthetic data (pipeline check only)",
    ),
    M(
        "bkt.real_prediction",
        "bkt",
        "Held-out log loss / Brier / calibration on real learners",
        "outcome",
        "blocked",
        "real, consented, longitudinal responses",
        "5 real attempts from 1 learner",
    ),
    M(
        "bkt.synthetic_recovery",
        "bkt",
        "Parameter recovery, held-out prediction, robustness on synthetic learners",
        "synthetic",
        "automated",
        "known generating parameters (evaluation.bkt_synthetic)",
    ),
    M(
        "adaptive.synthetic_policy_comparison",
        "adaptive",
        "Policy vs baselines on simulated learners, adverse conditions",
        "synthetic",
        "automated",
        "simulator hidden state (evaluation.policy_simulation)",
    ),
    M(
        "content.ai_review",
        "questions",
        "Whole-bank AI review: defects repaired, withdrawn, escalated",
        "ai_review",
        "automated",
        "AI reviewer judgement (data_pipeline.content_review)",
    ),
    M(
        "retrieval.synthetic_regression",
        "retrieval",
        "Chapter-hit regression on AI-derived queries; abstention probes",
        "synthetic",
        "automated",
        "KC metadata (ai_generated_unverified)",
    ),
    M(
        "explanation.synthetic_regression",
        "explanation",
        "Citation validity, abstention, arithmetic, language on AI-authored prompts",
        "synthetic",
        "automated",
        "deterministic checks on live local-model answers",
    ),
    # --- adaptive ----------------------------------------------------------------------------
    M(
        "adaptive.policy_conformance",
        "adaptive",
        "Recommendation matches the written policy",
        "software_correctness",
        "automated",
        "engineer-constructed cases from the written policy",
    ),
    M(
        "adaptive.simulation",
        "adaptive",
        "Policy behaviour on simulated learners",
        "proxy",
        "automated",
        "synthetic learners; describes the simulator only",
    ),
    M(
        "adaptive.learning_gain",
        "adaptive",
        "Recommendations improve learning",
        "outcome",
        "blocked",
        "controlled comparison on real learners",
        "no real learners; completion is not learning",
    ),
)

BY_ID = {m.id: m for m in CATALOG}
assert len(BY_ID) == len(CATALOG), "duplicate metric id"
