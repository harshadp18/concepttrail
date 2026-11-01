"""Small, dependency-free statistics for evaluation reports (deterministic, unit-tested)."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

MIN_STRATUM = 10  # fewer items than this in a breakdown cell: report insufficient_data, no rate


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for a proportion; None when n == 0."""
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def rate(successes: int, n: int, min_n: int = MIN_STRATUM) -> dict:
    """A proportion with its denominator and interval, or an explicit insufficient_data cell."""
    if n < min_n:
        return {"status": "insufficient_data", "n": n, "min_n": min_n}
    return {
        "status": "measured",
        "n": n,
        "count": successes,
        "rate": round(successes / n, 4),
        "ci95": wilson(successes, n),
    }


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    """Agreement of two raters on the same items beyond chance; None when undefined."""
    if len(a) != len(b) or not a:
        return None
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if expected == 1.0:
        return None
    return round((observed - expected) / (1 - expected), 4)


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    return len(set(ranked[:k]) & relevant) / len(relevant)


def reciprocal_rank(ranked: Sequence[str], relevant: set[str], k: int = 10) -> float | None:
    if not relevant:
        return None
    for position, item in enumerate(ranked[:k], start=1):
        if item in relevant:
            return 1.0 / position
    return 0.0
