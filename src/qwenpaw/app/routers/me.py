# -*- coding: utf-8 -*-
"""当前用户与个人偏好 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ...identity.models import UserProfileUpdate, UserRecord
from ...identity.audit import UserAuditRepository
from ...access.actor import actor_from_request
from ...identity.repository import DuplicateUsernameError
from ...identity.runtime import get_identity_runtime
from ...identity.service import CurrentPasswordIncorrectError
from ...identity.sessions import AuthenticatedSession

router = APIRouter(prefix="/me", tags=["me"])


def get_user_audit_repository() -> UserAuditRepository:
    return UserAuditRepository(schema=get_identity_runtime_schema())


def get_identity_runtime_schema() -> str:
    from ...identity.runtime import get_identity_schema

    return get_identity_schema()


class PreferenceUpdate(BaseModel):
    language: str = Field(min_length=2, max_length=32)
    timezone: str = Field(min_length=1, max_length=128)


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=32)
    department: str | None = Field(default=None, max_length=128)
    job_title: str | None = Field(default=None, max_length=128)
    remark: str | None = Field(default=None, max_length=500)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)


def _authenticated(request: Request) -> AuthenticatedSession:
    value = getattr(request.state, "authenticated_session", None)
    if not isinstance(value, AuthenticatedSession):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return value


def _user_payload(user: UserRecord) -> dict[str, object]:
    return {
        "id": str(user.id),
        "username": user.username,
        "platform_role": user.platform_role.value,
        "status": user.status,
        "display_name": user.display_name,
        "email": user.email,
        "phone": user.phone,
        "department": user.department,
        "job_title": user.job_title,
        "remark": user.remark,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


@router.get("")
async def get_me(request: Request):
    authenticated = _authenticated(request)
    preferences = await get_identity_runtime().preferences.get_or_create(
        authenticated.user.id
    )
    return {
        "user": _user_payload(authenticated.user),
        "preferences": {
            "language": preferences.language,
            "timezone": preferences.timezone,
        },
    }


@router.patch("/preferences")
async def update_preferences(request: Request, payload: PreferenceUpdate):
    authenticated = _authenticated(request)
    preferences = await get_identity_runtime().preferences.update(
        authenticated.user.id,
        language=payload.language.strip(),
        timezone=payload.timezone.strip(),
    )
    return {
        "language": preferences.language,
        "timezone": preferences.timezone,
    }


@router.patch("/profile")
async def update_profile(
    request: Request,
    payload: ProfileUpdateRequest,
    audit: UserAuditRepository = Depends(get_user_audit_repository),
):
    authenticated = _authenticated(request)
    try:
        user = await get_identity_runtime().users.update_profile(
            authenticated.user.id,
            UserProfileUpdate(**payload.model_dump()),
        )
    except DuplicateUsernameError as exc:
        raise HTTPException(status_code=409, detail="username_already_exists") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    actor = actor_from_request(request, multi_user=True)
    if actor is not None:
        await audit.record(
            actor=actor,
            target_user_id=authenticated.user.id,
            action="user.profile.update",
            changed_fields=list(payload.model_fields_set),
        )
    return {"user": _user_payload(user)}


@router.post("/change-password")
async def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    audit: UserAuditRepository = Depends(get_user_audit_repository),
):
    authenticated = _authenticated(request)
    runtime = get_identity_runtime()
    try:
        await runtime.users.change_password(
            authenticated.user.id,
            payload.current_password,
            payload.new_password,
        )
    except CurrentPasswordIncorrectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    revoked = await runtime.sessions.revoke_all(authenticated.user.id)
    actor = actor_from_request(request, multi_user=True)
    if actor is not None:
        await audit.record(
            actor=actor,
            target_user_id=authenticated.user.id,
            action="user.password.change",
            changed_fields=["password"],
        )
    return {"revoked_sessions": revoked}
