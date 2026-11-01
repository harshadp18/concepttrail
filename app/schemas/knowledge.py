"""Typed knowledge-component (KC) and prerequisite-edge records for the Phase 5 graph service.

These are domain schemas, separate from the SQLAlchemy models. Field names follow
`knowledge_component` and `kc_edge`. The class level of a KC is not a column on the KC table: it
comes from its curriculum mappings (`kc_curriculum_map` -> `curriculum_item`) or, before those
exist, from the author's declaration in the curated CSV; it is carried here as `class_levels`, and
an empty tuple means "no class yet".

`scope` and `lifecycle` have no database column; they come from the curated CSV and the private
lifecycle log. A `foundation` KC is taught before Class 6, has no class levels and is reported
separately. A `retired` KC stays `approved` (lifecycle is separate from review status) but is
never part of a traversable graph.

Shape is validated here (types, non-empty text, ranges). Graph rules (duplicates, missing
endpoints, self-edges, cycles, release gating) are checked by `app.services.prerequisite_graph`,
which reports every problem instead of failing on the first one.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# The project's existing review vocabulary (inventory REVIEW_STATUSES).
ReviewStatus = Literal["needs_review", "in_review", "approved", "rejected"]
Scope = Literal["target", "foundation"]
Lifecycle = Literal["active", "retired"]
CLASS_LEVELS = (6, 7, 8, 9, 10)

Identifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128, pattern=r"^\S+$")
]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# Stable, class- and subject-neutral key: lowercase slug.
StableKey = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
]


class KcRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kc_id: Identifier
    stable_key: StableKey
    subject_id: Identifier
    name: Text
    kc_type: Text | None = None
    difficulty_tier: int | None = Field(default=None, ge=1)
    review_status: ReviewStatus = "needs_review"
    class_levels: tuple[Literal[6, 7, 8, 9, 10], ...] = ()
    scope: Scope = "target"
    lifecycle: Lifecycle = "active"


class EdgeRecord(BaseModel):
    """`prerequisite_kc_id` is a prerequisite of `dependent_kc_id`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prerequisite_kc_id: Identifier
    dependent_kc_id: Identifier
    reason: Text  # the pedagogical justification; an edge without one is never proposed
    strength: int | None = Field(default=None, ge=1)
    evidence_refs: tuple[Text, ...] = ()
    review_status: ReviewStatus = "needs_review"

    @property
    def key(self) -> tuple[str, str]:
        return (self.prerequisite_kc_id, self.dependent_kc_id)
