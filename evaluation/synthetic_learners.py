"""Reproducible SYNTHETIC learners with known ground truth (never real learner data).

Each generated sequence records its generating parameters, the hidden knowledge state before
every response, and `synthetic: true`. Nothing here touches the database.

Generative model (BKT, Corbett & Anderson 1995) with optional, explicitly named departures used
to test robustness ("model mismatch"):

- `forget`: a known skill can be lost between opportunities (BKT assumes it never is);
- `learner_sd`: per-learner variation of the learning rate on the logit scale (BKT assumes one
  rate per skill);
- `item_sd`: per-opportunity variation of guess/slip, i.e. items of different difficulty;
- `burst_gap`: irregular practice, a gap after which forgetting is applied once more.

Learner profiles shift initial knowledge, learning rate, guessing and carelessness so a
population mixes fast, slow, guess-prone, careless, high- and low-prior learners. Sparse and
incomplete histories come from per-learner sequence lengths and random truncation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

SYNTHETIC_MARK = "SYNTHETIC-NOT-REAL-LEARNERS"


def logit(p: np.ndarray | float) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sigmoid(x: np.ndarray | float) -> np.ndarray:
    return 1 / (1 + np.exp(-x))


@dataclass(frozen=True)
class KcTruth:
    """Ground-truth BKT parameters of one synthetic knowledge component."""

    name: str
    p_l0: float
    p_t: float
    p_g: float
    p_s: float


# A deliberately varied set: typical, hard, guess-prone (true/false-like), careless-prone,
# fast-learned and high-prior skills. Values are plausible for school practice data but are
# made up for testing; they are not estimates of any real skill.
KC_TYPES: tuple[KcTruth, ...] = (
    KcTruth("typical", 0.25, 0.12, 0.20, 0.08),
    KcTruth("hard", 0.10, 0.06, 0.15, 0.10),
    KcTruth("guessy", 0.30, 0.10, 0.35, 0.08),
    KcTruth("careless", 0.35, 0.15, 0.15, 0.18),
    KcTruth("fast", 0.15, 0.30, 0.20, 0.06),
    KcTruth("high_prior", 0.60, 0.10, 0.20, 0.07),
)


@dataclass(frozen=True)
class Profile:
    """Shifts applied to a KC's parameters for one kind of learner (logit-scale offsets)."""

    name: str
    weight: float
    prior_shift: float = 0.0
    learn_shift: float = 0.0
    guess_shift: float = 0.0
    slip_shift: float = 0.0


POPULATIONS: dict[str, tuple[Profile, ...]] = {
    # Every learner follows the KC's parameters exactly: the identifiable BKT case.
    "homogeneous": (Profile("standard", 1.0),),
    # A realistic mix: the same KC behaves differently for different learners.
    "mixed": (
        Profile("standard", 0.40),
        Profile("fast", 0.15, learn_shift=1.0),
        Profile("slow", 0.15, learn_shift=-1.0),
        Profile("guess_prone", 0.10, guess_shift=0.8),
        Profile("careless", 0.10, slip_shift=0.9),
        Profile("high_start", 0.05, prior_shift=1.5),
        Profile("low_start", 0.05, prior_shift=-1.5),
    ),
}


@dataclass(frozen=True)
class Mismatch:
    forget: float = 0.0
    learner_sd: float = 0.0
    item_sd: float = 0.0
    burst_gap: float = 0.0  # probability, per step, of a long gap (one extra forgetting draw)


@dataclass
class Dataset:
    """Padded arrays: outcomes[n, L] (0/1), known_before[n, L] (hidden state), mask[n, L]."""

    kc: KcTruth
    outcomes: np.ndarray
    known_before: np.ndarray
    mask: np.ndarray
    profiles: list[str]
    meta: dict = field(default_factory=dict)

    @property
    def events(self) -> int:
        return int(self.mask.sum())

    def records(self) -> list[dict]:
        """JSON-friendly rows, each explicitly marked synthetic."""
        out = []
        for i in range(self.outcomes.shape[0]):
            n = int(self.mask[i].sum())
            out.append(
                {
                    "synthetic": True,
                    "mark": SYNTHETIC_MARK,
                    "learner": f"syn-{self.meta.get('seed')}-{i}",
                    "profile": self.profiles[i],
                    "kc": self.kc.name,
                    "outcomes": self.outcomes[i, :n].astype(int).tolist(),
                    "hidden_known_before": self.known_before[i, :n].astype(int).tolist(),
                }
            )
        return out


def generate(
    kc: KcTruth,
    learners: int,
    length: int,
    seed: int,
    population: str = "homogeneous",
    mismatch: Mismatch = Mismatch(),  # noqa: B008  (immutable)
    min_length: int | None = None,
    truncate_prob: float = 0.0,
) -> Dataset:
    """Simulate `learners` independent sequences of up to `length` opportunities on one KC.

    `min_length` < `length` gives variable-length histories; `truncate_prob` cuts a share of
    histories at a random point (incomplete data).
    """
    rng = np.random.default_rng(seed)
    profiles = POPULATIONS[population]
    weights = np.array([p.weight for p in profiles])
    chosen = rng.choice(len(profiles), size=learners, p=weights / weights.sum())
    prof = [profiles[i] for i in chosen]
    shift = lambda attr: np.array([getattr(p, attr) for p in prof])  # noqa: E731
    p_l0 = sigmoid(logit(kc.p_l0) + shift("prior_shift"))
    p_t = sigmoid(
        logit(kc.p_t) + shift("learn_shift") + rng.normal(0, mismatch.learner_sd, learners)
    )
    g_base = logit(kc.p_g) + shift("guess_shift")
    s_base = logit(kc.p_s) + shift("slip_shift")
    lengths = np.full(learners, length)
    if min_length is not None and min_length < length:
        lengths = rng.integers(min_length, length + 1, size=learners)
    cut = rng.random(learners) < truncate_prob
    lengths = np.where(cut, np.maximum(1, (lengths * rng.random(learners)).astype(int)), lengths)
    outcomes = np.zeros((learners, length), dtype=np.int8)
    known_before = np.zeros((learners, length), dtype=np.int8)
    mask = np.arange(length)[None, :] < lengths[:, None]
    known = rng.random(learners) < p_l0
    for t in range(length):
        g = sigmoid(g_base + rng.normal(0, mismatch.item_sd, learners))
        s = sigmoid(s_base + rng.normal(0, mismatch.item_sd, learners))
        known_before[:, t] = known
        p_correct = np.where(known, 1 - s, g)
        outcomes[:, t] = rng.random(learners) < p_correct
        learn = (~known) & (rng.random(learners) < p_t)
        forget = known & (rng.random(learners) < mismatch.forget)
        burst = (
            known
            & (rng.random(learners) < mismatch.burst_gap)
            & (rng.random(learners) < max(mismatch.forget, 0.3))
        )
        known = (known | learn) & ~forget & ~burst
    outcomes = np.where(mask, outcomes, 0)
    return Dataset(
        kc,
        outcomes,
        np.where(mask, known_before, 0),
        mask,
        [p.name for p in prof],
        {
            "seed": seed,
            "learners": learners,
            "length": length,
            "population": population,
            "mismatch": asdict(mismatch),
            "min_length": min_length,
            "truncate_prob": truncate_prob,
            "synthetic": True,
        },
    )
