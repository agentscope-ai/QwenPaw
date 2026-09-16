# -*- coding: utf-8 -*-
"""公共/私有 ReMe 运行时的隔离缓存池。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from ...access.actor import ActorContext, ActorType
from ...constant import WORKING_DIR
from ...identity.models import PlatformRole
from ...memory_scope.models import MemoryScope
from ...memory_scope.resolver import MemoryScopeResolver

RuntimeFactory = Callable[[MemoryScope, UUID | None, str, Path], Awaitable[Any]]
WorkspaceRegistrar = Callable[[UUID, str, str], Awaitable[None]]


class ScopedMemoryRuntimePool:
    """按作用域身份缓存运行时，禁止跨用户复用私有实例。"""

    def __init__(
        self,
        *,
        factory: RuntimeFactory,
        registrar: WorkspaceRegistrar | None = None,
        working_dir: Path = WORKING_DIR,
    ) -> None:
        self._factory = factory
        self._registrar = registrar
        self._working_dir = working_dir.resolve()
        self._resolver = MemoryScopeResolver(working_dir=working_dir)
        self._runtimes: dict[tuple[str, ...], Any] = {}
        self._lock = asyncio.Lock()

    async def get_public(self, *, agent_id: str) -> Any:
        key = (MemoryScope.PUBLIC.value, agent_id)
        actor = self._actor(None)
        context = self._resolver.resolve_public(actor=actor, agent_id=agent_id)
        return await self._get_or_create(
            key=key,
            scope=MemoryScope.PUBLIC,
            user_id=None,
            agent_id=agent_id,
            workspace=self._resolver.ensure_workspace(context),
        )

    async def get_private(self, *, user_id: UUID, agent_id: str) -> Any:
        key = (MemoryScope.PRIVATE.value, str(user_id), agent_id)
        context = self._resolver.resolve_private(
            actor=self._actor(user_id),
            agent_id=agent_id,
        )
        return await self._get_or_create(
            key=key,
            scope=MemoryScope.PRIVATE,
            user_id=user_id,
            agent_id=agent_id,
            workspace=self._resolver.ensure_workspace(context),
        )

    async def close_user(self, *, user_id: UUID) -> None:
        prefix = (MemoryScope.PRIVATE.value, str(user_id))
        async with self._lock:
            matches = [
                (key, runtime)
                for key, runtime in self._runtimes.items()
                if key[:2] == prefix
            ]
            for key, _runtime in matches:
                self._runtimes.pop(key, None)
        for _key, runtime in matches:
            await self._close_runtime(runtime)

    async def close(self) -> None:
        async with self._lock:
            runtimes = list(self._runtimes.values())
            self._runtimes.clear()
        for runtime in runtimes:
            await self._close_runtime(runtime)

    async def _get_or_create(
        self,
        *,
        key: tuple[str, ...],
        scope: MemoryScope,
        user_id: UUID | None,
        agent_id: str,
        workspace: Path,
    ) -> Any:
        async with self._lock:
            runtime = self._runtimes.get(key)
            if runtime is None:
                if self._registrar is not None and user_id is not None:
                    await self._registrar(
                        user_id,
                        agent_id,
                        workspace.relative_to(self._working_dir).as_posix(),
                    )
                runtime = await self._factory(
                    scope,
                    user_id,
                    agent_id,
                    workspace,
                )
                self._runtimes[key] = runtime
            return runtime

    @staticmethod
    async def _close_runtime(runtime: Any) -> None:
        close = getattr(runtime, "close", None)
        if callable(close):
            await close()

    @staticmethod
    def _actor(user_id: UUID | None) -> ActorContext:
        return ActorContext(
            user_id=user_id,
            actor_type=ActorType.SERVICE,
            platform_role=(PlatformRole.MEMBER if user_id else None),
            admin_mode=False,
            request_id="memory-runtime-pool",
        )
