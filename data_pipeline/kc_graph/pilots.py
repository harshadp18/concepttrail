"""D4 taxonomy assessment and D11 evidence pilot: forms, sampling and scoring (matrix A and B).

These tools prepare packages and compute metrics from sheets that **registered human
reviewers** fill in. They never assess anything themselves and a model must not fill a sheet.
Without two complete independent sheets the result is `pending_human_assessment`; no score,
agreement or consensus is ever produced from missing data.
"""

from __future__ import annotations

import collections
import csv
import io
import math
import random
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from data_pipeline.kc_graph.contract import SUBJECTS

# Appendix A: 30 synthetic skills; the provisional type is the author's key, hidden from
# reviewers until both have finished. Tests check this list against the decision matrix.
TAXONOMY_ITEMS: tuple[tuple[int, str, str, str], ...] = (
    (1, "english", "Identify the main idea of a short paragraph", "interpretation"),
    (2, "english", "Make a verb agree with its subject", "procedure"),
    (3, "english", "State the meaning of common prefixes", "vocabulary"),
    (4, "english", "Write a paragraph with a topic sentence", "application"),
    (5, "english", "Recall the parts of a formal letter", "fact"),
    (6, "english", "Explain what a metaphor is", "concept"),
    (7, "hindi", "Identify nouns and verbs in a sentence", "concept"),
    (8, "hindi", "Join two words by a sandhi rule", "procedure"),
    (9, "hindi", "Give the meaning of common idioms", "vocabulary"),
    (10, "hindi", "Answer an inference question on a short passage", "interpretation"),
    (11, "hindi", "Write a short formal leave application", "application"),
    (12, "hindi", "Recall the gender of everyday nouns", "fact"),
    (13, "mathematics", "Add two fractions with unlike denominators", "procedure"),
    (14, "mathematics", "Explain what equivalent fractions are", "concept"),
    (15, "mathematics", "Recall the multiplication tables up to 10", "fact"),
    (16, "mathematics", "Solve a word problem using a ratio", "application"),
    (17, "mathematics", "Read a value from a bar graph", "interpretation"),
    (18, "mathematics", 'State what "perimeter" means', "vocabulary"),
    (19, "science", "Classify materials as mixtures or pure substances", "concept"),
    (20, "science", "Name the three states of matter", "fact"),
    (21, "science", "Read a volume with a measuring cylinder", "procedure"),
    (22, "science", "Explain why ice floats on water", "application"),
    (23, "science", "Read a food-chain diagram", "interpretation"),
    (24, "science", 'State what "habitat" means', "vocabulary"),
    (25, "social_science", "Locate a place on a map using its coordinates", "procedure"),
    (26, "social_science", "Place events in order on a timeline", "application"),
    (27, "social_science", "Explain what a fundamental right is", "concept"),
    (28, "social_science", "Read a trend from a population table", "interpretation"),
    (29, "social_science", "Recall the capital of a given state", "fact"),
    (30, "social_science", 'State what "democracy" means', "vocabulary"),
)
TYPES = ("concept", "procedure", "fact", "vocabulary", "application", "interpretation")
NONE_FITS = "none_fits"
TAXONOMY_SHEET = (
    "skill_no",
    "subject",
    "skill",
    "reviewer_code",
    "assigned_type",
    "confidence",
    "none_fits",
    "none_fits_explanation",
    "note",
    "minutes",
)
ADJUDICATION_SHEET = ("skill_no", "adjudicator_code", "final_type", "note")
EVIDENCE_SHEET = (
    "edge_key",
    "subject",
    "stratum",
    "reviewer_code",
    "class",
    "evidence_tokens",
    "supports",
    "decision",
    "minutes",
    "disagreed",
    "adjudicated_class",
)
EVIDENCE_CLASSES = ("a", "b", "c")  # source-backed, expert-supported, not a real dependency
LIMITATIONS = (
    "Per-subject samples of about 20 have wide intervals (about +/-22 points).",
    "The pilot covers only the 10 pilot documents (Classes 8-10); it says little about Class 6-7.",
    "Candidates come from the pilot documents, biasing the evidence rate toward their content.",
    "A census of fewer than 100 edges is not a random sample.",
    "Classifying (a) versus (b) is a judgement; agreement is measured, not assumed.",
    "Early reviews take longer while reviewers learn, which inflates minutes per review.",
    "A rate from this pilot does not transfer automatically to other subjects, classes or sources.",
)


