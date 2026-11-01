"""Public authentication DTOs. Never expose ORM models directly."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login_identifier: str = Field(min_length=1, max_length=254)
    credential: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("login_identifier")
    @classmethod
    def strip_identifier(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Login identifier must not be blank")
        return value


class ClassroomContext(BaseModel):
    classroom_id: uuid.UUID
    grade_level: int | None
    section_label: str | None
    academic_session: str | None
    school_label: str | None


class AuthIdentity(BaseModel):
    user_id: uuid.UUID
    login_identifier: str
    roles: list[str]
    learner_id: uuid.UUID | None = None
    display_name: str | None = None
    enrolled_classrooms: list[ClassroomContext] = Field(default_factory=list)
    assigned_classrooms: list[ClassroomContext] = Field(default_factory=list)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    identity: AuthIdentity


class MeResponse(AuthIdentity):
    pass
