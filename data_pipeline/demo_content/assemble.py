"""Deterministic assembly and validation of generated batches (no model involved).

KCs: vocabulary and stable-key rules of the Phase 5 contract (provisional vocabulary), page
indices restricted to the pages the model was shown, deduplicated by stable key, IDs allocated
once in a persisted registry (`KC-<SUBJ>-5xxxx`, the demo range). Edges: both ends exist, no
self-edge or duplicate, cross-class edges only from an earlier or equal class, and the graph is
kept acyclic (stronger edges are kept first; an edge that would close a cycle is dropped and
reported); the result is re-checked by `app.services.prerequisite_graph.validate_graph`.
Questions: converted to `QuestionDraft` and checked by the question-bank validator plus
demo-specific checks (page citation, SymPy for mathematics, no copied source text).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import networkx as nx
from pydantic import ValidationError

from app.schemas.knowledge import EdgeRecord, KcRecord
from app.services.prerequisite_graph import validate_graph
from app.services.question_bank import OptionDraft, QuestionDraft, SourceRef, validate_structure
from data_pipeline.demo_content.generate import WORK, load_artifact, usable_pages
from data_pipeline.kc_graph.contract import CLASS_TOKEN_RE, SUBJECT_CODES
from data_pipeline.kc_graph.keys import check_key
from data_pipeline.kc_graph.vocabulary import provisional

REGISTRY = WORK / "kc_registry.json"
CODE = {v: k for k, v in SUBJECT_CODES.items()}
DEMO_BASE = 50000
_SLUG = re.compile(r"[^a-z0-9]+")
_WORDS = re.compile(r"\w+", re.UNICODE)


def slugify(text: str) -> str:
    return _SLUG.sub("-", text.casefold()).strip("-")[:60]


def humanize(name: str) -> str:
    """A display name from a model-written name; slug-style names ('add-unlike-fractions')
    become sentence case ('Add unlike fractions'). Names with spaces are left as written."""
    text = name.strip()
    if " " not in text and ("-" in text or "_" in text):
        text = text.replace("-", " ").replace("_", " ").strip()
        return text[:1].upper() + text[1:]
    return text


def kc_problems(kc: dict[str, Any], subject: str, shown: set[int]) -> tuple[dict | None, list[str]]:
    vocab = provisional()
    problems = []
    slug = slugify(kc["concept_slug"])
    if not slug or not slug.isascii() or CLASS_TOKEN_RE.search(slug):
        problems.append("bad_concept_slug")
    facet = kc.get("facet") or None
    if facet is not None and facet not in vocab.facets:
        facet = None  # an unknown facet is dropped (it is optional); a domain is not
    if kc["domain"] not in vocab.domains[subject]:
        problems.append("unknown_domain")
    if kc["kc_type"] not in vocab.kc_types:
        problems.append("unknown_kc_type")
    pages = sorted({p for p in kc["page_indices"] if p in shown})
    if not pages:
        problems.append("no_valid_page_reference")
    key = f"{subject}.{kc['domain']}.{slug}" + (f".{facet}" if facet else "")
    if not problems:
        errors = [p for p in check_key(key, vocab, subject) if p.code != "KEY_CLASS_LOOKALIKE"]
        problems += [p.code.lower() for p in errors]
    if problems:
        return None, problems
    name = humanize(kc["name"])
    misconceptions = [m.strip() for m in kc.get("misconceptions", []) if m and m.strip()]
    return {
        "stable_key": key,
        "name": name,
        "learning_objective": kc["learning_objective"].strip(),
        "kc_type": kc["kc_type"],
        "difficulty_tier": kc["difficulty_tier"],
        "misconceptions": [
            {"id": f"m{i}", "text": t} for i, t in enumerate(dict.fromkeys(misconceptions), start=1)
        ],
        "page_indices": pages,
    }, []


def chapter_kcs(chapter: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """Validated, deduplicated KCs of one chapter (with local IDs), and the rejects."""
    source = chapter["source_id"]
    kept: dict[str, dict] = {}
    rejected = []
    for path in sorted((WORK / source).glob("kcs_w*.json")):
        if path.name.endswith(".failed.json"):
            continue
        batch = json.loads(path.read_text(encoding="utf-8"))
        shown = set(batch["page_indices"])
        for raw in batch["output"]["kcs"]:
            kc, problems = kc_problems(raw, chapter["subject_id"], shown)
            if kc is None:
                rejected.append({"name": raw.get("name"), "problems": problems})
                continue
            if kc["stable_key"] in kept:
                merged = kept[kc["stable_key"]]
                merged["page_indices"] = sorted(
                    set(merged["page_indices"]) | set(kc["page_indices"])
                )
                continue
            kc.update(
                model_id=batch["model_id"], batch=batch["batch"], request_id=batch["request_id"]
            )
            kept[kc["stable_key"]] = kc
    ordered = sorted(kept.values(), key=lambda k: (k["page_indices"][0], k["stable_key"]))
    for n, kc in enumerate(ordered, start=1):
        kc.update(
            local_id=f"{source}#K{n}",
            source_id=source,
            class_level=chapter["class_level"],
            subject_id=chapter["subject_id"],
            inventory_id=chapter["inventory_id"],
            chapter=chapter["chapter"],
        )
    return ordered, rejected


def allocate_ids(kcs: list[dict]) -> dict[str, str]:
    """stable_key -> kc_id, persisted; an allocated ID is never reused or changed."""
    registry: dict[str, str] = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    used: dict[str, int] = defaultdict(lambda: DEMO_BASE)
    for kc_id in registry.values():
        prefix, number = kc_id.rsplit("-", 1)
        used[prefix] = max(used[prefix], int(number))
    for kc in sorted(kcs, key=lambda k: k["stable_key"]):
        if kc["stable_key"] in registry:
            continue
        prefix = f"KC-{CODE[kc['subject_id']]}"
        used[prefix] += 1
        registry[kc["stable_key"]] = f"{prefix}-{used[prefix]:05d}"
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(dict(sorted(registry.items())), indent=2))
    return registry


def accept_edges(
    proposals: list[tuple[dict, str]], by_local: dict[str, dict], existing: list[tuple[str, str]]
) -> tuple[list[dict], list[dict]]:
    """Keep valid edges, strongest first, never closing a cycle. `proposals` = (edge, batch)."""
    graph = nx.DiGraph()
    graph.add_edges_from(existing)
    kept, rejected = [], []
    ordered = sorted(
        proposals, key=lambda p: (-p[0]["strength"], p[0]["prerequisite"], p[0]["dependent"])
    )
    for edge, batch in ordered:
        pre, dep = by_local.get(edge["prerequisite"]), by_local.get(edge["dependent"])
        reason = None
        if pre is None or dep is None:
            reason = "unknown_kc"
        elif pre["kc_id"] == dep["kc_id"]:
            reason = "self_edge"
        elif graph.has_edge(pre["kc_id"], dep["kc_id"]):
            reason = "duplicate"
        elif pre["class_level"] > dep["class_level"]:
            reason = "prerequisite_in_later_class"
        elif (
            dep["kc_id"] in graph
            and pre["kc_id"] in graph
            and nx.has_path(graph, dep["kc_id"], pre["kc_id"])
        ):
            reason = "would_create_cycle"
        if reason:
            rejected.append({**edge, "reason_rejected": reason})
            continue
        graph.add_edge(pre["kc_id"], dep["kc_id"])
        page = edge.get("evidence_page")
        kept.append(
            {
                "prerequisite_kc_id": pre["kc_id"],
                "dependent_kc_id": dep["kc_id"],
                "basis": edge["basis"],
                "reason": edge["reason"].strip(),
                "strength": edge["strength"],
                "batch": batch,
                "evidence_page": page
                if page in pre["page_indices"] + dep["page_indices"]
                else None,
                "evidence_source_id": dep["source_id"],
            }
        )
    return kept, rejected


def check_graph(kcs: list[dict], edges: list[dict]) -> list[str]:
    records = [
        KcRecord(
            kc_id=k["kc_id"],
            stable_key=k["stable_key"],
            subject_id=k["subject_id"],
            name=k["name"],
            review_status="approved",
            class_levels=(k["class_level"],),
        )
        for k in kcs
    ]
    edge_records = [
        EdgeRecord(
            prerequisite_kc_id=e["prerequisite_kc_id"],
            dependent_kc_id=e["dependent_kc_id"],
            reason=e["reason"],
            strength=e["strength"],
            evidence_refs=("demo",),
            review_status="approved",
        )
        for e in edges
    ]
    return validate_graph(records, edge_records).codes("error")


def _shingles(text: str, n: int = 10) -> set[tuple[str, ...]]:
    words = [w.casefold() for w in _WORDS.findall(text)]
    return {tuple(words[i : i + n]) for i in range(max(0, len(words) - n + 1))}


def _number(text: str) -> Decimal | None:
    try:
        return Decimal(text.strip().replace(",", ""))
    except ArithmeticError:
        return None
    except Exception:  # noqa: BLE001  (Decimal raises InvalidOperation for non-numbers)
        return None


_UNITS = re.compile(r"\s*[A-Za-z][A-Za-z ²³]*$")
_ARITH = re.compile(r"^[0-9\s.+\-*/()]+$")


def option_value(text: str) -> Decimal | None:
    """A numeric option's value (plain numbers, fractions, simple LaTeX), else None."""
    t = text.replace("$", "").replace("\\times", "*").replace("×", "*").replace("^", "**")
    t = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", r"(\1)/(\2)", t)
    t = _UNITS.sub("", t.replace(",", "")).strip()
    if not t or not _ARITH.match(t.replace("**", "*")):
        return None
    return _sympy_value(t)