def _csv_text(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def reviewer_form() -> str:
    """One blank sheet: no key, no reviewer code (the reviewer enters their own)."""
    return _csv_text(
        TAXONOMY_SHEET,
        ((n, s, skill, "", "", "", "", "", "", "") for n, s, skill, _ in TAXONOMY_ITEMS),
    )


def adjudication_form(disagreements: Sequence[int]) -> str:
    return _csv_text(ADJUDICATION_SHEET, ((n, "", "", "") for n in disagreements))


def read_sheet(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    if not a or len(a) != len(b):
        return None
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = collections.Counter(a), collections.Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if expected == 1:
        return None  # undefined: both reviewers used one category throughout
    return round((observed - expected) / (1 - expected), 4)


def wilson(successes: int, n: int, z: float = 1.959964) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def _sheet_problems(rows: list[dict[str, str]], register_codes: set[str] | None) -> list[str]:
    out = []
    numbers = sorted(int(r["skill_no"]) for r in rows if r.get("skill_no", "").isdigit())
    if numbers != list(range(1, 31)):
        out.append("the sheet must have exactly skills 1-30, once each")
    codes = {r.get("reviewer_code", "") for r in rows}
    if len(codes) != 1 or "" in codes:
        out.append("one reviewer code per sheet is required")
    elif register_codes is not None and not codes <= register_codes:
        out.append(f"reviewer {sorted(codes)} is not in the verified register")
    for r in rows:
        assigned, none = r.get("assigned_type", ""), r.get("none_fits", "")
        if none == "yes":
            if not r.get("none_fits_explanation", "").strip():
                out.append(f"skill {r.get('skill_no')}: 'none fits' needs an explanation")
        elif none != "no" or assigned not in TYPES:
            out.append(
                f"skill {r.get('skill_no')}: assigned_type must be one of {TYPES} or none_fits=yes"
            )
        if r.get("confidence") not in ("1", "2", "3"):
            out.append(f"skill {r.get('skill_no')}: confidence must be 1, 2 or 3")
    return out


def score_taxonomy(
    sheet_a: list[dict[str, str]] | None,
    sheet_b: list[dict[str, str]] | None,
    adjudication: list[dict[str, str]] | None = None,
    register_codes: set[str] | None = None,
) -> dict[str, Any]:
    """Metrics from two complete independent human sheets; otherwise a pending result."""
    pending = {
        "status": "pending_human_assessment",
        "d4": "not frozen",
        "reason": "two complete sheets from independent registered human reviewers are "
        "required; no score is computed from missing data",
    }
    if not sheet_a or not sheet_b:
        return pending
    problems = [f"sheet A: {p}" for p in _sheet_problems(sheet_a, register_codes)]
    problems += [f"sheet B: {p}" for p in _sheet_problems(sheet_b, register_codes)]
    if not problems and sheet_a[0]["reviewer_code"] == sheet_b[0]["reviewer_code"]:
        problems.append("the two sheets must come from two different reviewer codes")
    if problems:
        return {**pending, "status": "invalid_sheets", "problems": problems}
    key = {n: (s, t) for n, s, _, t in TAXONOMY_ITEMS}

    def answers(rows):
        return {
            int(r["skill_no"]): (NONE_FITS if r["none_fits"] == "yes" else r["assigned_type"])
            for r in rows
        }

    a, b = answers(sheet_a), answers(sheet_b)
    numbers = list(range(1, 31))

    def agreement(ns):
        return round(sum(a[n] == b[n] for n in ns) / len(ns), 4) if ns else None

    per_subject = {s: [n for n in numbers if key[n][0] == s] for s in SUBJECTS}
    confusion = collections.Counter((a[n], b[n]) for n in numbers)
    disagreements = [n for n in numbers if a[n] != b[n] or NONE_FITS in (a[n], b[n])]
    adjudicated = {}
    for r in adjudication or []:
        if (
            r.get("final_type")
            and r.get("note", "").strip()
            and r.get("adjudicator_code")
            not in (sheet_a[0]["reviewer_code"], sheet_b[0]["reviewer_code"], "")
        ):
            adjudicated[int(r["skill_no"])] = r["final_type"]
    ambiguous = [
        n
        for n in disagreements
        if n in adjudicated and (adjudicated[n] not in (a[n], b[n]) or adjudicated[n] == NONE_FITS)
    ]
    return {
        "status": "scored",
        "d4": "not frozen: the owner compares these results with thresholds set beforehand (R6)",
        "reviewers": [sheet_a[0]["reviewer_code"], sheet_b[0]["reviewer_code"]],
        "percent_agreement": {
            "overall": agreement(numbers),
            **{s: agreement(ns) for s, ns in per_subject.items()},
        },
        "percent_agreement_by_key_type": {
            t: agreement([n for n in numbers if key[n][1] == t]) for t in TYPES
        },
        "cohen_kappa": {
            "overall": cohen_kappa([a[n] for n in numbers], [b[n] for n in numbers]),
            **{
                s: cohen_kappa([a[n] for n in ns], [b[n] for n in ns])
                for s, ns in per_subject.items()
            },
        },
        "confusion": {f"{x}|{y}": v for (x, y), v in sorted(confusion.items())},
        "none_fits_rate": {
            "overall": round(
                sum((a[n] == NONE_FITS) + (b[n] == NONE_FITS) for n in numbers) / 60, 4
            ),
            **{
                s: round(sum((a[n] == NONE_FITS) + (b[n] == NONE_FITS) for n in ns) / 12, 4)
                for s, ns in per_subject.items()
            },
        },
        "match_with_provisional_key": {
            "reviewer_a": round(sum(a[n] == key[n][1] for n in numbers) / 30, 4),
            "reviewer_b": round(sum(b[n] == key[n][1] for n in numbers) / 30, 4),
            "note": "reported after both finished; not used to grade reviewers",
        },
        "mean_confidence": {
            "reviewer_a": round(sum(int(r["confidence"]) for r in sheet_a) / 30, 3),
            "reviewer_b": round(sum(int(r["confidence"]) for r in sheet_b) / 30, 3),
        },
        "disagreements": disagreements,
        "adjudication_pending": [n for n in disagreements if n not in adjudicated],
        "ambiguous": ambiguous,
    }


# --- D11 evidence pilot -------------------------------------------------------------------


def stratified_sample(
    edges: Sequence[tuple[str, str]], seed: int, per_subject: int = 20, census_limit: int = 100
) -> dict[str, Any]:
    """Choose the edges to review: a census up to `census_limit`, else a stratified sample.

    `edges` are (edge_key, subject_family) pairs of real candidate edges authored by people.
    """
    edges = sorted(set(edges))
    if len(edges) <= census_limit:
        return {"design": "census", "seed": None, "edges": [k for k, _ in edges]}
    rng = random.Random(seed)
    chosen = []
    for subject in SUBJECTS:
        stratum = [k for k, s in edges if s == subject]
        chosen += sorted(rng.sample(stratum, min(per_subject, len(stratum))))
    return {
        "design": "stratified_random",
        "seed": seed,
        "per_subject": per_subject,
        "edges": chosen,
    }


def evidence_template(edge_rows: Sequence[tuple[str, str, str]]) -> str:
    """Blank sheet rows (edge_key, subject, stratum) for each reviewer to fill in."""
    return _csv_text(
        EVIDENCE_SHEET, ((k, s, st, "", "", "", "", "", "", "", "") for k, s, st in edge_rows)
    )


def score_evidence(rows: list[dict[str, str]], register_codes: set[str] | None = None) -> dict:
    """Pilot metrics from completed human sheets (two reviewers per edge)."""
    if not rows:
        return {
            "status": "pending_human_review",
            "d11": "open",
            "reason": "no completed reviewer sheets; no rate is computed from missing data",
        }
    problems = []
    by_edge: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    for r in rows:
        by_edge[r["edge_key"]].append(r)
        if r.get("class") not in EVIDENCE_CLASSES:
            problems.append(f"{r['edge_key']}: class must be a, b or c")
        if r.get("decision") not in ("approved", "rejected", "revision_required"):
            problems.append(f"{r['edge_key']}: invalid decision")
        if register_codes is not None and r.get("reviewer_code") not in register_codes:
            problems.append(f"{r['edge_key']}: reviewer {r.get('reviewer_code')} not registered")
        try:
            float(r.get("minutes", ""))
        except ValueError:
            problems.append(f"{r['edge_key']}: minutes must be a number")
    for key, reviews in by_edge.items():
        if len(reviews) != 2 or reviews[0]["reviewer_code"] == reviews[1]["reviewer_code"]:
            problems.append(f"{key}: exactly two reviews by different reviewers are required")
    if problems:
        return {"status": "invalid_sheets", "d11": "open", "problems": sorted(set(problems))}

    def final_class(reviews):
        a, b = reviews[0]["class"], reviews[1]["class"]
        if a == b:
            return a
        adjudicated = {r.get("adjudicated_class", "") for r in reviews} - {""}
        return adjudicated.pop() if len(adjudicated) == 1 else None

    subjects = {k: v[0]["subject"] for k, v in by_edge.items()}
    finals = {k: final_class(v) for k, v in by_edge.items()}
    real = [k for k, f in finals.items() if f in ("a", "b")]

    def share_b(keys):
        n = len(keys)
        b = sum(finals[k] == "b" for k in keys)
        return {
            "n": n,
            "expert_only": b,
            "share": round(b / n, 4) if n else None,
            "wilson_95": wilson(b, n),
        }

    ab_pairs = [
        (v[0]["class"], v[1]["class"])
        for v in by_edge.values()
        if {v[0]["class"], v[1]["class"]} <= {"a", "b"}
    ]
    minutes = sorted(float(r["minutes"]) for r in rows)
    availability: dict[str, dict[str, int]] = collections.defaultdict(
        lambda: {"with": 0, "without": 0}
    )
    for r in rows:
        availability[r["subject"]]["with" if r.get("evidence_tokens") else "without"] += 1
    return {
        "status": "scored",
        "d11": "the owner compares these results with thresholds set beforehand (R6)",
        "edges": len(by_edge),
        "unresolved_disagreements": sorted(k for k, f in finals.items() if f is None),
        "expert_only_share_among_real": {
            "overall": share_b(real),
            **{s: share_b([k for k in real if subjects[k] == s]) for s in SUBJECTS},
        },
        "agreement_a_vs_b": {
            "pairs": len(ab_pairs),
            "percent": round(sum(x == y for x, y in ab_pairs) / len(ab_pairs), 4)
            if ab_pairs
            else None,
            "kappa": cohen_kappa([x for x, _ in ab_pairs], [y for _, y in ab_pairs]),
        },
        "disagreements": sum(
            1
            for v in by_edge.values()
            if v[0]["class"] != v[1]["class"] or v[0]["decision"] != v[1]["decision"]
        ),
        "decisions": dict(sorted(collections.Counter(r["decision"] for r in rows).items())),
        "minutes_per_review": {
            "mean": round(sum(minutes) / len(minutes), 2),
            "median": minutes[len(minutes) // 2],
        },
        "evidence_availability_by_subject": {k: v for k, v in sorted(availability.items())},
        "limitations": list(LIMITATIONS),
    }
