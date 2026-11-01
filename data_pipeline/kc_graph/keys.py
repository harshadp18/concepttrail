"""`kc_id` and stable-key rules (D1, D2; contract section 5).

Keys are authored, then verified. The loader never generates, normalises in place or repairs
a key: a key that is not already lowercase ASCII in the exact pattern is an error.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from data_pipeline.kc_graph.contract import (
    CLASS_LOOKALIKE_RE,
    CLASS_TOKEN_RE,
    KC_ID_RE,
    SIMILAR_KEY_DISTANCE,
    STABLE_KEY_RE,
    SUBJECT_CODES,
)
from data_pipeline.kc_graph.vocabulary import Vocabulary


@dataclass(frozen=True)
class KeyProblem:
    code: str
    message: str


@dataclass(frozen=True)
class StableKey:
    subject: str
    domain: str
    concept: str
    facet: str | None


def kc_id_subject(kc_id: str) -> str | None:
    """The subject a well-formed `kc_id` encodes, or None if it is malformed."""
    match = KC_ID_RE.match(kc_id)
    return SUBJECT_CODES[match["code"]] if match else None


def parse_key(key: str) -> StableKey | None:
    match = STABLE_KEY_RE.match(key)
    if not match or not key.isascii():
        return None
    return StableKey(match["subject"], match["domain"], match["concept"], match["facet"])


def check_key(key: str, vocab: Vocabulary, subject_id: str | None) -> list[KeyProblem]:
    """Every problem with one key (or alias) against the closed lists and the row's subject."""
    parsed = parse_key(key)
    if parsed is None:
        return [KeyProblem("INVALID_KEY", "not <subject>.<domain>.<concept>[.<facet>]")]
    out: list[KeyProblem] = []
    if parsed.subject not in vocab.domains:
        out.append(KeyProblem("INVALID_KEY", f"unknown subject part {parsed.subject!r}"))
    elif subject_id is not None and parsed.subject != subject_id:
        out.append(KeyProblem("SUBJECT_ID_MISMATCH", "key subject differs from subject_id"))
    elif parsed.domain not in vocab.domains[parsed.subject]:
        out.append(KeyProblem("UNKNOWN_DOMAIN", f"{parsed.domain!r} is not in the closed list"))
    if parsed.facet is not None and parsed.facet not in vocab.facets:
        out.append(KeyProblem("UNKNOWN_FACET", f"{parsed.facet!r} is not in the closed list"))
    for part in (parsed.domain, parsed.concept, parsed.facet or ""):
        if CLASS_TOKEN_RE.search(part):
            out.append(KeyProblem("KEY_HAS_CLASS_TOKEN", f"{part!r} contains a class token"))
        elif CLASS_LOOKALIKE_RE.search(part):
            out.append(KeyProblem("KEY_CLASS_LOOKALIKE", f"{part!r} looks like a class token"))
    return out


def edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def similar_pairs(keys: Iterable[str]) -> list[tuple[str, str]]:
    """Pairs of distinct keys that share a concept slug or differ by a small edit distance."""
    unique = sorted(set(keys))
    parsed = {k: parse_key(k) for k in unique}
    out = []
    for i, a in enumerate(unique):
        for b in unique[i + 1 :]:
            pa, pb = parsed[a], parsed[b]
            same_concept = pa is not None and pb is not None and pa.concept == pb.concept
            if same_concept or edit_distance(a, b) <= SIMILAR_KEY_DISTANCE:
                out.append((a, b))
    return out
