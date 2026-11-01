"""Person register and the owner's write-once register verification (D12, guidelines 2).

`overrides/kc_review/people.json` (private, owner-created; R4)::

    {"version": "...", "people": [{"code": "RV-001", "roles": ["reviewer"],
      "subjects": ["mathematics"], "qualification_basis": "<private note>", "active": true}]}

No names or contact details. The loader can check that a code exists, is active, has the role
and covers the subjects, and is not the author. It **cannot** prove that two codes are two real
people or that a person is qualified: the owner states that privately in a write-once
`people_verification_<date>.json`, bound by SHA-256 to the register and to each entry. If an
entry changes after verification, events by that code fail with `REGISTER_NOT_VERIFIED`.

A register marked `"synthetic": true` exists only for tests and the synthetic dry run; a real
run refuses it (`SYNTHETIC_DATA`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.audit_chain import digest
from data_pipeline.kc_graph.contract import PERSON_CODE_RE, REVIEWER_ROLES, ROLES, SUBJECTS
from data_pipeline.kc_graph.findings import Finding, finding
from data_pipeline.teacher_validation import write_once

VERIFICATION_RE = re.compile(r"^people_verification_(\d{4}-\d{2}-\d{2})\.json$")
VERIFICATION_TYPE = "reviewer_register_verification"


@dataclass(frozen=True)
class Person:
    code: str
    roles: frozenset[str]
    subjects: frozenset[str]
    active: bool
    entry_sha256: str


@dataclass(frozen=True)
class Register:
    people: dict[str, Person]
    sha256: str
    synthetic: bool
    verified_codes: frozenset[str]  # codes whose current entry matches the owner's verification
    verification: str | None  # verification file name in force, if any

    def reviewer_problem(self, code: str, subjects: set[str]) -> tuple[str, str] | None:
        """(code, message) if `code` may not review a record in `subjects`; None if it may."""
        person = self.people.get(code)
        if person is None:
            return "REVIEWER_UNKNOWN", f"{code} is not in the register"
        if code not in self.verified_codes:
            return "REGISTER_NOT_VERIFIED", f"{code} is not covered by the owner's verification"
        if not person.active:
            return "REVIEWER_NOT_QUALIFIED", f"{code} is not active"
        if not person.roles & set(REVIEWER_ROLES):
            return "REVIEWER_NOT_QUALIFIED", f"{code} has no reviewer role"
        if not subjects <= person.subjects:
            return "REVIEWER_NOT_QUALIFIED", f"{code} is not qualified for {sorted(subjects)}"
        return None


def entry_digest(entry: dict[str, Any]) -> str:
    return digest(entry)


def _validate(data: Any) -> list[str]:
    if not isinstance(data, dict) or not isinstance(data.get("people"), list):
        return ["the register must be an object with a people list"]
    out, codes = [], []
    for i, p in enumerate(data["people"]):
        if not isinstance(p, dict):
            out.append(f"entry {i} is not an object")
            continue
        code = p.get("code", "")
        codes.append(code)
        if not isinstance(code, str) or not PERSON_CODE_RE.match(code):
            out.append(f"entry {i}: code {code!r} is not RV-<digits>")
        if not isinstance(p.get("roles"), list) or not set(p["roles"]) <= set(ROLES):
            out.append(f"{code}: roles must be a subset of {ROLES}")
        if not isinstance(p.get("subjects"), list) or not set(p["subjects"]) <= set(SUBJECTS):
            out.append(f"{code}: subjects must be a subset of {SUBJECTS}")
        if not isinstance(p.get("active"), bool):
            out.append(f"{code}: active must be true or false")
        if set(p) & {"name", "email", "phone", "contact"}:
            out.append(f"{code}: names and contact details are not allowed in the register")
    if dupes := sorted({c for c in codes if codes.count(c) > 1}):
        out.append(f"duplicate codes {dupes}")
    return out


def latest_verification(directory: Path) -> Path | None:
    found = sorted(
        p for p in directory.glob("people_verification_*.json") if VERIFICATION_RE.match(p.name)
    )
    return found[-1] if found else None


def load(path: Path, *, allow_synthetic: bool) -> tuple[Register | None, list[Finding]]:
    label = "register"
    if not path.exists():
        return None, [
            finding("REGISTER_MISSING", "no person register (owner choice R4)", file=label)
        ]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, [finding("REGISTER_INVALID", f"unreadable: {exc}", file=label)]
    if problems := _validate(data):
        return None, [finding("REGISTER_INVALID", p, file=label) for p in problems]
    findings: list[Finding] = []
    synthetic = data.get("synthetic") is True
    if synthetic and not allow_synthetic:
        findings.append(
            finding(
                "SYNTHETIC_DATA", "a synthetic register cannot be used for a real run", file=label
            )
        )
    people = {
        p["code"]: Person(
            p["code"], frozenset(p["roles"]), frozenset(p["subjects"]), p["active"], entry_digest(p)
        )
        for p in data["people"]
    }
    register_sha = digest(data)
    verified: frozenset[str] = frozenset()
    verification_path = latest_verification(path.parent)
    if verification_path is None:
        findings.append(
            finding("REGISTER_NOT_VERIFIED", "the owner has not verified the register", file=label)
        )
    else:
        record = json.loads(verification_path.read_text(encoding="utf-8"))
        entries = record.get("entries", {})
        if record.get("record_type") != VERIFICATION_TYPE or not isinstance(entries, dict):
            findings.append(
                finding("REGISTER_INVALID", "the verification record is malformed", file=label)
            )
        else:
            verified = frozenset(
                code for code, person in people.items() if entries.get(code) == person.entry_sha256
            )
            if record.get("register_sha256") != register_sha:
                changed = sorted(set(people) - verified)
                findings.append(
                    finding(
                        "REGISTER_NOT_VERIFIED",
                        "the register changed after the "
                        f"owner's verification; unverified codes {changed}",
                        file=label,
                    )
                )
    return Register(
        people,
        register_sha,
        synthetic,
        verified,
        verification_path.name if verification_path else None,
    ), findings


def build_verification(path: Path, statement: str, verified_on: str) -> dict[str, Any]:
    """The owner's verification record for the register at `path` (the owner signs it)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if problems := _validate(data):
        raise ValueError("; ".join(problems))
    if not statement.strip():
        raise ValueError("the owner's statement is required")
    return {
        "record_type": VERIFICATION_TYPE,
        "verified_on": verified_on,
        "verified_by": "owner",
        "register_sha256": digest(data),
        "entries": {p["code"]: entry_digest(p) for p in data["people"]},
        "statement": statement.strip(),
        "not_claimed": "This is the owner's own statement that each code is one distinct real "
        "person qualified as recorded; the tooling cannot prove it.",
    }


def write_verification(directory: Path, record: dict[str, Any]) -> Path:
    path = directory / f"people_verification_{record['verified_on']}.json"
    return write_once(path, record)[0]
