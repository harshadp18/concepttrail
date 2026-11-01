"""FastAPI dependencies for request-scoped DB access and authorization."""

from __future__ import annotations

import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import ConfigurationError
from app.core.roles import (
    CLASSROOM_PERMISSION_ROLES,
    Permission,
    RoleCode,
    canonical_role_code,
    has_permission,
)
from app.core.security import decode_access_token
from app.db.models import Learner, User
from app.db.repositories.auth_repository import AuthRepository
from app.db.session import get_db
from app.services.authorization_service import user_can_access_classroom

bearer_scheme = HTTPBearer(auto_error=False)


def _forbidden(
    code: str = "forbidden",
    message: str = "You do not have permission to perform this action.",
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": code, "message": message},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorised", "message": "Authentication is required."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id: uuid.UUID = decode_access_token(credentials.credentials)
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "invalid_token",
                "message": "The access token is invalid or expired.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except ConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "authentication_not_configured",
                "message": "Authentication is not configured.",
            },
        ) from None
    user = AuthRepository(session).user_by_id(user_id)
    if user is None or user.is_active is not True:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorised", "message": "Authentication is required."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_learner(
    user: User = Depends(get_current_user),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> Learner:
    """Resolve a learner only when the account also has the canonical student role."""
    repository = AuthRepository(session)
    learner = repository.learner_for_user(user.user_id)
    roles = repository.roles_for_user(user.user_id)
    if learner is None or not has_permission(roles, Permission.LEARNING_PROGRESS_READ_SELF):
        raise _forbidden("learner_access_required", "An authorised student account is required.")
    return learner


def require_role(role_code: str | RoleCode):
    """Build a dependency for one recognized role code.

    Unknown required-role names are programmer/configuration errors and are rejected
    while routes are being declared. Unknown roles returned by the database never
    satisfy a recognized role requirement.
    """
    required_role = canonical_role_code(role_code)

    def role_dependency(
        user: User = Depends(get_current_user),  # noqa: B008
        session: Session = Depends(get_db),  # noqa: B008
    ) -> User:
        roles = AuthRepository(session).roles_for_user(user.user_id)
        if required_role.value not in roles:
            raise _forbidden("forbidden_role")
        return user

    return role_dependency


def require_permission(permission: Permission | str):
    """Require a non-classroom-scoped permission from an assigned known role."""
    try:
        required = Permission(permission)
    except (ValueError, TypeError):
        raise ValueError("permission must be a recognized Permission") from None
    if required in CLASSROOM_PERMISSION_ROLES:
        raise ValueError("Use require_classroom_permission for classroom-scoped access")

    def permission_dependency(
        user: User = Depends(get_current_user),  # noqa: B008
        session: Session = Depends(get_db),  # noqa: B008
    ) -> User:
        roles = AuthRepository(session).roles_for_user(user.user_id)
        if not has_permission(roles, required):
            raise _forbidden("forbidden_permission")
        return user

    return permission_dependency


def require_classroom_permission(permission: Permission | str):
    """Require a role permission plus the user's active relation to `{class_id}`.

    Teacher permissions are scoped to active teacher assignments. Student classroom
    access is scoped to active learner enrollments. No school-admin class scope is
    enabled until the project approves and implements an authoritative school link.
    """
    try:
        required = Permission(permission)
    except (ValueError, TypeError):
        raise ValueError("permission must be a recognized Permission") from None
    if required not in CLASSROOM_PERMISSION_ROLES:
        raise ValueError("permission is not classroom-scoped")

    def classroom_permission_dependency(
        class_id: uuid.UUID,
        user: User = Depends(get_current_user),  # noqa: B008
        session: Session = Depends(get_db),  # noqa: B008
    ) -> User:
        repository = AuthRepository(session)
        roles = repository.roles_for_user(user.user_id)
        learner = repository.learner_for_user(user.user_id)
        enrolled_ids = (
            [item.classroom_id for item in repository.enrolled_classrooms(learner.learner_id)]
            if learner is not None
            else []
        )
        assigned_ids = [item.classroom_id for item in repository.assigned_classrooms(user.user_id)]
        if not user_can_access_classroom(
            roles,
            required,
            class_id,
            enrolled_classroom_ids=enrolled_ids,
            assigned_classroom_ids=assigned_ids,
        ):
            raise _forbidden("forbidden_classroom")
        return user

    return classroom_permission_dependency


def require_teacher_classroom_assignment(
    class_id: uuid.UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> User:
    """Require a teacher role and an active assignment to `{class_id}`."""
    repository = AuthRepository(session)
    roles = repository.roles_for_user(user.user_id)
    assigned_ids = [item.classroom_id for item in repository.assigned_classrooms(user.user_id)]
    if not user_can_access_classroom(
        roles,
        Permission.CLASSROOM_READ_ASSIGNED,
        class_id,
        assigned_classroom_ids=assigned_ids,
    ):
        raise _forbidden("forbidden_classroom", "You are not authorised for this classroom.")
    return user


def require_active_learner_enrollment(
    class_id: uuid.UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> Learner:
    """Require student role, learner record and active enrollment in `{class_id}`."""
    repository = AuthRepository(session)
    learner = repository.learner_for_user(user.user_id)
    roles = repository.roles_for_user(user.user_id)
    enrolled_ids = (
        [item.classroom_id for item in repository.enrolled_classrooms(learner.learner_id)]
        if learner is not None
        else []
    )
    if learner is None or not user_can_access_classroom(
        roles,
        Permission.CLASSROOM_READ_ENROLLED,
        class_id,
        enrolled_classroom_ids=enrolled_ids,
    ):
        raise _forbidden("forbidden_classroom", "You are not enrolled in this classroom.")
    return learner
