# -*- coding: utf-8 -*-
"""用户身份领域模型。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

_SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
_SALT_HEX = re.compile(r"^[0-9a-fA-F]{32}$")


class PlatformRole(StrEnum):
    """第一阶段平台角色。"""

    ADMIN = "admin"
    MEMBER = "member"


UserStatus = Literal["active", "disabled"]


@dataclass(frozen=True, slots=True)
class UserRecord:
    """不包含密码凭据的公开用户记录。"""

    id: UUID
    username: str
    platform_role: PlatformRole
    status: UserStatus
    display_name: str | None = None
    email: str | None = None
    phone: str | None = None
    department: str | None = None
    job_title: str | None = None
    remark: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_login_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class UserProfileUpdate:
    """用户名和企业基础资料更新。"""

    username: str
    display_name: str | None = None
    email: str | None = None
    phone: str | None = None
    department: str | None = None
    job_title: str | None = None
    remark: str | None = None


@dataclass(frozen=True, slots=True)
class CredentialRecord:
    """Repository 与认证服务之间使用的内部凭据记录。"""

    user: UserRecord
    password_hash: str


@dataclass(frozen=True, slots=True)
class LegacyAdminCredential:
    """从旧 auth.json 提取的一次性管理员迁移凭据。"""

    username: str
    password_hash: str
    password_salt: str

    @classmethod
    def from_auth_data(
        cls,
        auth_data: object,
    ) -> LegacyAdminCredential | None:
        """只读取旧单用户凭据，不迁移令牌或 JWT Secret。"""
        if not isinstance(auth_data, dict):
            return None
        user = auth_data.get("user")
        if not isinstance(user, dict):
            return None
        username = user.get("username")
        password_hash = user.get("password_hash")
        password_salt = user.get("password_salt")
        if not all(
            isinstance(value, str) for value in (username, password_hash, password_salt)
        ):
            return None
        normalized_username = username.strip()
        if not normalized_username:
            return None
        if not _SHA256_HEX.fullmatch(password_hash):
            return None
        if not _SALT_HEX.fullmatch(password_salt):
            return None
        return cls(
            username=normalized_username,
            password_hash=password_hash.lower(),
            password_salt=password_salt.lower(),
        )
