"""企业默认开启鉴权。"""

from __future__ import annotations

from dataclasses import dataclass

from airport_sms.domain.roles import Role
from airport_sms.session.principal import Principal


class AuthError(Exception):
    """未认证。"""


@dataclass
class TokenStore:
    """内存令牌表。"""

    tokens: dict[str, Principal]

    def __init__(self) -> None:
        self.tokens = {
            "reporter-token": Principal(
                "rep1", "org-a", Role.REPORTER, "site-1"
            ),
            "safety-token": Principal(
                "so1", "org-a", Role.SAFETY_OFFICE, "site-1"
            ),
        }

    def resolve(self, authorization: str | None) -> Principal:
        """解析 Bearer。缺省拒绝。"""
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthError("missing bearer")
        token = authorization.removeprefix("Bearer ").strip()
        principal = self.tokens.get(token)
        if principal is None:
            raise AuthError("invalid token")
        return principal


__all__ = ["AuthError", "TokenStore"]
