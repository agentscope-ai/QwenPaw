# -*- coding: utf-8 -*-
"""公共与当前用户私有记忆的合并检索。"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from ...memory_scope.models import MemoryScope

SearchCallable = Callable[[str, int], Awaitable[Iterable[dict[str, Any]]]]


@dataclass(frozen=True, slots=True)
class ScopedMemorySearchItem:
    scope: MemoryScope
    scope_label: str
    path: str
    line: int | None
    text: str
    score: float


class MemorySearchMergeResult(list[ScopedMemorySearchItem]):
    """合并命中及各作用域的局部失败状态。"""

    def __init__(
        self,
        items: Iterable[ScopedMemorySearchItem],
        *,
        public_error: str | None = None,
        private_error: str | None = None,
    ) -> None:
        super().__init__(items)
        self.public_error = public_error
        self.private_error = private_error


class ScopedMemoryManagerView:
    """把一次可信请求身份绑定到共享的 Agent 记忆服务。"""

    def __init__(
        self,
        manager: Any,
        request_context: dict[str, Any],
        *,
        model_authority: Any = None,
        scoped: bool = True,
    ) -> None:
        self._manager = manager
        self._request_context = dict(request_context)
        self.agent_id = manager.agent_id
        self._model_authority = model_authority
        self._scoped = scoped

    def get_memory_prompt(self) -> str:
        return self._manager.get_memory_prompt()

    def get_memory_config(self) -> Any:
        return self._manager.get_memory_config()

    def get_auto_memory_interval(self) -> int:
        return self._manager.get_auto_memory_interval()

    def list_memory_tools(self) -> list[Callable[..., Any]]:
        if not self.get_memory_config().memory_search_enabled:
            return []
        return [self.memory_search]

    def build_middlewares(self) -> list[Any]:
        from ..middlewares import MemoryMiddleware

        return [MemoryMiddleware(memory_manager=self)]

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0,
    ) -> Any:
        if not self._scoped:
            return await self._manager.memory_search(query, max_results, min_score)
        return await self._manager.scoped_memory_search(
            query=query,
            max_results=max_results,
            min_score=min_score,
            actor_user_id=self._request_context.get("user_id"),
        )

    async def auto_memory_search(self, messages: Any, **kwargs: Any) -> Any:
        if not self._scoped:
            return await self._manager.auto_memory_search(messages, **kwargs)
        kwargs.pop("actor_user_id", None)
        return await self._manager.scoped_auto_memory_search(
            messages=messages,
            actor_user_id=self._request_context.get("user_id"),
            **kwargs,
        )

    async def auto_memory(self, messages: Any, **kwargs: Any) -> Any:
        kwargs["_model_authority"] = self._model_authority
        if not self._scoped:
            return await self._manager.auto_memory(messages, **kwargs)
        kwargs.pop("actor_user_id", None)
        return await self._manager.scoped_auto_memory(
            messages=messages,
            actor_user_id=self._request_context.get("user_id"),
            **kwargs,
        )

    async def dream(self, **kwargs: Any) -> Any:
        kwargs["_model_authority"] = self._model_authority
        if not self._scoped:
            return await self._manager.dream(**kwargs)
        kwargs.pop("actor_user_id", None)
        return await self._manager.scoped_dream(
            actor_user_id=self._request_context.get("user_id"),
            **kwargs,
        )


async def merge_memory_search_results(
    *,
    public_search: SearchCallable,
    private_search: SearchCallable,
    query: str,
    max_results: int,
) -> MemorySearchMergeResult:
    """并行检索两个作用域，局部失败时仍返回另一侧结果。"""
    limit = max(1, max_results)
    public_result, private_result = await asyncio.gather(
        public_search(query, limit),
        private_search(query, limit),
        return_exceptions=True,
    )
    public_error = _error_text(public_result)
    private_error = _error_text(private_result)
    items = [
        *_normalize(public_result, MemoryScope.PUBLIC),
        *_normalize(private_result, MemoryScope.PRIVATE),
    ]
    deduplicated: dict[tuple[str, str, int | None, str], ScopedMemorySearchItem] = {}
    for item in items:
        content_hash = hashlib.sha256(item.text.encode("utf-8")).hexdigest()
        key = (item.scope.value, item.path, item.line, content_hash)
        previous = deduplicated.get(key)
        if previous is None or item.score > previous.score:
            deduplicated[key] = item
    ordered = sorted(
        deduplicated.values(),
        key=lambda item: item.score,
        reverse=True,
    )[:limit]
    return MemorySearchMergeResult(
        ordered,
        public_error=public_error,
        private_error=private_error,
    )


def _normalize(
    result: Iterable[dict[str, Any]] | BaseException,
    scope: MemoryScope,
) -> list[ScopedMemorySearchItem]:
    if isinstance(result, BaseException):
        return []
    label = "public_memory" if scope is MemoryScope.PUBLIC else "my_memory"
    normalized: list[ScopedMemorySearchItem] = []
    for raw in result:
        normalized.append(
            ScopedMemorySearchItem(
                scope=scope,
                scope_label=label,
                path=str(raw.get("path") or ""),
                line=_optional_int(raw.get("line")),
                text=str(raw.get("text") or ""),
                score=float(raw.get("score") or 0.0),
            )
        )
    return normalized


def _error_text(result: object) -> str | None:
    return str(result) if isinstance(result, BaseException) else None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
