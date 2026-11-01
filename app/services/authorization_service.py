"""Deterministic, database-independent authorization policy helpers."""

from __future__ import annotations

from collections.abc import Iterable

from app.core.roles import Permission, can_access_classroom, has_permission


def user_has_permission(role_codes: Iterable[str], permission: Permission | str) -> bool:
    """Check a non-resource-specific permission using canonical role policy."""
    return has_permission(role_codes, permission)


def user_can_access_classroom(
    role_codes: Iterable[str],
    permission: Permission | str,
    classroom_id: object,
    *,
    enrolled_classroom_ids: Iterable[object] = (),
    assigned_classroom_ids: Iterable[object] = (),
) -> bool:
    """Require both the permission and an active, role-appropriate class link."""
    return can_access_classroom(
        role_codes,
        permission,
        classroom_id,
        enrolled_classroom_ids=enrolled_classroom_ids,
        assigned_classroom_ids=assigned_classroom_ids,
    )
