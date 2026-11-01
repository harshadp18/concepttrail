"""Runtime access to the purpose-specific rights gate (`data_pipeline.authorization`).

The authorization records are the single source of truth. If the module or its records are not
available in this deployment, every use is refused (fail closed); nothing here grants a use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class _Refused:
    use: str
    allowed: bool = False
    reason: str = "rights gate unavailable in this deployment"
    record_id: str | None = None


def check_use(source_id: str, sha256: str, use: str, records: list[dict[str, Any]] | None = None):
    try:
        from data_pipeline.authorization import check_use as gate
    except ImportError:
        return _Refused(use)
    return gate(source_id, sha256, use, records)
