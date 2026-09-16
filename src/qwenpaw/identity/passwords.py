# -*- coding: utf-8 -*-
"""Argon2 密码哈希与旧 salted SHA-256 一次性升级。"""

from __future__ import annotations

import hashlib
import hmac

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from .models import LegacyAdminCredential


class PasswordManager:
    """封装当前密码算法及登录时自适应升级。"""

    LEGACY_SHA256_PREFIX = "legacy_salted_sha256$"

    def __init__(self, password_hash: PasswordHash | None = None) -> None:
        self._password_hash = password_hash or PasswordHash.recommended()

    def hash_password(self, password: str) -> str:
        """使用当前推荐 Argon2id 参数生成不可逆哈希。"""
        return self._password_hash.hash(password)

    def encode_legacy_sha256(
        self,
        credential: LegacyAdminCredential,
    ) -> str:
        """将旧 hash+salt 封装成仅供一次登录升级的内部格式。"""
        return (
            f"{self.LEGACY_SHA256_PREFIX}"
            f"{credential.password_salt}${credential.password_hash}"
        )

    def verify_and_update(
        self,
        password: str,
        stored_hash: str,
    ) -> tuple[bool, str | None]:
        """验证密码，并在算法或参数过期时返回新 Argon2id 哈希。"""
        if stored_hash.startswith(self.LEGACY_SHA256_PREFIX):
            return self._verify_legacy_and_update(password, stored_hash)
        try:
            return self._password_hash.verify_and_update(
                password,
                stored_hash,
            )
        except (UnknownHashError, ValueError):
            return False, None

    def _verify_legacy_and_update(
        self,
        password: str,
        stored_hash: str,
    ) -> tuple[bool, str | None]:
        encoded = stored_hash.removeprefix(self.LEGACY_SHA256_PREFIX)
        try:
            salt, expected_hash = encoded.split("$", 1)
        except ValueError:
            return False, None
        actual_hash = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        if not hmac.compare_digest(actual_hash, expected_hash):
            return False, None
        return True, self.hash_password(password)
