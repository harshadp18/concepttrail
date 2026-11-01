"""Which review states may be served to learners, in one place (fail closed).

Production serves only human-approved KCs, questions and mappings (`approved`) and published
curriculum (`published`). Demo mode (`CONTENT_RELEASE_MODE=demo`, development/test only, see
`Settings`) additionally serves AI-generated `demo_release` content, which is never
human-approved. Every serving filter calls these helpers instead of hard-coding a status, so a
production deployment cannot widen them by accident.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings

DEMO_STATUS = "demo_release"


def demo_enabled(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return settings.content_release_mode == "demo" and settings.app_env in ("development", "test")


def servable_review_statuses(settings: Settings | None = None) -> tuple[str, ...]:
    """For KCs, questions, question-KC and KC-curriculum mappings, edges and notes."""
    return ("approved", DEMO_STATUS) if demo_enabled(settings) else ("approved",)


def servable_curriculum_statuses(settings: Settings | None = None) -> tuple[str, ...]:
    """For `curriculum_version.status` and `curriculum_item.status`."""
    return ("published", DEMO_STATUS) if demo_enabled(settings) else ("published",)