def numeric_option_problems(
    options: list[OptionDraft], expression: str | None, kind: str
) -> list[str]:
    """When options are numbers, the key must be verified: exactly the correct option(s) equal
    the value of `answer_expression` (single choice: exactly one option equals it)."""
    values = [option_value(o.option_text) for o in options]
    if sum(v is not None for v in values) < 2:
        return []  # conceptual options; not numerically verifiable
    if kind == "multiple_select":
        return []
    if not expression:
        return ["maths_key_not_verifiable"]
    target = _sympy_value(expression)
    if target is None:
        return ["maths_expression_invalid"]
    equal = [
        o
        for o, v in zip(options, values, strict=True)
        if v is not None and abs(v - target) <= Decimal("1e-6")
    ]
    if len(equal) != 1:
        return ["maths_no_unique_matching_option"]
    if not equal[0].is_correct:
        return ["maths_key_disagrees_with_expression"]
    return []


def _sympy_value(expression: str) -> Decimal | None:
    import sympy

    try:
        return Decimal(str(float(sympy.N(sympy.sympify(expression, evaluate=True), 30))))
    except (sympy.SympifyError, TypeError, ValueError, ArithmeticError, SyntaxError):
        return None


def question_drafts(
    chapter: dict[str, Any], kc: dict[str, Any], batch: dict[str, Any], sha256: str
) -> tuple[list[QuestionDraft], list[dict]]:
    artifact = load_artifact(chapter["artifact"])
    page_text = {p["page_index"]: p["text"] for p in usable_pages(artifact)}
    source_shingles = (
        set().union(*(_shingles(t) for t in page_text.values())) if page_text else set()
    )
    maths = chapter["subject_id"] == "mathematics"
    drafts, rejected = [], []
    for raw in batch["output"]["questions"]:
        problems = []
        kind = raw["item_type"]
        options = [
            OptionDraft(
                option_key=o["key"].strip().upper(),
                option_text=o["text"].strip(),
                is_correct=o["is_correct"],
                explanation=o.get("explanation") or None,
            )
            for o in raw["options"]
        ]
        expected: dict[str, Any] | None = None
        rubric = None
        if kind == "true_false":
            correct = [o.option_text.casefold() for o in options if o.is_correct]
            expected = {"value": correct == ["true"]} if len(correct) == 1 else None
            if expected is None:
                problems.append("true_false_key_invalid")
        elif kind == "numeric":
            options = []
            if raw.get("numeric_answer") is None:
                problems.append("numeric_answer_missing")
            else:
                tolerance = raw.get("tolerance")
                expected = {
                    "value": raw["numeric_answer"],
                    "abs_tolerance": tolerance
                    if tolerance is not None and tolerance >= 0
                    else 0.01,
                }
                if raw.get("answer_expression"):
                    expected["expression"] = raw["answer_expression"]
                elif maths:
                    problems.append("maths_answer_not_verifiable")
        elif kind == "short_answer":
            options = []
            rubric = {"criteria": raw.get("rubric_criteria") or []}
        if kind in ("single_choice", "multiple_select"):
            problems += numeric_option_problems(options, raw.get("answer_expression"), kind)
        if raw["page_index"] not in page_text:
            problems.append("page_reference_invalid")
        if _shingles(raw["stem"]) & source_shingles:
            problems.append("copied_from_source")
        if problems:
            rejected.append({"stem": raw["stem"][:80], "problems": problems})
            continue
        try:
            draft = _build_draft(raw, kind, options, expected, rubric, chapter, kc, sha256, batch)
        except ValidationError as exc:
            rejected.append(
                {
                    "stem": raw["stem"][:80],
                    "problems": ["schema_" + str(e["loc"][0]) for e in exc.errors()],
                }
            )
            continue
        validation = validate_structure(draft)
        if validation.ok:
            drafts.append(draft)
        else:
            rejected.append(
                {"stem": raw["stem"][:80], "problems": [c for c, _ in validation.errors]}
            )
    return drafts, rejected


