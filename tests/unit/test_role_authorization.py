"""Role policy and classroom authorization tests; no PostgreSQL required."""

from __future__ import annotations

import uuid

import pytest

from app.core.roles import (
    KNOWN_ROLE_CODES,
    ROLE_PERMISSIONS,
    Permission,
    RoleCode,
    can_access_classroom,
    canonical_role_code,
    has_permission,
    permissions_for_roles,
    recognized_roles,
)


def test_role_constants_are_the_provisional_canonical_codes() -> None:
    assert KNOWN_ROLE_CODES == {"student", "teacher", "school_admin"}
    assert set(ROLE_PERMISSIONS) == {
        RoleCode.STUDENT,
        RoleCode.TEACHER,
        RoleCode.SCHOOL_ADMIN,
    }


def test_unknown_role_grants_no_permissions() -> None:
    assert recognized_roles(["future_superuser", "unknown"]) == frozenset()
    assert permissions_for_roles(["future_superuser"]) == frozenset()
    assert not has_permission(["future_superuser"], Permission.PROFILE_READ_SELF)


def test_unknown_role_does_not_add_permissions_to_a_known_role() -> None:
    roles = ["teacher", "future_superuser"]
    assert has_permission(roles, Permission.LEARNER_PROGRESS_READ_ASSIGNED)
    assert not has_permission(roles, "system:delete:everything")
    assert Permission.ATTEMPT_CREATE_SELF not in permissions_for_roles(roles)


def test_unknown_required_role_is_rejected_during_route_configuration() -> None:
    with pytest.raises(ValueError, match="recognized canonical RoleCode"):
        canonical_role_code("future_superuser")


def test_teacher_can_access_only_an_actively_assigned_classroom() -> None:
    assigned = uuid.uuid4()
    other = uuid.uuid4()
    assert can_access_classroom(
        ["teacher"],
        Permission.LEARNER_PROGRESS_READ_ASSIGNED,
        assigned,
        assigned_classroom_ids=[assigned],
    )
    assert not can_access_classroom(
        ["teacher"],
        Permission.LEARNER_PROGRESS_READ_ASSIGNED,
        other,
        assigned_classroom_ids=[assigned],
    )


def test_teacher_assignment_without_teacher_role_does_not_grant_access() -> None:
    classroom = uuid.uuid4()
    assert not can_access_classroom(
        ["unknown_role"],
        Permission.CLASSROOM_READ_ASSIGNED,
        classroom,
        assigned_classroom_ids=[classroom],
    )


def test_student_can_access_only_an_actively_enrolled_classroom() -> None:
    enrolled = uuid.uuid4()
    other = uuid.uuid4()
    assert can_access_classroom(
        ["student"],
        Permission.CLASSROOM_READ_ENROLLED,
        enrolled,
        enrolled_classroom_ids=[enrolled],
    )
    assert not can_access_classroom(
        ["student"],
        Permission.CLASSROOM_READ_ENROLLED,
        other,
        enrolled_classroom_ids=[enrolled],
    )
    assert not can_access_classroom(
        ["student"],
        Permission.CLASSROOM_READ_ASSIGNED,
        enrolled,
        enrolled_classroom_ids=[enrolled],
    )


def test_school_admin_has_no_school_or_classroom_scope_yet() -> None:
    classroom = uuid.uuid4()
    assert has_permission(["school_admin"], Permission.PROFILE_READ_SELF)
    assert not has_permission(["school_admin"], Permission.LEARNER_PROGRESS_READ_ASSIGNED)
    assert not can_access_classroom(
        ["school_admin"],
        Permission.LEARNER_PROGRESS_READ_ASSIGNED,
        classroom,
        assigned_classroom_ids=[classroom],
        enrolled_classroom_ids=[classroom],
    )


def test_classroom_access_fails_closed_for_unknown_permission_or_role() -> None:
    classroom = uuid.uuid4()
    assert not can_access_classroom(
        ["teacher"],
        "classroom:delete:all",
        classroom,
        assigned_classroom_ids=[classroom],
    )
    assert not can_access_classroom(
        ["not-a-role"],
        Permission.CLASSROOM_READ_ASSIGNED,
        classroom,
        assigned_classroom_ids=[classroom],
    )
