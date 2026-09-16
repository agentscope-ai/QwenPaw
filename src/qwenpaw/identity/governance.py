# -*- coding: utf-8 -*-
"""管理员用户治理领域服务。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .models import PlatformRole, UserProfileUpdate, UserRecord, UserStatus


class UserNotFoundError(RuntimeError):
    """目标用户不存在。"""

    def __init__(self) -> None:
        super().__init__("user_not_found")


class LastActiveAdminError(RuntimeError):
    """操作会移除最后一个可用管理员。"""

    def __init__(self) -> None:
        super().__init__("last_active_admin")


class GovernanceRepository(Protocol):
    async def list_users(self) -> list[UserRecord]: ...

    async def get_user(self, user_id: UUID) -> UserRecord: ...

    async def update_status(
        self,
        user_id: UUID,
        status: UserStatus,
    ) -> UserRecord: ...

    async def update_role(
        self,
        user_id: UUID,
        role: PlatformRole,
    ) -> UserRecord: ...


class UserCreationService(Protocol):
    async def create_user(
        self,
        username: str,
        password: str,
        platform_role: PlatformRole,
    ) -> UserRecord: ...

    async def update_profile(
        self,
        user_id: UUID,
        profile: UserProfileUpdate,
    ) -> UserRecord: ...

    async def reset_password(self, user_id: UUID, new_password: str) -> None: ...


class SessionRevocationService(Protocol):
    async def revoke_all(self, user_id: UUID) -> int: ...


class UserGovernanceService:
    """组合用户事实、密码创建和会话撤销。"""

    def __init__(
        self,
        *,
        repository: GovernanceRepository,
        user_service: UserCreationService,
        session_service: SessionRevocationService,
    ) -> None:
        self._repository = repository
        self._users = user_service
        self._sessions = session_service

    async def list_users(self) -> list[UserRecord]:
        return await self._repository.list_users()

    async def create_user(
        self,
        username: str,
        password: str,
        platform_role: PlatformRole,
    ) -> UserRecord:
        return await self._users.create_user(username, password, platform_role)

    async def set_status(
        self,
        user_id: UUID,
        status: UserStatus,
    ) -> tuple[UserRecord, int]:
        updated = await self._repository.update_status(user_id, status)
        revoked = 0
        if status == "disabled":
            revoked = await self._sessions.revoke_all(user_id)
        return updated, revoked

    async def set_role(
        self,
        user_id: UUID,
        role: PlatformRole,
    ) -> UserRecord:
        return await self._repository.update_role(user_id, role)

    async def update_profile(
        self,
        user_id: UUID,
        profile: UserProfileUpdate,
    ) -> UserRecord:
        await self._repository.get_user(user_id)
        return await self._users.update_profile(user_id, profile)

    async def reset_password(self, user_id: UUID, new_password: str) -> int:
        await self._repository.get_user(user_id)
        await self._users.reset_password(user_id, new_password)
        return await self._sessions.revoke_all(user_id)

    async def revoke_sessions(self, user_id: UUID) -> int:
        await self._repository.get_user(user_id)
        return await self._sessions.revoke_all(user_id)
