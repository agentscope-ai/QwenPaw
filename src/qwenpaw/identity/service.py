# -*- coding: utf-8 -*-
"""用户创建、旧管理员迁移与密码认证服务。"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from .governance import UserNotFoundError
from .models import (
    LegacyAdminCredential,
    PlatformRole,
    UserProfileUpdate,
    UserRecord,
)
from .passwords import PasswordManager
from .repository import UserRepository

logger = logging.getLogger(__name__)


class SelfRegistrationDisabledError(RuntimeError):
    """平台默认不允许未认证主体自行注册。"""

    def __init__(self) -> None:
        super().__init__("self_registration_disabled")


class CurrentPasswordIncorrectError(RuntimeError):
    """当前密码校验失败。"""

    def __init__(self) -> None:
        super().__init__("current_password_incorrect")


class UserService:
    """不包含令牌与 HTTP 逻辑的用户身份领域服务。"""

    def __init__(
        self,
        repository: UserRepository,
        password_manager: PasswordManager | None = None,
        *,
        self_registration_enabled: bool = False,
    ) -> None:
        self._repository = repository
        self._passwords = password_manager or PasswordManager()
        self._self_registration_enabled = self_registration_enabled

    async def has_users(self) -> bool:
        """返回身份库是否已经存在首个用户。"""
        return await self._repository.count_users() > 0

    async def create_user(
        self,
        username: str,
        password: str,
        platform_role: PlatformRole,
    ) -> UserRecord:
        """创建用户；首个用户无条件成为管理员。"""
        normalized_username = _normalize_username(username)
        if not password:
            raise ValueError("password_required")
        credential = await self._repository.create_credential(
            username=normalized_username,
            password_hash=self._passwords.hash_password(password),
            platform_role=PlatformRole(platform_role),
        )
        logger.info(
            "Created platform user id=%s username=%s role=%s",
            credential.user.id,
            credential.user.username,
            credential.user.platform_role,
        )
        return credential.user

    async def authenticate(
        self,
        username: str,
        password: str,
    ) -> UserRecord | None:
        """验证 active 用户，并在成功登录时升级旧哈希。"""
        normalized_username = username.strip()
        if not normalized_username:
            return None
        credential = await self._repository.get_credential_by_username(
            normalized_username
        )
        if credential is None or credential.user.status != "active":
            return None
        valid, updated_hash = self._passwords.verify_and_update(
            password,
            credential.password_hash,
        )
        if not valid:
            return None
        if updated_hash is not None:
            await self._repository.update_password_hash(
                credential.user.id,
                updated_hash,
            )
        await self._repository.mark_login(credential.user.id)
        logger.info(
            "Authenticated platform user id=%s username=%s",
            credential.user.id,
            credential.user.username,
        )
        return credential.user

    async def update_profile(
        self,
        user_id: UUID,
        profile: UserProfileUpdate,
    ) -> UserRecord:
        """规范化并更新公开账户资料。"""
        return await self._repository.update_profile(
            user_id,
            _normalize_profile(profile),
        )

    async def change_password(
        self,
        user_id: UUID,
        current_password: str,
        new_password: str,
    ) -> None:
        """验证当前密码后替换密码哈希。"""
        credential = await self._repository.get_credential_by_user_id(user_id)
        if credential is None:
            raise UserNotFoundError()
        valid, _updated_hash = self._passwords.verify_and_update(
            current_password,
            credential.password_hash,
        )
        if not valid:
            raise CurrentPasswordIncorrectError()
        await self.reset_password(user_id, new_password)

    async def reset_password(self, user_id: UUID, new_password: str) -> None:
        """由已授权调用方直接设置新密码。"""
        if not new_password:
            raise ValueError("password_required")
        credential = await self._repository.get_credential_by_user_id(user_id)
        if credential is None:
            raise UserNotFoundError()
        await self._repository.update_password_hash(
            user_id,
            self._passwords.hash_password(new_password),
        )

    async def migrate_legacy_admin(
        self,
        legacy: LegacyAdminCredential,
    ) -> UserRecord | None:
        """仅在空用户库中导入旧 auth.json 的单一管理员。"""
        credential = await self._repository.create_legacy_admin_if_empty(
            username=_normalize_username(legacy.username),
            password_hash=self._passwords.encode_legacy_sha256(legacy),
        )
        if credential is None:
            return None
        logger.info(
            "Migrated legacy administrator id=%s username=%s",
            credential.user.id,
            credential.user.username,
        )
        return credential.user

    async def self_register(
        self,
        username: str,
        password: str,
    ) -> UserRecord:
        """显式开关开启前拒绝自助注册。"""
        if not self._self_registration_enabled:
            raise SelfRegistrationDisabledError()
        return await self.create_user(
            username,
            password,
            PlatformRole.MEMBER,
        )


def _normalize_username(username: str) -> str:
    normalized = username.strip()
    if not normalized:
        raise ValueError("username_required")
    return normalized


_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE_PATTERN = re.compile(r"^[0-9+()\-\s]+$")


def _optional_text(value: str | None, *, maximum: int, error: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise ValueError(error)
    return normalized


def _normalize_profile(profile: UserProfileUpdate) -> UserProfileUpdate:
    username = _normalize_username(profile.username)
    if len(username) > 128:
        raise ValueError("username_too_long")
    email = _optional_text(profile.email, maximum=254, error="email_too_long")
    if email is not None:
        email = email.lower()
        if not _EMAIL_PATTERN.fullmatch(email):
            raise ValueError("invalid_email")
    phone = _optional_text(profile.phone, maximum=32, error="phone_too_long")
    if phone is not None and not _PHONE_PATTERN.fullmatch(phone):
        raise ValueError("invalid_phone")
    return UserProfileUpdate(
        username=username,
        display_name=_optional_text(
            profile.display_name, maximum=128, error="display_name_too_long"
        ),
        email=email,
        phone=phone,
        department=_optional_text(
            profile.department, maximum=128, error="department_too_long"
        ),
        job_title=_optional_text(
            profile.job_title, maximum=128, error="job_title_too_long"
        ),
        remark=_optional_text(profile.remark, maximum=500, error="remark_too_long"),
    )
