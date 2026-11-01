"""Closed vocabularies (D2, D4, D9): domains, facets, KC types and dependency bases.

The owner maintains `data/curated/kc_graph/kc_vocabularies.json` (R7). Until it exists the loader
uses `PROVISIONAL_VOCABULARY`, the unconfirmed proposal transcribed from contract section 4,
and reports `VOCABULARY_PROVISIONAL`. A provisional vocabulary is enough for parsing, dry runs
and synthetic tests; **release refuses it** (`VOCABULARY_NOT_CONFIRMED`). Nothing in the code
adds an entry: an unknown value is an error, and a new value enters only by an owner edit that
bumps the file's version.

File shape::

    {"version": "v1", "status": "owner_confirmed" | "provisional",
     "domains": {"<subject>": ["<slug>", ...], ...}, "facets": [...],
     "kc_types": [...], "dependency_bases": [...], "change_log": [...]}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.audit_chain import digest
from data_pipeline.kc_graph.contract import FORBIDDEN_BASES, SLUG, SUBJECTS
from data_pipeline.kc_graph.findings import Finding, finding

STATUSES = ("owner_confirmed", "provisional")
_SLUG_RE = re.compile(rf"^{SLUG}$")

PROVISIONAL_VOCABULARY: dict[str, Any] = {
    "version": "provisional-contract-rev3",
    "status": "provisional",
    "domains": {
        "mathematics": [
            "number-sense",
            "integers",
            "fractions",
            "decimals",
            "ratio-proportion",
            "percentages",
            "exponents-powers",
            "algebra",
            "equations",
            "polynomials",
            "sequences-series",
            "geometry",
            "mensuration",
            "coordinate-geometry",
            "trigonometry",
            "data-handling",
            "probability",
        ],
        "science": [
            "matter",
            "atoms-molecules",
            "chemical-reactions",
            "acids-bases-salts",
            "metals-nonmetals",
            "carbon-compounds",
            "periodic-classification",
            "motion-force",
            "work-energy",
            "heat",
            "light",
            "sound",
            "electricity",
            "magnetism",
            "cells-tissues",
            "nutrition",
            "respiration",
            "reproduction",
            "heredity-evolution",
            "human-body",
            "ecosystems",
            "natural-resources",
        ],
        "english": [
            "reading",
            "writing",
            "grammar",
            "vocabulary",
            "literature",
            "speaking-listening",
        ],
        "hindi": [
            "reading",
            "writing",
            "grammar",
            "vocabulary",
            "literature",
            "speaking-listening",
        ],
        "social_science": ["history", "geography", "civics", "economics"],
    },
    "facets": [
        "recall",
        "recognise",
        "define",
        "classify",
        "compute",
        "construct",
        "apply",
        "explain",
        "compare",
        "interpret",
        "evaluate",
    ],
    "kc_types": ["concept", "procedure", "fact", "vocabulary", "application", "interpretation"],
    "dependency_bases": [
        "uses_concept",
        "uses_procedure",
        "uses_vocabulary",
        "uses_representation",
        "expert_judgement",
    ],
    "change_log": ["transcribed from PHASE_5_CSV_CONTRACT.md section 4; not owner-confirmed"],
}


@dataclass(frozen=True)
class Vocabulary:
    version: str
    status: str
    sha256: str
    domains: dict[str, frozenset[str]]
    facets: frozenset[str]
    kc_types: frozenset[str]
    dependency_bases: frozenset[str]
    source: str  # "file" or "built-in provisional"
    synthetic: bool = False  # test vocabularies only; a real run refuses them

    @property
    def confirmed(self) -> bool:
        return self.status == "owner_confirmed" and self.source == "file"

    def manifest(self) -> dict[str, str]:
        return {
            "version": self.version,
            "status": self.status,
            "sha256": self.sha256,
            "source": self.source,
            "synthetic": self.synthetic,
        }


def _problems(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["not a JSON object"]
    out = []
    if not isinstance(data.get("version"), str) or not data["version"]:
        out.append("version missing")
    if data.get("status") not in STATUSES:
        out.append(f"status must be one of {STATUSES}")
    domains = data.get("domains")
    if not isinstance(domains, dict) or set(domains) != set(SUBJECTS):
        out.append(f"domains must have exactly the subjects {SUBJECTS}")
    else:
        for subject, values in domains.items():
            if not isinstance(values, list) or not values:
                out.append(f"domains.{subject} must be a non-empty list")
    lists = [
        ("facets", data.get("facets")),
        ("kc_types", data.get("kc_types")),
        ("dependency_bases", data.get("dependency_bases")),
    ]
    if isinstance(domains, dict):
        lists += [(f"domains.{s}", v) for s, v in domains.items()]
    for name, values in lists:
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            out.append(f"{name} must be a list of strings")
            continue
        if len(set(values)) != len(values):
            out.append(f"{name} has duplicates")
        if name != "kc_types" and name != "dependency_bases":
            if bad := [v for v in values if not _SLUG_RE.match(v)]:
                out.append(f"{name} has values that are not slugs: {bad}")
    if isinstance(data.get("dependency_bases"), list):
        if bad := sorted(set(data["dependency_bases"]) & set(FORBIDDEN_BASES)):
            out.append(f"dependency_bases may never include {bad}")
    return out


def from_mapping(data: dict[str, Any], source: str) -> Vocabulary:
    return Vocabulary(
        version=data["version"],
        status=data["status"],
        sha256=digest(data),
        domains={s: frozenset(v) for s, v in data["domains"].items()},
        facets=frozenset(data["facets"]),
        kc_types=frozenset(data["kc_types"]),
        dependency_bases=frozenset(data["dependency_bases"]),
        source=source,
        synthetic=data.get("synthetic") is True,
    )


def provisional() -> Vocabulary:
    return from_mapping(PROVISIONAL_VOCABULARY, "built-in provisional")


def load(path: Path | None) -> tuple[Vocabulary | None, list[Finding]]:
    """The vocabulary to validate against, and any findings about it."""
    if path is None or not path.exists():
        return provisional(), [
            finding(
                "VOCABULARY_PROVISIONAL",
                "no owner vocabulary file; using the unconfirmed proposal from the contract",
                file="vocabulary",
            )
        ]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, [finding("VOCABULARY_INVALID", f"unreadable: {exc}", file="vocabulary")]
    if problems := _problems(data):
        return None, [finding("VOCABULARY_INVALID", p, file="vocabulary") for p in problems]
    vocab = from_mapping(data, "file")
    notes = []
    if not vocab.confirmed:
        notes.append(
            finding(
                "VOCABULARY_PROVISIONAL",
                "the vocabulary file is marked provisional",
                file="vocabulary",
            )
        )
    return vocab, notes
