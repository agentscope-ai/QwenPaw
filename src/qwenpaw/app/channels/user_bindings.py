# -*- coding: utf-8 -*-
"""个人频道绑定的独立运行时，不复用或覆盖 Agent ChannelManager。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import UUID

from ...config import update_last_dispatch

_EXTERNAL_IDENTITY_METADATA_FIELDS = frozenset(
    {
        "channel_id",
        "chat_id",
        "conversation_id",
        "display_name",
        "guild_id",
        "group_id",
        "is_group",
        "team_id",
        "thread_ts",
        "user_name",
        "username",
    }
)


def bind_process_identity(
    process,
    *,
    owner_user_id: UUID,
    binding_id: UUID,
    record_external_identity: Callable[..., Awaitable[None]] | None = None,
):
    """将外部发送者映射为绑定所有者，同时保留外部身份元数据。"""
    platform_user_id = str(owner_user_id)
    binding_key = str(binding_id)

    async def bound_process(request) -> AsyncIterator[Any]:
        external_user_id = str(getattr(request, "user_id", "") or "")
        channel_meta = dict(getattr(request, "channel_meta", None) or {})
        if external_user_id and record_external_identity is not None:
            metadata = {
                key: value
                for key, value in channel_meta.items()
                if key in _EXTERNAL_IDENTITY_METADATA_FIELDS
            }
            metadata.update(
                channel=str(getattr(request, "channel", "") or ""),
                session_id=str(
                    getattr(request, "session_id", "") or ""
                ),
            )
            try:
                json.dumps(metadata)
            except (TypeError, ValueError):
                metadata = {
                    key: str(value)
                    for key, value in metadata.items()
                    if value is not None
                }
            await record_external_identity(
                binding_id=binding_id,
                external_subject_id=external_user_id[:512],
                platform_user_id=owner_user_id,
                metadata=metadata,
            )
        if external_user_id:
            channel_meta["external_user_id"] = external_user_id
        channel_meta["channel_binding_id"] = binding_key
        request.channel_meta = channel_meta
        request.user_id = platform_user_id
        request._trusted_channel_user_id = owner_user_id
        request_context = dict(
            getattr(request, "request_context", None) or {}
        )
        request_context["user_id"] = platform_user_id
        request_context["channel_binding_id"] = binding_key
        request_context["actor_context"] = {
            "user_id": platform_user_id,
            "actor_type": "external",
            "admin_mode": False,
        }
        request.request_context = request_context
        async for event in process(request):
            yield event

    return bound_process


def _build_channel_manager(
    *,
    workspace,
    binding_repository,
    channel_type: str,
    config: dict[str, Any],
    owner_user_id: UUID,
    binding_id: UUID,
):
    from ...config import Config, load_config
    from .manager import ChannelManager

    process = bind_process_identity(
        workspace.stream_query,
        owner_user_id=owner_user_id,
        binding_id=binding_id,
        record_external_identity=(
            binding_repository.upsert_external_identity
        ),
    )
    root_config = load_config()
    def on_last_dispatch(channel, user_id, session_id):
        update_last_dispatch(
            channel=channel,
            user_id=user_id,
            session_id=session_id,
            agent_id=workspace.agent_id,
            platform_user_id=str(owner_user_id),
            binding_id=str(binding_id),
        )

    manager = ChannelManager.from_config(
        process=process,
        config=Config(
            channels={channel_type: config},
            show_tool_details=root_config.show_tool_details,
        ),
        on_last_dispatch=on_last_dispatch,
        workspace_dir=workspace.workspace_dir,
    )
    manager.set_workspace(workspace)
    language = getattr(workspace._config, "language", "zh") or "zh"
    for channel in manager.channels:
        channel._language = language
    return manager


ManagerFactory = Callable[..., Any]


class UserChannelBindingRuntimeRegistry:
    """按 binding_id 管理个人频道监听器的启动、替换和停止。"""

    def __init__(
        self,
        *,
        workspace_manager,
        binding_repository,
        manager_factory: ManagerFactory = _build_channel_manager,
    ) -> None:
        self._workspace_manager = workspace_manager
        self._binding_repository = binding_repository
        self._manager_factory = manager_factory
        self._managers: dict[UUID, Any] = {}
        self._locks: dict[UUID, asyncio.Lock] = {}

    async def _stop(self, binding_id: UUID) -> None:
        manager = self._managers.pop(binding_id, None)
        if manager is not None:
            await manager.stop_all()

    async def reconcile(self, record) -> None:
        lock = self._locks.setdefault(record.id, asyncio.Lock())
        async with lock:
            await self._stop(record.id)
            if not record.enabled:
                return
            runtime_config = await self._binding_repository.get_runtime_config(
                binding_id=record.id,
                owner_user_id=record.owner_user_id,
            )
            if runtime_config is None:
                return
            workspace = await self._workspace_manager.get_agent(
                record.agent_key
            )
            if workspace is None:
                raise ValueError("agent_workspace_not_found")
            manager = self._manager_factory(
                workspace=workspace,
                binding_repository=self._binding_repository,
                channel_type=record.channel_type,
                config={**runtime_config, "enabled": True},
                owner_user_id=record.owner_user_id,
                binding_id=record.id,
            )
            try:
                await manager.start_all()
            except Exception:
                await manager.stop_all()
                raise
            self._managers[record.id] = manager

    async def remove(self, binding_id: UUID) -> None:
        lock = self._locks.setdefault(binding_id, asyncio.Lock())
        async with lock:
            await self._stop(binding_id)

    async def stop_all(self) -> None:
        for binding_id in list(self._managers):
            await self.remove(binding_id)
