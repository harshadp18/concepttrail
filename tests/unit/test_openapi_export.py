"""The checked-in OpenAPI export matches the application's actual routes and schemas."""

from __future__ import annotations

import json

from scripts.export_openapi import TARGET, render


def test_export_is_current() -> None:
    assert TARGET.read_text(encoding="utf-8") == render(), "run: python -m scripts.export_openapi"


def test_export_lists_only_implemented_routes() -> None:
    paths = json.loads(render())["paths"]
    assert set(paths) == {
        "/health",
        "/ready",
        "/api/v1/auth/login",
        "/api/v1/me",
        "/api/v1/curriculum",
        "/api/v1/curriculum/items/{item_id}/topics",
        "/api/v1/topics/{kc_id}",
        "/api/v1/topics/{kc_id}/questions",
        "/api/v1/attempts",
        "/api/v1/student/progress",
        "/api/v1/student/recommendation",
        "/api/v1/doubts",
        "/api/v1/teacher/classes/{class_id}/dashboard",
        "/api/v1/jobs/{job_id}",
        "/api/v1/teacher/review/questions",
        "/api/v1/teacher/review/questions/{question_id}",
        "/api/v1/teacher/classes/{class_id}/interventions",
        "/api/v1/teacher/classes/{class_id}/interventions/{intervention_id}/status",
        "/api/v1/catalog/classes",
        "/api/v1/curriculum/items/{item_id}",
        "/api/v1/topics/{kc_id}/prerequisites",
        "/api/v1/student/progress/chapters",
        "/api/v1/student/activity",
        "/api/v1/student/weak-areas",
        "/api/v1/student/review",
        "/api/v1/student/doubts/conversations",
        "/api/v1/student/doubts/conversations/{conversation_id}",
        "/api/v1/student/doubts/conversations/{conversation_id}/archive",
        "/api/v1/teacher/classes",
        "/api/v1/teacher/classes/{class_id}/learners",
        "/api/v1/teacher/classes/{class_id}/learners/{learner_id}/progress",
        "/api/v1/teacher/classes/{class_id}/weak-areas",
        "/api/v1/notifications",
        "/api/v1/notifications/read-all",
        "/api/v1/notifications/{notification_id}/read",
        "/api/v1/teacher/classes/{class_id}/heatmap",
        "/api/v1/teacher/classes/{class_id}/bell-ringer/topics",
        "/api/v1/teacher/classes/{class_id}/bell-ringer/cycles",
        "/api/v1/teacher/classes/{class_id}/bell-ringer/cycles/{cycle_id}",
        "/api/v1/teacher/classes/{class_id}/bell-ringer/cycles/{cycle_id}/status",
    }
