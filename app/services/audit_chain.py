"""Hash-chain primitives shared by the Phase 5 review log, lifecycle log and graph snapshots.

Pure functions: canonical JSON, SHA-256, and chain verification. A chain is a list of JSON
objects, each holding `seq` (1, 2, ...), an ID (`<prefix>` plus `seq` zero-padded to four
digits), `prev_hash` (the previous event's `event_hash`, or 64 zeros for the first event) and
`event_hash` (SHA-256 of the canonical JSON of the event without `event_hash`).

A hash chain is tamper-evident, not immutable storage: it makes most edits detectable and
prevents none. Truncation and whole-log replacement are detected only against separately kept
anchors (see `data_pipeline.kc_graph.review_log`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

GENESIS_HASH = "0" * 64


def canonical_json(value: Any) -> bytes:
    """UTF-8, sorted keys, no insignificant whitespace."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value: Any) -> str:
    return sha256_hex(canonical_json(value))


def event_hash(event: dict[str, Any]) -> str:
    return digest({k: v for k, v in event.items() if k != "event_hash"})


def event_id(prefix: str, seq: int) -> str:
    return f"{prefix}{seq:04d}"


def head_hash(events: Sequence[dict[str, Any]]) -> str:
    return str(events[-1].get("event_hash", "")) if events else GENESIS_HASH


@dataclass(frozen=True)
class ChainProblem:
    seq: int  # position in the file (1-based), not the event's own claim
    message: str


def verify_chain(events: Sequence[dict[str, Any]], id_prefix: str) -> list[ChainProblem]:
    """Every problem in the chain; an empty list means the chain is internally consistent."""
    problems: list[ChainProblem] = []
    previous = GENESIS_HASH
    seen_ids: set[str] = set()
    for position, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            problems.append(ChainProblem(position, "event is not a JSON object"))
            continue
        if event.get("seq") != position:
            problems.append(ChainProblem(position, f"seq {event.get('seq')!r} is not consecutive"))
        expected_id = event_id(id_prefix, position)
        claimed_id = event.get("event_id")
        if claimed_id in seen_ids:
            problems.append(ChainProblem(position, f"duplicate event ID {claimed_id}"))
        seen_ids.add(claimed_id)
        if claimed_id != expected_id:
            problems.append(ChainProblem(position, f"event ID {claimed_id!r} != {expected_id}"))
        if event.get("prev_hash") != previous:
            problems.append(ChainProblem(position, "prev_hash does not match the previous event"))
        if event.get("event_hash") != event_hash(event):
            problems.append(ChainProblem(position, "event_hash does not recompute"))
        previous = event.get("event_hash", "")
    return problems


def seal(event: dict[str, Any], previous: Sequence[dict[str, Any]], id_prefix: str) -> dict:
    """Return `event` with its chain fields set, appended after `previous`."""
    seq = len(previous) + 1
    sealed = {k: v for k, v in event.items() if k not in ("seq", "event_id", "prev_hash")}
    sealed.update(seq=seq, event_id=event_id(id_prefix, seq), prev_hash=head_hash(previous))
    sealed.pop("event_hash", None)
    sealed["event_hash"] = event_hash(sealed)
    return sealed