def _build_draft(raw, kind, options, expected, rubric, chapter, kc, sha256, batch):
    return QuestionDraft(
        item_type=kind,
        stem=raw["stem"].strip(),
        options=options,
        expected_answer=expected,
        rubric=rubric,
        difficulty=raw["difficulty"],
        language="hi" if chapter["subject_id"] == "hindi" else "en",
        class_level=chapter["class_level"],
        subject_id=chapter["subject_id"],
        kc_ids=[kc["kc_id"]],
        curriculum_item_id=chapter["inventory_id"],
        source_refs=[
            SourceRef(
                source_id=chapter["source_id"], sha256=sha256, pdf_page_index=raw["page_index"]
            )
        ],
        misconception_map={"targets": raw["misconception"]} if raw.get("misconception") else None,
        explanation=raw["explanation"].strip()
        + ("\n\nSteps: " + " | ".join(raw["solution_steps"]) if raw.get("solution_steps") else ""),
        origin="ai_drafted",
        origin_ref=f"{batch['model_id']}|{batch['prompt_version']}|{batch['request_id']}",
    )


RELEVANCE_FLOOR = 0.35


def relevance_filter(
    kc_text: dict[str, str], questions: list[tuple[str, QuestionDraft]], embed: Any
) -> tuple[list[QuestionDraft], list[dict]]:
    """Drop questions whose stem is semantically far from their KC (local embeddings).

    `questions` = (kc_id, draft). `embed(texts) -> vectors`. Cosine below `RELEVANCE_FLOOR`
    (provisional) means the question drifted off its knowledge component.
    """
    from app.services.embeddings import cosine

    if not questions:
        return [], []
    kc_ids = sorted(kc_text)
    kc_vectors = dict(zip(kc_ids, embed([kc_text[k] for k in kc_ids]), strict=True))
    stem_vectors = embed([d.stem for _, d in questions])
    kept, dropped = [], []
    for (kc_id, draft), vector in zip(questions, stem_vectors, strict=True):
        score = cosine(vector, kc_vectors[kc_id])
        if score < RELEVANCE_FLOOR:
            dropped.append(
                {
                    "kc_id": kc_id,
                    "stem": draft.stem[:80],
                    "problems": [f"off_kc_relevance_{score:.2f}"],
                }
            )
        else:
            kept.append(draft)
    return kept, dropped


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


