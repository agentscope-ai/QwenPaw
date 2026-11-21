# -*- coding: utf-8 -*-
"""管理员用户治理 API。"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field

from ...access.actor import ActorContext
from ...access.dependencies import (
    get_actor,  # noqa: F401 -- exposed for FastAPI dependency overrides in tests
    require_multi_user_mode,
    require_users_manage,
)
from ...identity.governance import (
    LastActiveAdminError,
    UserGovernanceService,
    UserNotFoundError,
)
from ...identity.models import PlatformRole, UserProfileUpdate, UserRecord
from ...identity.audit import UserAuditRepository
from ...identity.repository import DuplicateUsernameError
from ...identity.runtime import get_identity_schema, get_user_governance_service
from ..rate_limiter import rate_limiter

router = APIRouter(
    prefix="/admin/users",
    tags=["admin-users"],
    dependencies=[Depends(require_multi_user_mode)],
)


def get_governance_service() -> UserGovernanceService:
    return get_user_governance_service()


def get_user_audit_repository() -> UserAuditRepository:
    return UserAuditRepository(schema=get_identity_schema())


class UserResponse(BaseModel):
    id: UUID
    username: str
    platform_role: PlatformRole
    status: Literal["active", "disabled"]
    display_name: str | None = None
    email: str | None = None
    phone: str | None = None
    department: str | None = None
    job_title: str | None = None
    remark: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    last_login_at: str | None = None
    login_locked: bool = False
    login_retry_after_seconds: int = 0
    login_failed_attempts: int = 0
    login_remaining_attempts: int = 5


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1)
    platform_role: PlatformRole = PlatformRole.MEMBER


class UpdateStatusRequest(BaseModel):
    status: Literal["active", "disabled"]


class UpdateRoleRequest(BaseModel):
    platform_role: PlatformRole


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=32)
    department: str | None = Field(default=None, max_length=128)
    job_title: str | None = Field(default=None, max_length=128)
    remark: str | None = Field(default=None, max_length=500)


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=1)


class StatusUpdateResponse(BaseModel):
    user: UserResponse
    revoked_sessions: int = 0


class RevokeSessionsResponse(BaseModel):
    revoked_sessions: int


def _response(user: UserRecord) -> UserResponse:
    login = rate_limiter.user_status(user.username)
    return UserResponse(
        id=user.id,
        username=user.username,
        platform_role=user.platform_role,
        status=user.status,
        display_name=user.display_name,
        email=user.email,
        phone=user.phone,
        department=user.department,
        job_title=user.job_title,
        remark=user.remark,
        created_at=user.created_at.isoformat() if user.created_at else None,
        updated_at=user.updated_at.isoformat() if user.updated_at else None,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        login_locked=login.locked,
        login_retry_after_seconds=login.retry_after_seconds,
        login_failed_attempts=login.failed_attempts,
        login_remaining_attempts=login.remaining_attempts,
    )


def _map_governance_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DuplicateUsernameError):
        return HTTPException(status_code=409, detail="username_already_exists")
    if isinstance(exc, LastActiveAdminError):
        return HTTPException(status_code=409, detail="last_active_admin")
    if isinstance(exc, UserNotFoundError):
        return HTTPException(status_code=404, detail="user_not_found")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.get("", response_model=list[UserResponse])
async def list_users(
    _actor: ActorContext = Depends(require_users_manage),
    service: UserGovernanceService = Depends(get_governance_service),
) -> list[UserResponse]:
    return [_response(user) for user in await service.list_users()]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest = Body(...),
    _actor: ActorContext = Depends(require_users_manage),
    service: UserGovernanceService = Depends(get_governance_service),
) -> UserResponse:
    try:
        user = await service.create_user(
            body.username,
            body.password,
            body.platform_role,
        )
    except (DuplicateUsernameError, ValueError) as exc:
        raise _map_governance_error(exc) from exc
    return _response(user)


@router.patch("/{user_id}/status", response_model=StatusUpdateResponse)
async def update_status(
    user_id: UUID = Path(...),
    body: UpdateStatusRequest = Body(...),
    _actor: ActorContext = Depends(require_users_manage),
    service: UserGovernanceService = Depends(get_governance_service),
) -> StatusUpdateResponse:
    try:
        user, revoked = await service.set_status(user_id, body.status)
    except (LastActiveAdminError, UserNotFoundError, ValueError) as exc:
        raise _map_governance_error(exc) from exc
    return StatusUpdateResponse(user=_response(user), revoked_sessions=revoked)


@router.patch("/{user_id}/role", response_model=UserResponse)
async def update_role(
    user_id: UUID = Path(...),
    body: UpdateRoleRequest = Body(...),
    _actor: ActorContext = Depends(require_users_manage),
    service: UserGovernanceService = Depends(get_governance_service),
) -> UserResponse:
    try:
        user = await service.set_role(user_id, body.platform_role)
    except (LastActiveAdminError, UserNotFoundError, ValueError) as exc:
        raise _map_governance_error(exc) from exc
    return _response(user)


@router.post("/{user_id}/revoke-sessions", response_model=RevokeSessionsResponse)
async def revoke_sessions(
    user_id: UUID = Path(...),
    _actor: ActorContext = Depends(require_users_manage),
    service: UserGovernanceService = Depends(get_governance_service),
) -> RevokeSessionsResponse:
    try:
        revoked = await service.revoke_sessions(user_id)
    except UserNotFoundError as exc:
        raise _map_governance_error(exc) from exc
    return RevokeSessionsResponse(revoked_sessions=revoked)


@router.patch("/{user_id}/profile", response_model=UserResponse)
async def update_profile(
    user_id: UUID = Path(...),
    body: ProfileUpdateRequest = Body(...),
    actor: ActorContext = Depends(require_users_manage),
    service: UserGovernanceService = Depends(get_governance_service),
    audit: UserAuditRepository = Depends(get_user_audit_repository),
) -> UserResponse:
    try:
        user = await service.update_profile(
            user_id,
            UserProfileUpdate(**body.model_dump()),
        )
    except (DuplicateUsernameError, UserNotFoundError, ValueError) as exc:
        raise _map_governance_error(exc) from exc
    await audit.record(
        actor=actor,
        target_user_id=user_id,
        action="admin.user.profile.update",
        changed_fields=list(body.model_fields_set),
    )
    return _response(user)


@router.post("/{user_id}/reset-password", response_model=RevokeSessionsResponse)
async def reset_password(
    user_id: UUID = Path(...),
    body: ResetPasswordRequest = Body(...),
    actor: ActorContext = Depends(require_users_manage),
    service: UserGovernanceService = Depends(get_governance_service),
    audit: UserAuditRepository = Depends(get_user_audit_repository),
) -> RevokeSessionsResponse:
    try:
        revoked = await service.reset_password(user_id, body.new_password)
    except (UserNotFoundError, ValueError) as exc:
        raise _map_governance_error(exc) from exc
    await audit.record(
        actor=actor,
        target_user_id=user_id,
        action="admin.user.password.reset",
        changed_fields=["password"],
    )
    return RevokeSessionsResponse(revoked_sessions=revoked)


@router.post("/{user_id}/unlock", response_model=UserResponse)
async def unlock_user(
    user_id: UUID = Path(...),
    actor: ActorContext = Depends(require_users_manage),
    service: UserGovernanceService = Depends(get_governance_service),
    audit: UserAuditRepository = Depends(get_user_audit_repository),
) -> UserResponse:
    """仅清除目标账户的临时登录锁，保留账户停用状态和网络防护。"""
    try:
        user = await service.get_user(user_id)
    except UserNotFoundError as exc:
        raise _map_governance_error(exc) from exc
    if user.status != "active":
        raise HTTPException(status_code=409, detail="user_disabled")
    # 审计失败时不执行解锁，避免出现无记录的权限操作。
    await audit.record(
        actor=actor,
        target_user_id=user_id,
        action="admin.user.login.unlock",
        changed_fields=["login_lock"],
    )
    rate_limiter.clear_user_failed_attempts(user.username)
    return _response(user)
