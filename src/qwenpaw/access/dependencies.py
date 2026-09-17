# -*- coding: utf-8 -*-
"""FastAPI 请求主体与 capability 依赖。"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from ..identity.runtime import is_multi_user_enabled
from .actor import ActorContext, actor_from_request
from .capabilities import Capability
from .service import AuthorizationDeniedError, AuthorizationService


def get_actor(request: Request) -> ActorContext:
    actor = getattr(request.state, "actor", None)
    if actor is None:
        actor = actor_from_request(
            request,
            multi_user=is_multi_user_enabled(),
        )
    if actor is None:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return actor


def require_multi_user_mode() -> None:
    if not is_multi_user_enabled():
        raise HTTPException(status_code=404, detail="multi_user_not_enabled")


def require_users_manage(
    actor: ActorContext = Depends(get_actor),
) -> ActorContext:
    try:
        AuthorizationService().require(actor, Capability.USERS_MANAGE)
    except AuthorizationDeniedError as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc
    return actor


def require_platform_settings_manage(
    actor: ActorContext = Depends(get_actor),
) -> ActorContext:
    """仅允许平台管理员读写部署级设置。"""
    try:
        AuthorizationService().require(
            actor,
            Capability.PLATFORM_SETTINGS_MANAGE,
        )
    except AuthorizationDeniedError as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc
    return actor


def require_plugins_manage(
    actor: ActorContext = Depends(get_actor),
) -> ActorContext:
    """仅允许平台管理员进入插件全局治理接口。"""
    try:
        AuthorizationService().require(actor, Capability.PLUGINS_MANAGE)
    except AuthorizationDeniedError as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc
    return actor
