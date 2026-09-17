# -*- coding: utf-8 -*-
"""从可信认证状态构造统一请求主体。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from fastapi import Request

from ..identity.models import PlatformRole


class ActorType(StrEnum):
    """能够调用平台能力的主体类型。"""

    USER = "user"
    EXTERNAL = "external"
    SERVICE = "service"
    AUTOMATION = "automation"


@dataclass(frozen=True, slots=True)
class ActorContext:
    """一次请求中不可由客户端身份参数覆盖的主体。"""

    user_id: UUID | None
    actor_type: ActorType
    platform_role: PlatformRole | None
    admin_mode: bool
    request_id: str


def actor_from_request(
    request: Request,
    *,
    multi_user: bool,
) -> ActorContext | None:
    """只从中间件验证结果构造 Web 主体。"""
    request_id = request.headers.get("x-request-id", "").strip() or str(uuid4())
    if not multi_user:
        return ActorContext(
            user_id=None,
            actor_type=ActorType.USER,
            platform_role=PlatformRole.ADMIN,
            admin_mode=False,
            request_id=request_id,
        )

    authenticated = getattr(request.state, "authenticated_session", None)
    if authenticated is None:
        return None
    return ActorContext(
        user_id=authenticated.user.id,
        actor_type=ActorType.USER,
        platform_role=authenticated.user.platform_role,
        admin_mode=False,
        request_id=request_id,
    )
