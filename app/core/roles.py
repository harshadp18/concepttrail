"""Canonical application role codes and the least-privilege permission matrix.

These constants do not provision roles in PostgreSQL. The ``school_admin`` code is
provisional and intentionally grants no school-scoped or administrative permissions
until an approved school-membership mapping and policy exist.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from types import MappingProxyType


class RoleCode(StrEnum):
    STUDENT = "student"
    TEACHER = "teacher"
    SCHOOL_ADMIN = "school_admin"


class Permission(StrEnum):
    PROFILE_READ_SELF = "profile:read:self"
    LEARNING_PROGRESS_READ_SELF = "learning_progress:read:self"
    ATTEMPT_CREATE_SELF = "attempt:create:self"
    DOUBT_CREATE_SELF = "doubt:create:self"
    CLASSROOM_READ_ENROLLED = "classroom:read:enrolled"
    CLASSROOM_READ_ASSIGNED = "classroom:read:assigned"
    LEARNER_PROGRESS_READ_ASSIGNED = "learner_progress:read:assigned"
    LEARNING_ACTIVITIES_MANAGE_ASSIGNED = "learning_activities:manage:assigned"


KNOWN_ROLE_CODES = frozenset(role.value for role in RoleCode)


def canonical_role_code(role_code: str | RoleCode) -> RoleCode:
    """Validate a role code used in application route configuration."""
    try:
        return RoleCode(role_code)
    except (ValueError, TypeError):
        raise ValueError("role_code must be a recognized canonical RoleCode") from None


# Immutable at runtime to prevent route code from accidentally expanding access.
ROLE_PERMISSIONS = MappingProxyType(
    {
        RoleCode.STUDENT: frozenset(
            {
                Permission.PROFILE_READ_SELF,
                Permission.LEARNING_PROGRESS_READ_SELF,
                Permission.ATTEMPT_CREATE_SELF,
                Permission.DOUBT_CREATE_SELF,
                Permission.CLASSROOM_READ_ENROLLED,
            }
        ),
        RoleCode.TEACHER: frozenset(
            {
                Permission.PROFILE_READ_SELF,
                Permission.CLASSROOM_READ_ASSIGNED,
                Permission.LEARNER_PROGRESS_READ_ASSIGNED,
                Permission.LEARNING_ACTIVITIES_MANAGE_ASSIGNED,
            }
        ),
        # Provisional only: own profile is not a school-administration capability.
        # All school-scoped and administrative access remains denied pending approval.
        RoleCode.SCHOOL_ADMIN: frozenset({Permission.PROFILE_READ_SELF}),
    }
)


# For a classroom-scoped permission, at least one matching role AND its active
# membership relation must be present. A school-admin role has no matching scope yet.
CLASSROOM_PERMISSION_ROLES = MappingProxyType(
    {
        Permission.CLASSROOM_READ_ENROLLED: frozenset({RoleCode.STUDENT}),
        Permission.CLASSROOM_READ_ASSIGNED: frozenset({RoleCode.TEACHER}),
        Permission.LEARNER_PROGRESS_READ_ASSIGNED: frozenset({RoleCode.TEACHER}),
        Permission.LEARNING_ACTIVITIES_MANAGE_ASSIGNED: frozenset({RoleCode.TEACHER}),
    }
)


def recognized_roles(role_codes: Iterable[str]) -> frozenset[RoleCode]:
    """Return only canonical roles; unknown database values grant nothing."""
    recognized: set[RoleCode] = set()
    for code in role_codes:
        try:
            recognized.add(RoleCode(code))
        except (ValueError, TypeError):
            continue
    return frozenset(recognized)


def permissions_for_roles(role_codes: Iterable[str]) -> frozenset[Permission]:
    """Union permissions from recognized roles; unknown role codes are ignored."""
    permissions: set[Permission] = set()
    for role in recognized_roles(role_codes):
        permissions.update(ROLE_PERMISSIONS[role])
    return frozenset(permissions)


def has_permission(role_codes: Iterable[str], permission: Permission | str) -> bool:
    """Fail-closed permission check for a known permission and assigned roles."""
    try:
        required = Permission(permission)
    except (ValueError, TypeError):
        return False
    return required in permissions_for_roles(role_codes)


def can_access_classroom(
    role_codes: Iterable[str],
    permission: Permission | str,
    classroom_id: object,
    *,
    enrolled_classroom_ids: Iterable[object] = (),
    assigned_classroom_ids: Iterable[object] = (),
) -> bool:
    """Check role, permission and active classroom membership together.

    The caller must supply classroom IDs obtained from trusted database queries,
    never from client-provided claims. School admins intentionally fail closed here.
    """
    try:
        required = Permission(permission)
    except (ValueError, TypeError):
        return False

    permitted_roles = CLASSROOM_PERMISSION_ROLES.get(required)
    if not permitted_roles:
        return False

    roles = recognized_roles(role_codes)
    if not any(role in permitted_roles for role in roles):
        return False
    if not has_permission((role.value for role in roles), required):
        return False

    if RoleCode.STUDENT in roles and required is Permission.CLASSROOM_READ_ENROLLED:
        return classroom_id in set(enrolled_classroom_ids)

    if RoleCode.TEACHER in roles and required in {
        Permission.CLASSROOM_READ_ASSIGNED,
        Permission.LEARNER_PROGRESS_READ_ASSIGNED,
        Permission.LEARNING_ACTIVITIES_MANAGE_ASSIGNED,
    }:
        return classroom_id in set(assigned_classroom_ids)

    return False
