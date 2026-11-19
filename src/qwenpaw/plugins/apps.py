# -*- coding: utf-8 -*-
"""PawApp declarations and scoped services available to app authors."""

from dataclasses import dataclass, field
from contextlib import AbstractAsyncContextManager
from typing import (
    Any,
    AsyncIterator,
    AsyncGenerator,
    Awaitable,
    Callable,
    Mapping,
    TYPE_CHECKING,
    Union,
)

from .events import ChatEvent, StreamMessage, ApprovalSnapshot
from .tools import ToolContext

if TYPE_CHECKING:
    from .sdk import PluginContext
    from .resources import Registration


JSONBody = Union[
    None,
    bool,
    int,
    float,
    str,
    list["JSONBody"],
    tuple["JSONBody", ...],
    dict[str, "JSONBody"],
]


@dataclass(frozen=True)
class ChatRequest:
    text: str
    session_id: str | None = None
    skill: str | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class ChatReply:
    events: tuple[ChatEvent, ...]

    @property
    def text(self) -> str:
        # Prefer completed messages so streamed deltas are not counted twice.
        messages = [
            message for event in self.events for message in event.output
        ]
        if messages:
            return "".join(
                block.text
                for message in messages
                for block in message.content
                if block.type == "text"
            )
        completed = [
            event
            for event in self.events
            if event.object == "message" and event.status == "completed"
        ]
        source = completed or [
            event for event in self.events if event.object == "content"
        ]
        return "".join(
            block.text
            for event in source
            for block in event.content
            if block.type == "text"
        )


@dataclass(frozen=True)
class SessionSummary:
    id: str
    session_id: str
    name: str
    created_at: str
    updated_at: str
    archived: bool
    pinned: bool


@dataclass(frozen=True)
class WorkspaceSummary:
    id: str
    name: str
    enabled: bool


@dataclass(frozen=True)
class TaskSnapshot:
    run_id: str
    session_id: str
    workspace_id: str
    app_id: str
    status: str
    error: str = ""
    result: str = ""
    result_truncated: bool = False


@dataclass(frozen=True)
class CancelResult:
    requested: bool
    stopped: bool
    timed_out: bool = False


@dataclass(frozen=True)
class HttpRequest:
    method: str
    path: str
    path_params: Mapping[str, str]
    query: Mapping[str, str]
    headers: Mapping[str, str]
    body: bytes = b""

    def json(self) -> JSONBody:
        import json

        return json.loads(self.body)


@dataclass(frozen=True)
class HttpResponse:
    body: JSONBody | bytes = None
    status: int = 200
    headers: Mapping[str, str] = field(default_factory=dict)
    media_type: str | None = None


@dataclass(frozen=True)
class StreamingResponse:
    stream: AsyncIterator[str | bytes]
    status: int = 200
    headers: Mapping[str, str] = field(default_factory=dict)
    media_type: str = "text/event-stream"