_PASSAGE_DEPENDENT = re.compile(
    r"according to the (text|passage|story|poem|chapter|lesson|author)|in the (passage|story|"
    r"poem|text) above|as (described|mentioned|stated) in the (text|passage|story|chapter)|"
    r"पाठ के अनुसार|गद्यांश के अनुसार|कहानी के अनुसार",
    re.IGNORECASE,
)
_KEYS = "ABCD"


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def near_duplicate(
    stem: str, others: list[str], threshold: float = 0.6, containment: float = 0.6
) -> bool:
    """Same normalised words, word-trigram Jaccard above `threshold`, or one stem's trigrams
    largely contained in the other's (catches light paraphrases such as 'equals'/'is equal to').
    """
    words = _words(stem)
    grams = {tuple(words[i : i + 3]) for i in range(max(1, len(words) - 2))}
    for other in others:
        ow = _words(other)
        if ow == words:
            return True
        og = {tuple(ow[i : i + 3]) for i in range(max(1, len(ow) - 2))}
        if grams and og:
            shared = len(grams & og)
            smaller = min(len(grams), len(og))
            if shared / len(grams | og) > threshold or (
                smaller >= 6 and shared / smaller > containment
            ):
                return True
    return False


def rekey_single_choice(stem: str, options: list[dict]) -> list[dict]:
    """Place the correct option at a stem-determined position (uniform over A-D).

    Drafted keys cluster on one letter; the delivered order is shuffled per learner anyway, but
    the stored key should not carry a pattern either. Distractors keep their relative order.
    """
    correct = [o for o in options if o["is_correct"]]
    wrong = [o for o in options if not o["is_correct"]]
    if len(correct) != 1 or len(options) != 4:
        return options
    slot = int(hashlib.sha256(stem.encode()).hexdigest(), 16) % 4
    ordered = wrong[:slot] + correct + wrong[slot:]
    return [{**o, "key": _KEYS[i]} for i, o in enumerate(ordered)]


