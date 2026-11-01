"""Typed KC and edge rows, parsed from CSV cells with field-level findings (contract 2, 3).

Parsing never repairs a value. A row that has any error is still returned (with the values
that did parse) so later stages can report everything at once; release is blocked by the
errors, not by dropping rows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from data_pipeline.kc_graph import contract as c
from data_pipeline.kc_graph.csv_io import CsvRow
from data_pipeline.kc_graph.findings import Finding, finding
from data_pipeline.kc_graph.keys import check_key, kc_id_subject
from data_pipeline.kc_graph.vocabulary import Vocabulary


@dataclass(frozen=True)
class SourceToken:
    raw: str
    source_id: str
    page: int
    para: int | None
    pin: str


@dataclass(frozen=True)
class KcRow:
    line: int
    cells: dict[str, str] = field(repr=False)
    kc_id: str
    stable_key: str
    subject_id: str
    name: str
    learning_objective: str
    kc_type: str
    difficulty_tier: int | None
    misconceptions: tuple[dict[str, str], ...]
    source_refs: tuple[SourceToken, ...]
    declared_class_levels: tuple[int, ...]
    content_version: str
    origin: str
    origin_ref: str
    review_status: str
    review_record_ids: tuple[str, ...]
    aliases: tuple[str, ...]
    scope: str
    author_id: str

    @property
    def version_number(self) -> int | None:
        match = c.KC_VERSION_RE.match(self.content_version)
        return int(match["n"]) if match else None


@dataclass(frozen=True)
class EdgeRow:
    line: int
    cells: dict[str, str] = field(repr=False)
    prerequisite_kc_id: str
    dependent_kc_id: str
    dependency_basis: str
    reason: str
    strength: int | None
    evidence_refs: tuple[SourceToken, ...]
    origin: str
    origin_ref: str
    review_status: str
    review_record_ids: tuple[str, ...]
    author_id: str

    @property
    def key(self) -> str:
        return f"{self.prerequisite_kc_id}->{self.dependent_kc_id}"


class _Ctx:
    def __init__(self, label: str, row: CsvRow, record: str) -> None:
        self.label, self.row, self.record = label, row, record
        self.findings: list[Finding] = []

    def add(self, code: str, message: str, column: str = "") -> None:
        self.findings.append(
            finding(
                code, message, file=self.label, line=self.row.line, record=self.record, field=column
            )
        )

    def cell(self, column: str) -> str:
        return self.row.cells[column]

    def require(self, column: str) -> str:
        value = self.cell(column)
        if value == "":
            self.add("MISSING_REQUIRED", "required value is empty", column)
        return value

    def items(self, column: str) -> tuple[str, ...]:
        value = self.cell(column)
        if value == "":
            return ()
        parts = value.split(c.LIST_SEPARATOR)
        if any(p == "" or p != p.strip() for p in parts):
            self.add("INVALID_LIST", "empty or untrimmed list item", column)
        if len(set(parts)) != len(parts):
            self.add("INVALID_LIST", "repeated list item", column)
        return tuple(p for p in parts if p)

    def one_of(self, column: str, allowed, code: str, required: bool = True) -> str:
        value = self.require(column) if required else self.cell(column)
        if value and value not in allowed:
            self.add(code, f"{value!r} is not one of {sorted(allowed)}", column)
        return value


def parse_token(raw: str) -> SourceToken | None:
    match = c.SOURCE_TOKEN_RE.match(raw)
    if not match:
        return None
    para = match["para"]
    return SourceToken(
        raw,
        match["source_id"],
        int(match["page"]),
        int(para) if para is not None else None,
        match["pin"],
    )


def _tokens(ctx: _Ctx, column: str, *, locator_required: bool) -> tuple[SourceToken, ...]:
    bad_code = "INVALID_EVIDENCE_REF" if locator_required else "INVALID_SOURCE_REF"
    out = []
    for raw in ctx.items(column):
        if c.REV_TOKEN_RE.match(raw):
            ctx.add(
                "REV_TOKEN_IN_CSV", "rev: tokens are derived by the loader, never written", column
            )
            continue
        token = parse_token(raw)
        if token is None:
            ctx.add(bad_code, f"{raw!r} is not src:<source_id>@<page>[:para<N>]#<sha12>", column)
        elif locator_required and token.para is None:
            ctx.add("MISSING_LOCATOR", f"{raw!r} needs a :para<N> passage locator", column)
        else:
            out.append(token)
    return tuple(out)


def _common(ctx: _Ctx) -> tuple[str, str, str, tuple[str, ...], str]:
    origin = ctx.one_of("origin", c.ORIGINS, "INVALID_ORIGIN")
    origin_ref = ctx.cell("origin_ref")
    if origin == "ai_drafted" and origin_ref == "":
        ctx.add("MISSING_REQUIRED", "origin_ref is required for ai_drafted rows", "origin_ref")
    status = ctx.one_of("review_status", c.REVIEW_STATUSES, "INVALID_STATUS")
    review_ids = ctx.items("review_record_ids")
    for rid in review_ids:
        if not c.EVENT_ID_RE.match(rid):
            ctx.add(
                "INVALID_REVIEW_REF", f"{rid!r} is not an event ID (RR-0001)", "review_record_ids"
            )
    if status in c.DECIDED_STATUSES and not review_ids:
        ctx.add(
            "MISSING_REQUIRED", f"{status} rows must cite their review events", "review_record_ids"
        )
    author = ctx.cell("author_id")
    untouched_ai = origin == "ai_drafted" and author == ""
    if author == "" and not untouched_ai:
        ctx.add(
            "MISSING_REQUIRED",
            "author_id is required unless the row is an untouched ai_drafted draft",
            "author_id",
        )
    elif author and not c.PERSON_CODE_RE.match(author):
        ctx.add("INVALID_PERSON_CODE", f"{author!r} is not a register code (RV-001)", "author_id")
    if untouched_ai and (status != "needs_review" or review_ids):
        ctx.add(
            "AI_FIELD_VIOLATION",
            "an uncurated model draft must be needs_review with no review records",
            "review_status",
        )
    return origin, origin_ref, status, review_ids, author


def _misconceptions(ctx: _Ctx) -> tuple[dict[str, str], ...]:
    raw = ctx.cell("misconceptions")
    if raw == "":
        return ()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        ctx.add("INVALID_MISCONCEPTIONS", f"invalid JSON: {exc.msg}", "misconceptions")
        return ()
    ok = (
        isinstance(items, list)
        and items
        and all(
            isinstance(m, dict)
            and set(m) == {"id", "text"}
            and isinstance(m["id"], str)
            and c.MISCONCEPTION_ID_RE.match(m["id"])
            and isinstance(m["text"], str)
            and m["text"].strip() == m["text"]
            and m["text"]
            for m in items
        )
    )
    if not ok:
        ctx.add(
            "INVALID_MISCONCEPTIONS",
            'must be a non-empty array of {"id": "m<N>", "text"}',
            "misconceptions",
        )
        return ()
    if len({m["id"] for m in items}) != len(items):
        ctx.add("INVALID_MISCONCEPTIONS", "misconception IDs repeat", "misconceptions")
    if len({m["text"].casefold() for m in items}) != len(items):
        ctx.add("INVALID_MISCONCEPTIONS", "misconception texts repeat", "misconceptions")
    return tuple(items)


def parse_kc(row: CsvRow, vocab: Vocabulary, label: str = "kc_csv") -> tuple[KcRow, list[Finding]]:
    ctx = _Ctx(label, row, row.cells["kc_id"])
    kc_id = ctx.require("kc_id")
    subject = ctx.one_of("subject_id", c.SUBJECTS, "INVALID_SUBJECT")
    if kc_id:
        coded = kc_id_subject(kc_id)
        if coded is None:
            ctx.add("INVALID_KC_ID", "not KC-<ENG|HIN|MAT|SCI|SOC>-<5 digits>", "kc_id")
        elif subject in c.SUBJECTS and coded != subject:
            ctx.add("SUBJECT_ID_MISMATCH", "kc_id subject code differs from subject_id", "kc_id")
    key = ctx.require("stable_key")
    known_subject = subject if subject in c.SUBJECTS else None
    if key:
        for p in check_key(key, vocab, known_subject):
            ctx.add(p.code, p.message, "stable_key")
    aliases = ctx.items("aliases")
    for alias in aliases:
        for p in check_key(alias, vocab, known_subject):
            ctx.add(p.code, f"alias {alias!r}: {p.message}", "aliases")
    name = ctx.require("name")
    objective = ctx.require("learning_objective")
    if objective and (
        len(objective.split()) > c.LONG_OBJECTIVE_WORDS
        or sum(objective.count(x) for x in (". ", "? ", "! ", "। ")) > 0
    ):
        ctx.add(
            "LONG_OBJECTIVE",
            "the objective should be one measurable sentence",
            "learning_objective",
        )
    kc_type = ctx.one_of("kc_type", vocab.kc_types, "INVALID_KC_TYPE")
    tier = ctx.one_of("difficulty_tier", c.DIFFICULTY_TIERS, "INVALID_DIFFICULTY", required=False)
    refs = _tokens(ctx, "source_refs", locator_required=False)
    if ctx.cell("source_refs") == "":
        ctx.add("MISSING_REQUIRED", "at least one source reference is required", "source_refs")
    classes = ctx.items("declared_class_levels")
    for value in classes:
        if value not in c.CLASS_LEVELS:
            ctx.add("INVALID_CLASS_LEVEL", f"{value!r} is not one of 6-10", "declared_class_levels")
    version = ctx.require("content_version")
    if version and not c.KC_VERSION_RE.match(version):
        ctx.add("INVALID_VERSION", "content_version must be kc-v<n>", "content_version")
    scope = ctx.one_of("scope", c.SCOPES, "INVALID_SCOPE")
    if scope == "foundation" and classes:
        ctx.add(
            "FOUNDATION_HAS_CLASSES", "a foundation KC declares no class", "declared_class_levels"
        )
    if scope == "target" and not classes:
        ctx.add(
            "KC_WITHOUT_CLASS_DECLARATION",
            "not counted in released class coverage",
            "declared_class_levels",
        )
    origin, origin_ref, status, review_ids, author = _common(ctx)
    kc = KcRow(
        line=row.line,
        cells=row.cells,
        kc_id=kc_id,
        stable_key=key,
        subject_id=subject,
        name=name,
        learning_objective=objective,
        kc_type=kc_type,
        difficulty_tier=int(tier) if tier in c.DIFFICULTY_TIERS else None,
        misconceptions=_misconceptions(ctx),
        source_refs=refs,
        declared_class_levels=tuple(sorted(int(v) for v in classes if v in c.CLASS_LEVELS)),
        content_version=version,
        origin=origin,
        origin_ref=origin_ref,
        review_status=status,
        review_record_ids=review_ids,
        aliases=aliases,
        scope=scope,
        author_id=author,
    )
    return kc, ctx.findings


def parse_edge(
    row: CsvRow, vocab: Vocabulary, label: str = "edge_csv"
) -> tuple[EdgeRow, list[Finding]]:
    record = f"{row.cells['prerequisite_kc_id']}->{row.cells['dependent_kc_id']}"
    ctx = _Ctx(label, row, record)
    ends = []
    for column in ("prerequisite_kc_id", "dependent_kc_id"):
        value = ctx.require(column)
        if value and kc_id_subject(value) is None:
            ctx.add("INVALID_KC_ID", "not KC-<ENG|HIN|MAT|SCI|SOC>-<5 digits>", column)
        ends.append(value)
    basis = ctx.require("dependency_basis")
    if basis and (basis in c.FORBIDDEN_BASES or basis not in vocab.dependency_bases):
        ctx.add(
            "FORBIDDEN_BASIS",
            f"{basis!r} is not an allowed dependency basis (chapter_order is prohibited)",
            "dependency_basis",
        )
    reason = ctx.require("reason")
    if reason and c.SEQUENCE_WORDS_RE.search(reason):
        ctx.add("REASON_MENTIONS_ORDER", "the reason seems to lean on sequence", "reason")
    strength = ctx.one_of("strength", c.STRENGTHS, "INVALID_STRENGTH", required=False)
    evidence = _tokens(ctx, "evidence_refs", locator_required=True)
    origin, origin_ref, status, review_ids, author = _common(ctx)
    if status == "approved" and basis.startswith("uses_") and not ctx.cell("evidence_refs"):
        ctx.add(
            "EDGE_WITHOUT_EVIDENCE",
            "a uses_* edge needs located source evidence to be approved",
            "evidence_refs",
        )
    edge = EdgeRow(
        line=row.line,
        cells=row.cells,
        prerequisite_kc_id=ends[0],
        dependent_kc_id=ends[1],
        dependency_basis=basis,
        reason=reason,
        strength=int(strength) if strength in c.STRENGTHS else None,
        evidence_refs=evidence,
        origin=origin,
        origin_ref=origin_ref,
        review_status=status,
        review_record_ids=review_ids,
        author_id=author,
    )
    return edge, ctx.findings