@dataclass(frozen=True)
class AppContext(ToolContext):
    app_id: str = ""
    user_id: str = ""
    channel: str = "console"
    _services: Any = field(default=None, repr=False, compare=False)

    async def workspaces(self) -> tuple[WorkspaceSummary, ...]:
        """Configured console workspaces, without host paths or credentials."""
        return await self._services.workspaces()

    def for_workspace(
        self,
        workspace_id: str,
    ) -> AbstractAsyncContextManager["AppContext"]:
        """Open an owned call with the same app and authenticated identity.

        Only configured, enabled targets are accepted. A plugin-owned
        background task may retain this identity delegation; each entry
        rechecks availability and derives cancellation and resources from
        the task entering the scope.
        """
        return self._services.for_workspace(workspace_id)

    def chat_stream(
        self,
        request: ChatRequest | str,
    ) -> AsyncGenerator[ChatEvent, None]:
        return self._services.chat_stream(request)

    async def chat(self, request: ChatRequest | str) -> ChatReply:
        stream = self.chat_stream(request)
        try:
            events = [event async for event in stream]
            return ChatReply(tuple(events))
        finally:
            await stream.aclose()

    async def sessions(self) -> tuple[SessionSummary, ...]:
        return await self._services.sessions()

    async def create_session(self, *, name="New analysis") -> SessionSummary:
        return await self._services.create_session(name)

    async def rename_session(self, chat_id: str, name: str) -> SessionSummary:
        return await self._services.rename_session(chat_id, name)

    async def archive_session(self, chat_id: str) -> bool:
        return await self._services.archive_session(chat_id)

    async def pin_session(self, chat_id: str, pinned: bool) -> SessionSummary:
        return await self._services.pin_session(chat_id, pinned)

    async def delete_session(self, chat_id: str) -> bool:
        return await self._services.delete_session(chat_id)

    async def history(
        self,
        session_id: str | None = None,
    ) -> tuple[StreamMessage, ...]:
        return await self._services.history(session_id)

    async def start_task(self, request: ChatRequest | str) -> TaskSnapshot:
        return await self._services.start_task(request)

    async def task(self, run_id: str) -> TaskSnapshot:
        return await self._services.task(run_id)

    def task_stream(self, run_id: str) -> AsyncGenerator[TaskSnapshot, None]:
        """
        Current status and changes until terminal; disconnect leaves the run
        alive.
        """
        return self._services.task_stream(run_id)

    async def cancel_task(self, run_id: str, *, timeout=5.0) -> CancelResult:
        return await self._services.cancel_task(run_id, timeout)

    async def approvals(self, session_id: str) -> tuple[ApprovalSnapshot, ...]:
        return await self._services.approvals(session_id)

    async def resolve_approval(
        self,
        request_id: str,
        *,
        approved: bool,
        scope="exact",
    ) -> bool:
        return await self._services.resolve_approval(
            request_id,
            approved,
            scope,
        )

    async def request_approval(
        self,
        name: str,
        *,
        session_id: str,
        summary="",
        timeout=300.0,
    ) -> bool:
        return await self._services.request_approval(
            name,
            session_id,
            summary,
            timeout,
        )

    async def notify(self, message: str, *, title="", level="info") -> None:
        await self._services.notify(message, title, level)


RouteResult = (
    JSONBody
    | HttpResponse
    | StreamingResponse
    | TaskSnapshot
    | CancelResult
    | SessionSummary
    | ChatReply
    | ApprovalSnapshot
)
RouteHandler = Callable[
    [AppContext, HttpRequest],
    RouteResult | Awaitable[RouteResult],
]
WebSocketHandler = Callable[[AppContext, "WebSocket"], Awaitable[None]]


class PawApp:
    """Collect public routes and contributions, then register one owned app."""

    def __init__(self, name: str = "", *, app_id: str):
        self.name, self.app_id = name or app_id, app_id
        self._routes = []
        self._websockets = []
        self._standard = False

    def route(
        self,
        path: str,
        *,
        methods: tuple[str, ...] = ("GET",),
    ) -> Callable[[RouteHandler], RouteHandler]:
        """Decorate handler(AppContext, HttpRequest), sync or async."""

        def register(handler):
            self._routes.append((path, tuple(methods), handler))
            return handler

        return register

    def websocket(
        self,
        path: str,
    ) -> Callable[[WebSocketHandler], WebSocketHandler]:
        """Decorate async handler(AppContext, WebSocket)."""

        def register(handler):
            self._websockets.append((path, handler))
            return handler

        return register

    def enable_standard_capabilities(self) -> "PawApp":
        self._standard = True
        return self

    def register(self, context: "PluginContext") -> "Registration":
        return context.register_app(self)


class WebSocket:
    """
    Owned connection wrapper; host websocket objects never leave the adapter.
    """

    def __init__(self, connection):
        self._connection = connection

    async def receive(self) -> str | bytes | None:
        message = await self._connection.receive()
        if message["type"] == "websocket.disconnect":
            return None
        return message.get("text", message.get("bytes"))

    async def send(self, message: str | bytes) -> None:
        if isinstance(message, str):
            await self._connection.send_text(message)
        else:
            await self._connection.send_bytes(message)

    async def close(self, code=1000) -> None:
        await self._connection.close(code)
