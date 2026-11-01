"""Read-only persistence operations used by authentication."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ClassEnrollment,
    Classroom,
    Learner,
    Role,
    TeacherClassAssignment,
    User,
    UserRole,
)


class AuthRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def user_by_identifier(self, identifier: str) -> User | None:
        return self.session.scalar(select(User).where(User.login_identifier == identifier))

    def user_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.session.get(User, user_id)

    def learner_for_user(self, user_id: uuid.UUID) -> Learner | None:
        return self.session.scalar(select(Learner).where(Learner.user_id == user_id))

    def roles_for_user(self, user_id: uuid.UUID) -> list[str]:
        statement = (
            select(Role.role_code)
            .join(UserRole, UserRole.role_code == Role.role_code)
            .where(UserRole.user_id == user_id)
            .order_by(Role.role_code)
        )
        return list(self.session.scalars(statement).all())

    def enrolled_classrooms(self, learner_id: uuid.UUID) -> list[Classroom]:
        statement = (
            select(Classroom)
            .join(ClassEnrollment, ClassEnrollment.classroom_id == Classroom.classroom_id)
            .where(
                ClassEnrollment.learner_id == learner_id,
                ClassEnrollment.ended_at.is_(None),
                Classroom.active.is_(True),
            )
            .order_by(Classroom.grade_level, Classroom.section_label)
        )
        return list(self.session.scalars(statement).all())

    def assigned_classrooms(self, user_id: uuid.UUID) -> list[Classroom]:
        statement = (
            select(Classroom)
            .join(
                TeacherClassAssignment,
                TeacherClassAssignment.classroom_id == Classroom.classroom_id,
            )
            .where(
                TeacherClassAssignment.user_id == user_id,
                TeacherClassAssignment.ended_at.is_(None),
                Classroom.active.is_(True),
            )
            .order_by(Classroom.grade_level, Classroom.section_label)
        )
        return list(self.session.scalars(statement).all())
