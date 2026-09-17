# -*- coding: utf-8 -*-
"""当前用户在可使用 Agent 下的个人频道绑定 API。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from ...access.actor import ActorContext
from ...access.agent_repository import PostgresAgentRepository
from ...access.channel_bindings import (
    ChannelBindingDeniedError,
    ChannelBindingService,
    PostgresChannelBindingRepository,
)
from ...access.dependencies import get_actor, require_multi_user_mode
from ...identity.runtime import get_identity_schema
from ..channels.conflict import get_channel_bot_identity, get_channel_config
from ..channels.user_bindings import UserChannelBindingRuntimeRegistry

router = APIRouter(dependencies=[Depends(require_multi_user_mode)])

_BUILTIN_SECRET_FIELDS = frozenset(
    {
        "access_token",
        "api_key",
        "app_secret",
        "app_token",
        "bot_token",
        "client_secret",
        "dashscope_api_key",
        "encrypt_key",
        "livekit_api_key",
        "livekit_api_secret",
        "password",
        "rest_api_key",
        "secret",
        "sip_password",
        "token",
        "twilio_auth_token",
        "verification_token",
    }
)


class ChannelBindingUpsertRequest(BaseModel):
    display_name: str = ""
    enabled: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class ChannelBindingResponse(BaseModel):
    id: UUID
    channel_type: str
    display_name: str
    enabled: bool
    config: dict[str, Any]
    configured_secret_fields: list[str] = Field(default_factory=list)


class ChannelBindingDeleteResponse(BaseModel):
    success: bool = True


class ChannelBindingConfigRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class ChannelBindingConflictResponse(BaseModel):
    conflict: bool


def get_channel_binding_service() -> ChannelBindingService:
    schema = get_identity_schema()
    return ChannelBindingService(
        binding_repository=PostgresChannelBindingRepository(schema=schema),
        agent_repository=PostgresAgentRepository(schema=schema),
    )


def get_channel_binding_runtime(
    request: Request,
) -> UserChannelBindingRuntimeRegistry:
    runtime = getattr(
        request.app.state,
        "user_channel_binding_runtime",
        None,
    )
    if runtime is None:
        raise HTTPException(
            status_code=503,
            detail="channel_binding_runtime_unavailable",
        )
    return runtime


def _plugin_secret_fields(channel_type: str) -> set[str]:
    try:
        from ...plugins.registry import PluginRegistry

        registration = PluginRegistry().get_registered_channels().get(
            channel_type
        )
    except Exception:  # noqa: BLE001 - optional plugin metadata
        return set()
    if registration is None:
        return set()
    return {
        str(field.get("name"))
        for field in registration.config_fields
        if field.get("type") == "password" and field.get("name")
    }


def partition_channel_config(
    channel_type: str,
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """把普通配置与不可回读 Secret 分离；空 Secret 表示保留旧值。"""
    secret_fields = _BUILTIN_SECRET_FIELDS | _plugin_secret_fields(
        channel_type
    )
    public_config: dict[str, Any] = {}
    secrets: dict[str, str] = {}
    for key, value in config.items():
        if key in secret_fields:
            if value not in (None, ""):
                secrets[key] = str(value)
            continue
        public_config[key] = value
    return public_config, secrets


def _response(record) -> ChannelBindingResponse:
    return ChannelBindingResponse(
        id=record.id,
        channel_type=record.channel_type,
        display_name=record.display_name,
        enabled=record.enabled,
        config=record.config,
        configured_secret_fields=list(record.configured_secret_fields),
    )


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ChannelBindingDeniedError):
        return HTTPException(status_code=403, detail="forbidden")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


def _has_agent_channel_conflict(
    request: Request,
    *,
    channel_type: str,
    config: dict[str, Any],
) -> bool:
    """比较个人绑定与所有正在运行的 Agent 原频道。"""
    proposed = get_channel_bot_identity(channel_type, config)
    if proposed is None:
        return False
    manager = getattr(request.app.state, "multi_agent_manager", None)
    for workspace in getattr(manager, "agents", {}).values():
        channel_manager = getattr(workspace, "channel_manager", None)
        if not any(
            getattr(channel, "channel", None) == channel_type
            for channel in getattr(channel_manager, "channels", ())
        ):
            continue
        existing = get_channel_config(
            getattr(workspace.config, "channels", None),
            channel_type,
        )
        if get_channel_bot_identity(channel_type, existing) == proposed:
            return True
    return False


@router.get(
    "/agents/{agentId}/channel-bindings",
    response_model=list[ChannelBindingResponse],
    tags=["channel-bindings"],
)
async def list_user_channel_bindings(
    agentId: str = Path(...),
    actor: ActorContext = Depends(get_actor),
    service: ChannelBindingService = Depends(get_channel_binding_service),
) -> list[ChannelBindingResponse]:
    try:
        records = await service.list_bindings(
            actor=actor,
            agent_key=agentId,
        )
    except (ChannelBindingDeniedError, ValueError) as exc:
        raise _map_error(exc) from exc
    return [_response(record) for record in records]


@router.put(
    "/agents/{agentId}/channel-bindings/{channel_type}",
    response_model=ChannelBindingResponse,
    tags=["channel-bindings"],
)
async def put_user_channel_binding(
    agentId: str = Path(...),
    channel_type: str = Path(...),
    body: ChannelBindingUpsertRequest = Body(...),
    actor: ActorContext = Depends(get_actor),
    service: ChannelBindingService = Depends(get_channel_binding_service),
    runtime: UserChannelBindingRuntimeRegistry = Depends(
        get_channel_binding_runtime
    ),
) -> ChannelBindingResponse:
    public_config, secrets = partition_channel_config(
        channel_type,
        body.config,
    )
    try:
        record = await service.upsert(
            actor=actor,
            agent_key=agentId,
            channel_type=channel_type,
            display_name=body.display_name,
            enabled=body.enabled,
            config=public_config,
            secrets=secrets,
        )
    except (ChannelBindingDeniedError, ValueError) as exc:
        raise _map_error(exc) from exc
    await runtime.reconcile(record)
    return _response(record)


@router.post(
    "/agents/{agentId}/channel-bindings/{channel_type}/conflict-check",
    response_model=ChannelBindingConflictResponse,
    tags=["channel-bindings"],
)
async def check_user_channel_binding_conflict(
    request: Request,
    agentId: str = Path(...),
    channel_type: str = Path(...),
    body: ChannelBindingConfigRequest = Body(...),
    actor: ActorContext = Depends(get_actor),
    service: ChannelBindingService = Depends(get_channel_binding_service),
) -> ChannelBindingConflictResponse:
    try:
        conflict = await service.has_bot_conflict(
            actor=actor,
            agent_key=agentId,
            channel_type=channel_type,
            config=body.config,
        )
    except (ChannelBindingDeniedError, ValueError) as exc:
        raise _map_error(exc) from exc
    if not conflict:
        conflict = _has_agent_channel_conflict(
            request,
            channel_type=channel_type.strip().lower(),
            config=body.config,
        )
    return ChannelBindingConflictResponse(conflict=conflict)


@router.delete(
    "/agents/{agentId}/channel-bindings/{channel_type}",
    response_model=ChannelBindingDeleteResponse,
    tags=["channel-bindings"],
)
async def delete_user_channel_binding(
    agentId: str = Path(...),
    channel_type: str = Path(...),
    actor: ActorContext = Depends(get_actor),
    service: ChannelBindingService = Depends(get_channel_binding_service),
    runtime: UserChannelBindingRuntimeRegistry = Depends(
        get_channel_binding_runtime
    ),
) -> ChannelBindingDeleteResponse:
    try:
        records = await service.list_bindings(
            actor=actor,
            agent_key=agentId,
        )
        binding = next(
            (
                item
                for item in records
                if item.channel_type == channel_type.strip().lower()
            ),
            None,
        )
        deleted = await service.delete(
            actor=actor,
            agent_key=agentId,
            channel_type=channel_type,
        )
    except (ChannelBindingDeniedError, ValueError) as exc:
        raise _map_error(exc) from exc
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="channel_binding_not_found",
        )
    if binding is not None:
        await runtime.remove(binding.id)
    return ChannelBindingDeleteResponse()
