"""同一 Console 运行内的子任务委托。身份仅在进程内传递。"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from uuid import UUID

import httpx
from starlette.types import ASGIApp

from ..identity.sessions import AuthenticatedSession


def is_terminal_response(event) -> bool:
    return isinstance(event, dict) and event.get("object") == "response" and event.get("status") in {
        "completed", "failed", "cancelled", "canceled",
    }


@dataclass(frozen=True)
class ConsoleDelegation:
    app: ASGIApp
    session_id: UUID
    user_id: UUID
    agent_id: str
    conversation_id: str
    tools: tuple[str, ...] | None = None
    skills: tuple[str, ...] | None = None
    model: dict | None = None
    dispatch_denied: asyncio.Event = field(default_factory=asyncio.Event, compare=False)
    is_subtask: bool = False
    target_agent_id: str | None = None
    root_session_id: str | None = None
    session_handle: str | None = None

    @property
    def destination(self) -> str:
        return self.target_agent_id or self.agent_id

    def for_target(self, target: str, *, session_handle: str) -> ConsoleDelegation:
        """只允许父运行指定新的目标，子运行保持已核准的目标。"""
        if target == self.destination:
            return replace(self, session_handle=session_handle)
        if self.is_subtask:
            raise PermissionError("跨智能体子任务不能再次向其他智能体委托。")
        return replace(self, target_agent_id=target, model=None, session_handle=session_handle)

    async def call(self, method, path, *, payload=None, timeout=30):
        if payload is not None:
            if self.dispatch_denied.is_set():
                raise PermissionError("子任务未获授权，本轮已停止派发，无需再次确认样稿。")
            child = dict(payload.get("request_context") or {})
            for field, limit in (("subagent_allowed_tools", self.tools), ("subagent_skills", self.skills)):
                if limit is not None:
                    requested = child.get(field)
                    child[field] = [v for v in limit if requested is None or v in requested]
            payload = {**payload, "request_context": child}
        # 使用当前 ASGI 应用的完整鉴权、维护和路由栈，不把用户凭据发往网络。
        async def application(scope, receive, send):
            await self.app({**scope, "qwenpaw.subtask": self}, receive, send)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://console.internal",
            headers={"X-Agent-Id": self.destination},
        ) as client, asyncio.timeout(timeout):
            response = await client.request(method, path, json=payload)
            if payload is not None and (response.status_code == 401 or (
                response.status_code == 403 and self.target_agent_id is None
            )):
                self.dispatch_denied.set()
            response.raise_for_status()
            return response


current_delegation: ContextVar[ConsoleDelegation | None] = ContextVar(
    "console_subtask_delegation", default=None,
)


def bind_console_stream(request, workspace, chat, stream):
    authenticated = getattr(getattr(request, "state", None), "authenticated_session", None)
    if not isinstance(authenticated, AuthenticatedSession):
        return stream
    parent = request.scope.get("qwenpaw.subtask")
    delegation = parent or ConsoleDelegation(
        request.app, authenticated.session.id, authenticated.user.id,
        workspace.agent_id, str(chat.id), root_session_id=getattr(chat, "session_id", None),
    )

    async def bound(payload):
        rc = payload.get("meta", {}).get("request_context") or {}
        limits = {}
        for field, key in (("tools", "subagent_allowed_tools"), ("skills", "subagent_skills")):
            if isinstance(rc.get(key), list):
                limits[field] = tuple(rc[key])
        token = current_delegation.set(replace(
            delegation, model=payload.get("model_slot_override"), is_subtask=parent is not None,
            session_handle=None, **limits,
        ))
        try:
            async for event in stream(payload):
                yield event
        finally:
            current_delegation.reset(token)

    return bound
