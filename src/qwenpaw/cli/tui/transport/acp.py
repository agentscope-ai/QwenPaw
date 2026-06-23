# -*- coding: utf-8 -*-
"""Default TUI transport: drive ``qwenpaw acp`` over ACP/stdio.

The transport spawns ``qwenpaw acp`` as a subprocess and connects an ACP
client to it (the same ``spawn_agent_process`` plumbing the in-process ACP
service uses, see ``qwenpaw/agents/acp/service.py``). All agent capabilities —
tools, memory, slash commands, permissions, model switching — come for free
because the ACP server already exposes them.

The client object is duck-typed (mirroring ``ACPHostedClient``): the connection
only ever calls ``session_update``, ``request_permission`` and the ``ext_*``
hooks for the QwenPaw agent, so we implement exactly those.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from contextlib import AsyncExitStack
from typing import Any, AsyncIterator, cast

from acp import (
    PROTOCOL_VERSION,
    spawn_agent_process,
    text_block,
)
from acp.schema import (
    AllowedOutcome,
    ClientCapabilities,
    DeniedOutcome,
    Implementation,
    RequestPermissionResponse,
)

from ..__version__ import __version__
from ..events import (
    BackendWarmed,
    Connected,
    PermissionOption,
    PermissionRequest,
    PushMessage,
    SessionSummary,
    TransportError,
    TurnEnded,
    TuiEvent,
)
from ..normalize import normalize_update

logger = logging.getLogger(__name__)

# Sentinel pushed onto the queue to end ``events()`` iteration.
_CLOSED = object()

# The agent (`run_agent`) may emit JSON-RPC lines up to ~50 MB (e.g. a browser
# screenshot in a tool result). The default asyncio StreamReader line limit is
# 64 KB, which would drop the connection on a big tool payload — match the
# agent's buffer so large messages stream through (same as service.py).
_STDIO_BUFFER_LIMIT = 50 * 1024 * 1024

_WARMUP_PROMPT = (
    "Warm up the QwenPaw backend for an interactive terminal session. "
    "Reply with exactly: ready. Do not call tools."
)

# ``_meta`` flag marking the warmup session ephemeral so the QwenPaw ACP server
# never registers a console chat or persists state for it. Passed as an extra
# kwarg on ``new_session``/``prompt`` (the ACP client folds extra kwargs into
# the request's ``_meta``). Mirrors the server's ``ACP_EPHEMERAL_META_KEY``.
_EPHEMERAL_META_KEY = "qwenpaw.ephemeral"


def _open_agent_stderr_log() -> tuple[int | None, str | None]:
    """Open a file to receive the agent subprocess's stderr.

    ``spawn_agent_process`` defaults the child's stderr to an *unread* PIPE.
    Chatty tools (Chromium via ``browser_use``) flood it, fill the 64 KB pipe
    buffer, block the agent, and the JSON-RPC stream dies ("Connection
    closed"). Draining stderr to a file avoids the deadlock and keeps the logs
    for debugging. Falls back to ``DEVNULL`` if the file can't be opened.
    """
    try:
        from ..paths import log_path

        path = str(log_path("acp.log"))
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        return fd, path
    except Exception as exc:  # noqa: BLE001
        logger.debug("falling back to DEVNULL for agent stderr: %s", exc)
        try:
            return os.open(os.devnull, os.O_WRONLY), None
        except Exception:  # noqa: BLE001
            return None, None


def _warmup_disabled() -> bool:
    return os.getenv("PAW_DISABLE_BACKEND_WARMUP", "").lower() in {
        "1",
        "true",
        "yes",
    }


def _kill_process_tree(pid: int) -> None:
    """Best-effort recursive kill (mirrors acp/service.py fix #4615)."""
    try:
        import psutil  # local import; psutil is already a QwenPaw dep
    except Exception:  # pragma: no cover - psutil always present in app
        return
    try:
        parent = psutil.Process(pid)
    except Exception:
        return
    for child in parent.children(recursive=True):
        try:
            child.kill()
        except Exception:
            pass
    try:
        parent.kill()
    except Exception:
        pass


def _permission_params(tool_call: Any) -> str | None:
    """Render ACP permission tool parameters for the inline approval prompt."""
    raw_input = _tool_call_raw_input(tool_call)
    if raw_input is None:
        return None
    if isinstance(raw_input, str):
        return raw_input.strip() or None
    if isinstance(raw_input, dict):
        lines: list[str] = []
        for key, value in raw_input.items():
            text = (
                value
                if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False)
            )
            lines.append(f"{key}: {text}")
        return "\n".join(lines) or None
    return str(raw_input)


def _tool_call_raw_input(tool_call: Any) -> Any:
    if isinstance(tool_call, dict):
        return tool_call.get("rawInput", tool_call.get("raw_input"))
    raw_input = getattr(tool_call, "raw_input", None)
    if raw_input is not None:
        return raw_input
    return getattr(tool_call, "rawInput", None)


class _TuiClient:
    """ACP client callbacks → push normalized events onto a queue."""

    def __init__(self, queue: "asyncio.Queue[Any]") -> None:
        self._queue = queue
        self._pending: dict[str, asyncio.Future[str | None]] = {}
        self._session_id: str | None = None
        self._ignored_sessions: set[str] = set()

    def set_session_id(self, session_id: str) -> None:
        self._session_id = session_id

    def ignore_session(self, session_id: str) -> None:
        self._ignored_sessions.add(session_id)

    # -- connection lifecycle ------------------------------------------------
    def on_connect(self, conn: Any) -> None:  # noqa: D401 - ACP hook
        self._conn = conn

    # -- streaming updates ---------------------------------------------------
    async def session_update(
        self,
        session_id: str,
        update: Any,
        **_: Any,
    ) -> None:
        if session_id in self._ignored_sessions:
            return
        if self._session_id is not None and session_id != self._session_id:
            return
        for event in normalize_update(update):
            await self._queue.put(event)

    # -- permission round-trip ----------------------------------------------
    async def request_permission(
        self,
        options: list[Any],
        session_id: str,
        tool_call: Any,
        **_: Any,
    ) -> RequestPermissionResponse:
        if session_id in self._ignored_sessions:
            return RequestPermissionResponse(
                outcome=DeniedOutcome(outcome="cancelled"),
            )
        if self._session_id is not None and session_id != self._session_id:
            return RequestPermissionResponse(
                outcome=DeniedOutcome(outcome="cancelled"),
            )
        request_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str | None] = loop.create_future()
        self._pending[request_id] = future

        title = (
            getattr(tool_call, "title", None)
            or getattr(tool_call, "tool_call_id", None)
            or "Permission required"
        )
        await self._queue.put(
            PermissionRequest(
                request_id=request_id,
                title=str(title),
                tool_kind=getattr(tool_call, "kind", None),
                params=_permission_params(tool_call),
                options=[
                    PermissionOption(
                        option_id=getattr(o, "option_id", ""),
                        name=getattr(o, "name", "")
                        or getattr(o, "option_id", ""),
                        kind=getattr(o, "kind", "allow_once"),
                    )
                    for o in options
                ],
            ),
        )

        try:
            option_id = await future
        finally:
            self._pending.pop(request_id, None)

        if option_id is None:
            return RequestPermissionResponse(
                outcome=DeniedOutcome(outcome="cancelled"),
            )
        return RequestPermissionResponse(
            outcome=AllowedOutcome(outcome="selected", option_id=option_id),
        )

    def resolve(self, request_id: str, option_id: str | None) -> None:
        future = self._pending.get(request_id)
        if future is not None and not future.done():
            future.set_result(option_id)

    def cancel_pending(self) -> None:
        for future in list(self._pending.values()):
            if not future.done():
                future.set_result(None)
        self._pending.clear()

    # -- extensions: server-initiated push (design §4.3) --------------------
    async def ext_notification(
        self,
        method: str,
        params: dict[str, Any],
    ) -> None:
        if method in ("qwenpaw/push_message", "session/push_message"):
            text = str(params.get("text") or params.get("message") or "")
            if text:
                await self._queue.put(PushMessage(text))
        # Unknown notifications are ignored (degrade gracefully).

    async def ext_method(
        self,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        del params
        logger.debug("Ignoring unsupported ACP ext method: %s", method)
        return {}


class AcpTransport:
    """Spawns ``qwenpaw acp`` and drives one session over ACP/stdio."""

    def __init__(
        self,
        *,
        agent: str | None = None,
        cwd: str | None = None,
        command: list[str] | None = None,
        resume_session_id: str | None = None,
    ) -> None:
        self._agent = agent
        self._cwd = cwd or os.getcwd()
        # When set, ``start()`` resumes this session (load + replay) instead
        # of opening a fresh one.
        self._resume_session_id = resume_session_id
        # Default: re-invoke this very interpreter as `python -m qwenpaw acp`.
        # The TUI owns that subprocess, so opt it into local diagnostics.
        # Copy the caller's list so appending options never mutates it.
        if command is None:
            self._command = [
                sys.executable,
                "-m",
                "qwenpaw",
                "acp",
                "--local-diagnostics",
            ]
        else:
            self._command = list(command)
        if agent:
            self._command += ["--agent", agent]

        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._client = _TuiClient(self._queue)
        self._stack: AsyncExitStack | None = None
        self._conn: Any = None
        self._process: Any = None
        self._session_id: str | None = None
        self._prompt_task: asyncio.Task[Any] | None = None
        self._warmup_task: asyncio.Task[Any] | None = None
        self._stderr_fd: int | None = None
        self._stderr_path: str | None = None
        self._closed = False

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def start(self) -> Connected:
        self._stack = AsyncExitStack()
        cmd, *args = self._command
        self._stderr_fd, self._stderr_path = _open_agent_stderr_log()
        transport_kwargs: dict[str, Any] = {"limit": _STDIO_BUFFER_LIMIT}
        if self._stderr_fd is not None:
            transport_kwargs["stderr"] = self._stderr_fd
        self._conn, self._process = await self._stack.enter_async_context(
            spawn_agent_process(
                self._client,
                cmd,
                *args,
                cwd=self._cwd,
                env={**os.environ},
                transport_kwargs=transport_kwargs,
            ),
        )
        initialized = await self._conn.initialize(
            protocol_version=PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(),
            client_info=Implementation(name="paw", version=__version__),
        )
        if initialized.protocol_version != PROTOCOL_VERSION:
            logger.warning(
                "ACP protocol mismatch: agent=%s client=%s",
                initialized.protocol_version,
                PROTOCOL_VERSION,
            )
        if self._resume_session_id is not None:
            # Point the client at the resumed session before loading so its
            # replayed history updates (tagged with this id) aren't filtered.
            session_id = self._resume_session_id
            session = await self._conn.load_session(
                cwd=self._cwd,
                session_id=session_id,
            )
            # LoadSessionResponse carries no model list; it populates from the
            # first turn's usage report instead.
            model = None
        else:
            session = await self._conn.new_session(cwd=self._cwd)
            session_id = cast(str, session.session_id)
            model = _current_model(session)
        self._session_id = session_id
        self._client.set_session_id(session_id)
        if not _warmup_disabled():
            self._warmup_task = asyncio.create_task(self._warm_backend())
        return Connected(
            session_id=session_id,
            # Prefer the agent the server actually resolved (via _meta) over
            # the one we requested, so the UI shows the real agent.
            agent=_session_agent(session) or self._agent,
            model=model,
            qwenpaw_version=_agent_version(initialized),
            warming=self._warmup_task is not None,
        )

    async def _warm_backend(self) -> None:
        warm_session_id: str | None = None
        try:
            if self._conn is None:
                return
            warm_session = await self._conn.new_session(
                cwd=self._cwd,
                **{_EPHEMERAL_META_KEY: True},
            )
            warm_session_id = cast(str, warm_session.session_id)
            if warm_session_id == self._session_id:
                logger.debug(
                    "skipping ACP warmup because agent reused session id %s",
                    warm_session_id,
                )
                await self._queue.put(
                    BackendWarmed(
                        success=False,
                        message="warmup skipped: duplicate session id",
                    ),
                )
                return
            self._client.ignore_session(warm_session_id)
            await self._conn.prompt(
                prompt=[text_block(_WARMUP_PROMPT)],
                session_id=warm_session_id,
                **{_EPHEMERAL_META_KEY: True},
            )
            await self._queue.put(BackendWarmed())
        except asyncio.CancelledError:  # pylint: disable=try-except-raise
            raise
        except Exception as exc:  # noqa: BLE001 - warmup is best-effort
            logger.debug("ACP warmup failed: %s", exc, exc_info=True)
            await self._queue.put(
                BackendWarmed(success=False, message=str(exc)),
            )
        finally:
            if (
                warm_session_id is not None
                and self._conn is not None
                and not self._closed
            ):
                try:
                    await self._conn.close_session(session_id=warm_session_id)
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "failed to close warmup session",
                        exc_info=True,
                    )

    async def send(self, text: str) -> None:
        if self._conn is None or self._session_id is None:
            raise RuntimeError("transport not started")
        if self._prompt_task is not None and not self._prompt_task.done():
            raise RuntimeError("a turn is already in progress")
        self._prompt_task = asyncio.create_task(
            self._run_prompt_after_warmup(text),
        )

    async def _run_prompt_after_warmup(self, text: str) -> None:
        if self._warmup_task is not None and not self._warmup_task.done():
            try:
                await self._warmup_task
            except asyncio.CancelledError:  # pylint: disable=try-except-raise
                raise
            except Exception:  # noqa: BLE001
                logger.debug("warmup task failed before prompt", exc_info=True)
        await self._run_prompt(text)

    async def _run_prompt(self, text: str) -> None:
        stop_reason: str | None = None
        try:
            response = await self._conn.prompt(
                prompt=[text_block(text)],
                session_id=self._session_id,
            )
            stop_reason = getattr(response, "stop_reason", None)
            # The ACP connection resolves the prompt *response* inline but
            # dispatches session_update *notifications* via an async queue, so
            # prompt() can return before the final tool/text update has been
            # delivered. Let those in-flight updates land so TurnEnded is last.
            await self._settle()
        except asyncio.CancelledError:
            stop_reason = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001 - surface to UI, don't crash
            await self._queue.put(TransportError(str(exc)))
        finally:
            await self._queue.put(TurnEnded(stop_reason=stop_reason))

    async def _settle(self, *, max_idle: int = 3) -> None:
        """Yield until the event queue stops growing (in-flight notifications
        have all been enqueued). Bounded and cheap: each ``sleep(0)`` lets one
        queued ACP notification task run."""
        idle = 0
        while idle < max_idle:
            before = self._queue.qsize()
            await asyncio.sleep(0)
            if self._queue.qsize() == before:
                idle += 1
            else:
                idle = 0

    async def interrupt(self) -> None:
        if self._conn is None or self._session_id is None:
            return
        # Free any blocked permission first so the prompt task can unwind.
        self._client.cancel_pending()
        try:
            await self._conn.cancel(session_id=self._session_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("cancel failed: %s", exc)

    async def list_sessions(self) -> list[SessionSummary]:
        if self._conn is None:
            raise RuntimeError("transport not started")
        # No cwd filter: QwenPaw runs every session in its single workspace
        # dir regardless of where paw was launched, so all past sessions are
        # equally resumable. Listing them folder-scoped would just hide work.
        response = await self._conn.list_sessions()
        summaries: list[SessionSummary] = []
        for info in getattr(response, "sessions", None) or []:
            session_id = getattr(info, "session_id", None)
            if not session_id:
                continue
            summaries.append(
                SessionSummary(
                    session_id=str(session_id),
                    title=str(getattr(info, "title", "") or ""),
                    cwd=str(getattr(info, "cwd", "") or ""),
                    updated_at=str(getattr(info, "updated_at", "") or ""),
                ),
            )
        return summaries

    async def load_session(self, session_id: str) -> None:
        if self._conn is None:
            raise RuntimeError("transport not started")
        if self._prompt_task is not None and not self._prompt_task.done():
            raise RuntimeError("a turn is already in progress")
        # Let any in-flight warmup finish first; it drives its own (ignored)
        # session, but loading mid-warmup risks interleaved backend work.
        if self._warmup_task is not None and not self._warmup_task.done():
            try:
                await self._warmup_task
            except asyncio.CancelledError:  # pylint: disable=try-except-raise
                raise
            except Exception:  # noqa: BLE001 - warmup is best-effort
                logger.debug("warmup task failed before load", exc_info=True)
        # Point the client at the resumed session *before* loading so the
        # replayed history updates (tagged with this id) aren't filtered out.
        self._session_id = session_id
        self._client.set_session_id(session_id)
        await self._conn.load_session(cwd=self._cwd, session_id=session_id)

    async def resolve_permission(
        self,
        request_id: str,
        option_id: str | None,
    ) -> None:
        self._client.resolve(request_id, option_id)

    async def events(self) -> AsyncIterator[TuiEvent]:
        while True:
            item = await self._queue.get()
            if item is _CLOSED:
                return
            yield item

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._client.cancel_pending()
        if self._warmup_task is not None and not self._warmup_task.done():
            self._warmup_task.cancel()
            try:
                await self._warmup_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._prompt_task is not None and not self._prompt_task.done():
            self._prompt_task.cancel()
            try:
                await self._prompt_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._conn is not None and self._session_id is not None:
            try:
                await asyncio.wait_for(
                    self._conn.close_session(session_id=self._session_id),
                    timeout=5.0,
                )
            except Exception:  # noqa: BLE001
                pass
        if self._process is not None:
            _kill_process_tree(self._process.pid)
        if self._stack is not None:
            try:
                await self._stack.aclose()
            except Exception:  # noqa: BLE001
                pass
        if self._stderr_fd is not None:
            try:
                os.close(self._stderr_fd)
            except OSError:
                pass
            self._stderr_fd = None
        await self._queue.put(_CLOSED)


# ``_meta`` key QwenPaw sets on the session response with the resolved agent
# id; mirrors the ACP server's ``ACP_AGENT_META_KEY``.
_AGENT_META_KEY = "qwenpaw.agent"


def _session_agent(new_session: Any) -> str | None:
    """The resolved agent id the server reported via ``_meta``, if any."""
    meta = getattr(new_session, "field_meta", None)
    if isinstance(meta, dict):
        agent = meta.get(_AGENT_META_KEY)
        if agent:
            return str(agent)
    return None


def _current_model(new_session: Any) -> str | None:
    """Best-effort extraction of the current model name from new_session."""
    models = getattr(new_session, "models", None)
    if not models:
        return None
    current_id = getattr(models, "current_model_id", None) or getattr(
        models,
        "current",
        None,
    )
    available = getattr(models, "available_models", None) or getattr(
        models,
        "models",
        None,
    )
    if available:
        for model in available:
            mid = getattr(model, "model_id", None) or getattr(
                model,
                "id",
                None,
            )
            if mid == current_id:
                return getattr(model, "name", None) or str(mid)
    return str(current_id) if current_id else None


def _agent_version(initialized: Any) -> str | None:
    """Best-effort extraction of the ACP server's implementation version."""
    info = getattr(initialized, "agent_info", None)
    version = getattr(info, "version", None)
    return str(version) if version else None