def topup_filters(batch: dict, existing_stems: list[str]) -> tuple[dict, list[dict]]:
    """v3 checks before the shared validation: self-contained, new, complete, re-keyed."""
    kept, rejected, seen = [], [], list(existing_stems)
    for raw in batch["output"]["questions"]:
        problems = []
        if _PASSAGE_DEPENDENT.search(raw["stem"]):
            problems.append("passage_dependent_stem")
        if near_duplicate(raw["stem"], seen):
            problems.append("near_duplicate")
        if any(len((o.get("explanation") or "").strip()) < 5 for o in raw["options"]):
            problems.append("option_explanation_missing")
        if raw["item_type"] == "single_choice" and len(raw["options"]) != 4:
            problems.append("single_choice_needs_4_options")
        if raw["item_type"] == "true_false":
            texts = sorted(o["text"].strip().casefold() for o in raw["options"])
            if texts != ["false", "true"]:
                problems.append("true_false_options_invalid")
        if problems:
            rejected.append({"stem": raw["stem"][:80], "problems": problems})
            continue
        if raw["item_type"] == "single_choice":
            raw = {**raw, "options": rekey_single_choice(raw["stem"], raw["options"])}
        else:
            order = {"true": "A", "false": "B"}
            raw = {
                **raw,
                "options": sorted(
                    (
                        {
                            **o,
                            "key": order[o["text"].strip().casefold()],
                            "text": o["text"].strip().title(),
                        }
                        for o in raw["options"]
                    ),
                    key=lambda o: o["key"],
                ),
            }
        seen.append(raw["stem"])
        kept.append(raw)
    return {**batch, "output": {"questions": kept}}, rejected
