# -*- coding: utf-8 -*-
"""Antigravity CLI backend using only the public QwenPaw plugin contract.

The CLI is driven through its Agent Client Protocol server (``agy acp``):
one server process per working directory (or per session when MCP servers
are attached), one ACP session per QwenPaw conversation identity.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
import time
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import unquote_to_bytes, urlparse
from urllib.request import url2pathname

from acp import (
    PROTOCOL_VERSION,
    RequestError,
    image_block,
    resource_link_block,
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
from qwenpaw.plugins import SDKError
from qwenpaw.plugins.harnesses import (
    HarnessApprovalSummary,
    HarnessAttachment,
    HarnessAttachmentKind,
    HarnessCallContext,
    HarnessContext,
    HarnessDiscoveredMCPServer,
    HarnessDiscoveredSkill,
    HarnessEvent,
    HarnessEventKind,
    HarnessHistoryItem,
    HarnessLogin,
    HarnessModel,
    HarnessOperationNotSupportedError,
    HarnessRunRequest,
    HarnessRuntimeCapabilities,
    HarnessStatus,
)

from .auth_fingerprint import (
    async_agy_auth_fingerprint,
    read_active_agy_auth_fingerprint,
)
from .discovery import AgyBinaryResolution, resolve_agy_binary_info
from .event_mapper import AgyEventMapper
from .io_helpers import finish, run_io
from .projection import mcp_servers

logger = logging.getLogger(__name__)

PROVIDER_ID = "agy"
PROVIDER_NAME = "Antigravity"
_CLIENT_VERSION = "1.0.0"

# The approval preset under which nothing is asked. Its sessions run on a
# server started with the CLI's own flag for that: a subagent's permission
# request never reaches an ACP client, so answering requests on this side
# alone would leave a subagent waiting for an approval nobody is shown.
BYPASS_PERMISSIONS = "bypassPermissions"
_SKIP_PERMISSIONS_FLAG = "--dangerously-skip-permissions"
_AGY_MODES = ("default", "accept-edits", "auto", "plan")
_EFFORTS = ("low", "medium", "high", "xhigh", "max")
_SKIP_GUARDIAN_ENV_VARS = (
    "QWENPAW_AGY_SKIP_GUARDIAN",
    "COPAW_ACPX_SKIP_GUARDIAN",
)
_TRUTHY_FLAGS = frozenset({"1", "true", "yes", "on", "y", "t"})

# Starting the server and opening a session each load the account's
# settings from Google; a cold start takes a few seconds.
_CONNECT_TIMEOUT_SECONDS = 60
# Status checks run during generic harness catalog listings; fail fast so an
# unreachable network cannot block unrelated pages.
_PROBE_TIMEOUT_SECONDS = 15
# How long a status check trusts the last successful login probe. The
# agent settings page polls the status every two seconds while it is open.
_ACCOUNT_CACHE_SECONDS = 60
# A probe that could not reach the CLI is not repeated for this long: each
# attempt starts a process, and the settings page asks every two seconds.
_PROBE_FAILURE_CACHE_SECONDS = 15
# After asking the server to cancel a turn, how long to wait for it to
# answer the prompt before leaving it behind.
_CANCEL_GRACE_SECONDS = 10
# Approval prompt timeout forwarded to QwenPaw's host approval service.
_APPROVAL_TIMEOUT_SECONDS = 60
# Session-isolated ``agy acp`` processes keep MCP server pools from colliding
# across conversations, while an idle cap and TTL bound memory use when many
# chats run over time.
_DEFAULT_MAX_IDLE_ISOLATED_SERVERS = 4
_DEFAULT_IDLE_ISOLATED_SERVER_TTL_SECONDS = 600.0
# A turn's updates are sent before its result, but each is handled as its
# own task: give the ones already received a moment to be queued.
_SETTLE_SECONDS = 0.05
# One JSON line can hold a whole file read or an image.
_STDIO_LIMIT_BYTES = 50 * 1024 * 1024
# JSON-RPC code the server answers with when nobody is logged in.
_AUTH_REQUIRED = -32000
_INSTALL_HINT = "Antigravity CLI not found. Install agy or provide its path."
_LOGIN_HINT = (
    "Antigravity CLI is not logged in. Run `agy acp --login` in a terminal "
    "on this machine, then try again."
)
_RISKY_KINDS = {"execute", "delete", "move"}

# Appended to the CLI's system prompt. On its own the CLI moves a slow
# command or a subagent to the background and ends the turn with "waiting
# for it"; the result then only comes out when the next message arrives,
# and a channel or another agent that handed over a task never sends one.
_HOST_RULES = (
    "You are running inside QwenPaw, an automated host. After the last "
    "message of your turn nobody sends another message until a person or "
    "another agent decides to, so a turn that ends early leaves its work "
    "unreported. Do not end a turn while a command, subagent or workflow "
    "you started is still running in the background: wait for it to "
    "finish, read its result and report it in the same turn. If the tool "
    "you wait with fails, wait another way (check the subagent or task "
    'again after a short pause) instead of ending the turn; "I am '
    'waiting for it" is never a final answer.'
)
# The rule above is not always kept. The CLI moves a command that runs
# longer than a few seconds to the background and tells the model it may end
# the turn and will be started again when the command finishes; a timer the
# model sets works the same way. The CLI does start the conversation again,
# but an ACP client hears nothing of it until the next message arrives
# (measured on 1.5.9), so the turn's last words, "build started, waiting for
# the result", became the result of the task. At that point the tool call
# is still in progress, which is how it is noticed: the session is then told
# to wait, at most this many times in one turn.
_MAX_WAIT_REMINDERS_PER_TURN = 4
_MAX_RUNNING_ITEM_CHARS = 300
_WAIT_REMINDER = (
    "[Automatic message from QwenPaw, the host. It is not from the user.] "
    "Your turn ended while the following was still running in the "
    "background:\n{items}\n"
    "In this host nothing starts the conversation again when it finishes "
    "or comes due. Only your last message is handed over as the result of "
    "the task, and the task is then reported as finished. So stay in this "
    "turn: wait by running a short blocking command (for example "
    "`sleep 9`, kept shorter than the wait-before-async limit so that it "
    "stays in the foreground), then check the status; repeat until it has "
    "finished, read its result, carry on with the task you were given and "
    "end with your complete report. If it is meant to keep running after "
    "the turn, as a server is, do not wait: write your complete report "
    "again as your last message and say in it that this keeps running."
)
_STILL_RUNNING_NOTE = (
    "\n\n(Still running in the background when this turn ended: {items}. "
    "If its result is needed, send a message to this conversation to "
    "collect it.)"
)
# What the host adds to a message that starts with one of the CLI's own
# commands. A swarm coordinator is written for a terminal: it starts the
# workers, ends its turn at once and is woken again by their posts, with the
# progress on the `/swarm board` screen. Nothing wakes a turn here, so
# without this the reply is "the swarm has started" and the outcome is never
# reported.
_COMMAND_NOTES = {
    "swarm": (
        "[Note from the host, for the coordinator only; do not pass it on "
        "to workers.] This conversation runs inside an automated host. "
        "There is no /swarm board here and nothing wakes you after this "
        "turn ends, so a reply that only says the swarm has started is the "
        "last thing anyone sees. In this turn: start the swarm, then stay "
        "in the turn (wait with swarm_wait, read the board, hand out "
        "follow-ups) until the work is finished or cannot go further. Then "
        "give the final result as your reply: what was done, where it is, "
        "and anything that failed. Do not end with a board link or command."
    ),
}
# Forms of a command that start nothing and so need no note.
_COMMAND_NOTE_EXEMPT = {"swarm": {"", "board", "status"}}

# The agent's identity and memory files in its workspace, and how much of
# each is put into the system prompt. QwenPaw's own runtime builds its
# prompt from AGENTS.md, SOUL.md and PROFILE.md; the CLI loads AGENTS.md on
# its own but none of the others.
_MEMORY_FILES = ("SOUL.md", "PROFILE.md", "MEMORY.md")
_MAX_MEMORY_FILE_CHARS = 12_000
# The CLI loads only the first part of AGENTS.md: the first 24,000 bytes,
# cut back to the end of a line, then "<truncated N bytes>" (measured on
# 1.5.9). The rules after that point would be lost, so the part the CLI
# drops is put into the system prompt, up to this many characters.
_AGENTS_FILE = "AGENTS.md"
_CLI_AGENTS_BYTES = 24_000
_MAX_AGENTS_REST_CHARS = 20_000
_AGENTS_REST_RULES = (
    "The copy of AGENTS.md above is cut short: it ends with a "
    '"<truncated … bytes>" marker. The rest of that file follows. It is '
    "part of the same rules and has the same authority as the part before "
    "the marker."
)
_MEMORY_RULES = (
    "QwenPaw keeps this agent's identity and long-term memory as files in "
    "the working directory. SOUL.md says who you are and how you speak: "
    "stay in that character. SOUL.md, PROFILE.md and MEMORY.md are "
    "reproduced below as they were when this conversation was opened "
    "(those that exist). Notes about your conversations are "
    "written for you afterwards: `memory/` holds dated notes and `digest/` "
    "holds what was consolidated from them; read them when an answer "
    "depends on earlier work. Edit MEMORY.md yourself only for something "
    "that must not be forgotten."
)

# Marker in a turn's queue indicating a prompt has finished.
_DONE = object()


def _effective_permission_mode(settings: Mapping[str, Any]) -> str:
    """Resolve permission mode, honoring skip-guardian env overrides."""
    explicit = settings.get("permission_mode")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    for env_name in _SKIP_GUARDIAN_ENV_VARS:
        if os.environ.get(env_name, "").strip().lower() in _TRUTHY_FLAGS:
            return BYPASS_PERMISSIONS
    return "default"


@dataclass(eq=False)
class _Prompt:
    """One ``session/prompt`` request of a turn."""

    task: asyncio.Future
    # "user" for the message that started the turn, "reminder" for the
    # host telling the session to wait.
    kind: str
    # The tool calls the turn had started when this prompt was sent.
    tools_before: int = 0


@dataclass
class _Server:
    """One running ``agy acp`` process and the connection to it."""

    conn: Any
    process: Any
    stack: AsyncExitStack
    directory: str
    mcp_http: bool = False
    mcp_sse: bool = False
    skip_permissions: bool = False
    # Where the backend keeps it; the directory alone for a shared process.
    key: str = ""
    auth_fingerprint: str = ""
    # Non-empty when this process is dedicated to a single conversation
    # (required when the session attaches MCP servers, because ``agy acp``
    # shares MCP server registrations across sessions in one process).
    session_id: str = ""
    last_used_at: float = field(default_factory=time.monotonic)

    @property
    def alive(self) -> bool:
        if self.process.returncode is not None:
            return False
        return _connection_alive(self.conn)


@dataclass
class _Session:
    """One open ACP session and what the backend knows about it."""

    acp_id: str
    key: tuple[Any, ...]
    server: _Server
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Current value, initial defaults and offered values of each session
    # config option.
    config: dict[str, str] = field(default_factory=dict)
    defaults: dict[str, str] = field(default_factory=dict)
    offered: dict[str, list[str]] = field(default_factory=dict)
    permission_mode: str = "default"
    # Bound only while a turn runs so stale permission callbacks never cross
    # into another caller's turn.
    call_context: HarnessCallContext | None = None
    # Set while a turn runs: where the turn reads its updates from.
    queue: asyncio.Queue | None = None
    # Title and arguments of the turn's tool calls, for approval requests,
    # which name the call only by id.
    tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    approvals: set[asyncio.Task] = field(default_factory=set)


class _Client:
    """The client side of the ACP connection.

    File system and terminal access are not offered to the server (the CLI
    uses its own tools), so only updates and permission requests arrive.
    """

    def __init__(self, backend: "AgyBackend") -> None:
        self._backend = backend

    def on_connect(self, conn: Any) -> None:
        """Nothing to keep: the backend holds the connection."""
        del conn

    async def session_update(
        self,
        session_id: str,
        update: Any,
        **_: Any,
    ) -> None:
        """Pass one update to the turn that is running in the session."""
        self._backend.handle_update(session_id, update)

    async def request_permission(
        self,
        options: list[Any],
        session_id: str,
        tool_call: Any,
        **_: Any,
    ) -> RequestPermissionResponse:
        """Answer one permission request."""
        return await self._backend.handle_permission(
            session_id,
            options,
            tool_call,
        )

    async def ext_method(self, method: str, params: dict[str, Any]) -> Any:
        """Reject extension requests: none are supported."""
        del params
        raise RequestError.method_not_found(method)

    async def ext_notification(
        self,
        method: str,
        params: dict[str, Any],
    ) -> None:
        """Ignore extension notifications."""
        del method, params

    def __getattr__(self, name: str) -> Any:
        # Requests for capabilities that were not offered (fs/*, terminal/*).
        if name.startswith("_"):
            raise AttributeError(name)

        async def unsupported(*_args: Any, **_kwargs: Any) -> Any:
            raise RequestError.method_not_found(name)

        return unsupported


class AgyBackend:
    """Run Antigravity CLI sessions inside one QwenPaw agent workspace."""

    def __init__(
        self,
        context: HarnessContext,
        settings: dict[str, Any] | None = None,
        *,
        binary: str | None = None,
        spawn: Callable[..., Any] | None = None,
        auth_fingerprint: Callable[[], str] | None = None,
        max_idle_isolated_servers: int | None = None,
        idle_isolated_server_ttl: float | None = None,
    ) -> None:
        self._context = context
        self._state_dir = context.state_dir
        self._binary = (
            binary or str((settings or {}).get("binary") or "").strip() or None
        )
        self._spawn = spawn or spawn_agent_process
        if auth_fingerprint is not None:
            self._auth_fingerprint = auth_fingerprint
        elif spawn is not None:
            # Keep injected FakeServer unit tests hermetic from host keyrings.
            self._auth_fingerprint = lambda: ""
        else:
            self._auth_fingerprint = read_active_agy_auth_fingerprint
        self._max_idle_isolated_servers = (
            max_idle_isolated_servers
            if max_idle_isolated_servers is not None
            else _env_int(
                "QWENPAW_AGY_MAX_IDLE_ISOLATED_SERVERS",
                _DEFAULT_MAX_IDLE_ISOLATED_SERVERS,
            )
        )
        self._idle_isolated_server_ttl = (
            idle_isolated_server_ttl
            if idle_isolated_server_ttl is not None
            else _env_float(
                "QWENPAW_AGY_IDLE_SERVER_TTL_SECONDS",
                _DEFAULT_IDLE_ISOLATED_SERVER_TTL_SECONDS,
            )
        )
        self._last_auth_fingerprint = ""
        self._sessions: dict[str, str] = {}
        self._live: dict[str, _Session] = {}
        self._by_acp_id: dict[str, _Session] = {}
        # Keyed by directory (+ unattended / per-session isolation suffix).
        # The CLI resolves relative paths against its own working directory,
        # not against the directory a session names, so each session gets a
        # server started in its directory.
        self._servers: dict[str, _Server] = {}
        self._turn_locks: dict[str, asyncio.Lock] = {}
        self._session_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._catalog: list[HarnessModel] = []
        self._account: dict[str, Any] | None = None
        self._account_checked_at = 0.0
        self._probe_error: Exception | None = None
        self._probe_failed_at = 0.0
        self._prepared = False
        self._closed = False

    async def prepare(self) -> None:
        """Load session mappings, copying legacy state once if present."""
        async with self._session_lock:
            if self._closed:
                raise SDKError("Antigravity backend is closed")
            if self._prepared:
                return
            try:
                missing = object()
                payload = await self._context.storage.aread_json(
                    "agy_sessions.json",
                    missing,
                )
                if payload is missing:
                    legacy = (
                        self._context.workspace_dir
                        / "harnesses"
                        / "agy_sessions.json"
                    )
                    try:
                        raw = await run_io(legacy.read_bytes)
                    except FileNotFoundError:
                        payload = {}
                    else:
                        payload = json.loads(raw)
                        self._validate_sessions(payload)
                        await self._context.storage.awrite_bytes(
                            "agy_sessions.json",
                            raw,
                        )
                self._validate_sessions(payload)
            except (OSError, json.JSONDecodeError, UnicodeError) as exc:
                raise SDKError(
                    "Could not load Antigravity session state; restore "
                    f"agy_sessions.json or fix file permissions: {exc}",
                ) from exc
            self._sessions = dict(payload)
            self._prepared = True

    @staticmethod
    def _validate_sessions(payload: Any) -> None:
        if not isinstance(payload, dict) or not all(
            isinstance(key, str) and isinstance(value, str) and key and value
            for key, value in payload.items()
        ):
            raise SDKError(
                "Antigravity session mapping is invalid; "
                "restore its saved JSON state",
            )

    @staticmethod
    def _session_key(context: HarnessCallContext) -> str:
        return json.dumps(
            [context.user_id, context.channel, context.session_id],
        )

    async def _save_sessions(self, payload: dict[str, str]) -> None:
        async def commit() -> None:
            try:
                await self._context.storage.awrite_json(
                    "agy_sessions.json",
                    payload,
                )
            except (OSError, UnicodeError) as exc:
                raise SDKError(
                    "Could not save Antigravity session state; "
                    f"check storage permissions: {exc}",
                ) from exc
            self._sessions = payload

        await finish(commit())

    async def _claim_session(self, context: HarnessCallContext) -> str | None:
        identity = self._session_key(context)
        if (
            identity not in self._sessions
            and context.session_id in self._sessions
        ):
            payload = dict(self._sessions)
            payload[identity] = payload.pop(context.session_id)
            await self._save_sessions(payload)
        return self._sessions.get(identity)

    # ------------------------------------------------------------------
    # Status, login, models and discovery
    # ------------------------------------------------------------------

    async def status(self, context: HarnessCallContext) -> HarnessStatus:
        """Return CLI installation and login status."""
        del context
        await self.prepare()
        resolution = await self._resolution()
        if resolution is None:
            return HarnessStatus(
                installed=False,
                error=_INSTALL_HINT,
            )
        try:
            account = await self._probe_account()
        except _NotLoggedIn:
            return self._status(resolution)
        except (
            OSError,
            RuntimeError,
            RequestError,
            TimeoutError,
            SDKError,
        ) as exc:
            return self._status(
                resolution,
                error=str(exc) or type(exc).__name__,
            )
        return self._status(
            resolution,
            authenticated=True,
            account=account,
        )

    async def start_login(
        self,
        context: HarnessCallContext,
        *,
        device_code: bool = False,
    ) -> HarnessLogin:
        """Name the command that logs in.

        The CLI's Google login needs a terminal (it prints a link and waits
        for the code), so it cannot be started from here.
        """
        del context, device_code
        await self.prepare()
        resolution = await self._require_resolution()
        self._account_checked_at = 0.0
        self._probe_error = None
        self._probe_failed_at = 0.0
        return HarnessLogin(
            {
                "type": "external",
                "loginId": f"agy-{uuid.uuid4().hex}",
                "command": f"{resolution.path} acp --login",
            },
        )

    async def logout(self, context: HarnessCallContext) -> None:
        """Explain the provider-owned logout limitation."""
        del context
        raise HarnessOperationNotSupportedError(
            "Antigravity CLI has no non-interactive logout. Run `agy` and "
            "use /logout.",
        )

    async def models(
        self,
        context: HarnessCallContext,
    ) -> tuple[HarnessModel, ...]:
        """Return the models the logged-in account can use."""
        del context
        await self.prepare()
        if await self._resolution() is None:
            return ()
        if not self._catalog:
            try:
                await self._probe_account(force=True)
            except _NotLoggedIn:
                return ()
        return tuple(self._catalog)

    async def discover_skills(
        self,
        context: HarnessCallContext,
    ) -> tuple[HarnessDiscoveredSkill, ...]:
        del context
        raise HarnessOperationNotSupportedError(
            "Antigravity CLI does not expose provider skill discovery.",
        )

    async def discover_mcp(
        self,
        context: HarnessCallContext,
    ) -> tuple[HarnessDiscoveredMCPServer, ...]:
        del context
        raise HarnessOperationNotSupportedError(
            "Antigravity CLI does not expose provider MCP discovery.",
        )

    async def history(
        self,
        context: HarnessCallContext,
    ) -> tuple[HarnessHistoryItem, ...]:
        del context
        return ()

    async def run_command(
        self,
        context: HarnessCallContext,
        command: str,
        arguments: str,
    ) -> tuple[HarnessEvent, ...]:
        if command != "swarm":
            raise HarnessOperationNotSupportedError(
                f"Unsupported Antigravity command: /{command}",
            )
        prompt = f"/{command}" + (f" {arguments}" if arguments else "")
        events = [
            event
            async for event in self.run_turn(
                context,
                HarnessRunRequest(prompt),
            )
        ]
        return tuple(events)

    # ------------------------------------------------------------------
    # Turns
    # ------------------------------------------------------------------

    async def run_turn(
        self,
        context: HarnessCallContext,
        request: HarnessRunRequest,
    ) -> AsyncIterator[HarnessEvent]:
        """Send one turn to the session and stream what the CLI reports."""
        await self.prepare()
        identity = self._session_key(context)
        turn_lock = self._turn_locks.setdefault(identity, asyncio.Lock())
        async with turn_lock:
            async with self._locked_session(context, identity) as session:
                session.call_context = context
                session.permission_mode = _effective_permission_mode(
                    context.settings,
                )
                await self._apply_settings(session, context.settings)
                blocks = await self._prompt_blocks(
                    _with_command_note(request.prompt),
                    request.attachments,
                )
                mapper = AgyEventMapper()
                queue: asyncio.Queue = asyncio.Queue()
                session.queue = queue
                session.tools.clear()
                reminders = 0
                tools_started = 0
                pending: list[_Prompt] = []
                answered: list[_Prompt] = []
                settled = False

                def send(content: list[Any], kind: str) -> None:
                    mapper.begin_prompt()
                    sent = _Prompt(
                        task=asyncio.ensure_future(
                            session.server.conn.prompt(
                                prompt=content,
                                session_id=session.acp_id,
                            ),
                        ),
                        kind=kind,
                        tools_before=tools_started,
                    )

                    def done(_task: asyncio.Future) -> None:
                        answered.append(sent)
                        queue.put_nowait(_DONE)

                    sent.task.add_done_callback(done)
                    pending.append(sent)

                try:
                    send(blocks, "user")
                    while True:
                        if pending:
                            item = await queue.get()
                        else:
                            if not settled:
                                # A turn's updates are sent before its result,
                                # but each is handled as its own task.
                                await asyncio.sleep(_SETTLE_SECONDS)
                                settled = True
                            if queue.empty():
                                last = answered[-1]
                                running = _running_calls(mapper, session)
                                if not running or not self._may_remind(
                                    session,
                                    last,
                                    reminders=reminders,
                                    tools_started=(
                                        tools_started - last.tools_before
                                    ),
                                ):
                                    break
                                reminders += 1
                                items = list(running.values())
                                logger.info(
                                    "agy: session %s ended its turn with %d "
                                    "tool call(s) still running (%s); telling "
                                    "it to wait (reminder %d)",
                                    session.acp_id,
                                    len(items),
                                    "; ".join(items),
                                    reminders,
                                )
                                send(
                                    [
                                        text_block(
                                            _WAIT_REMINDER.format(
                                                items="\n".join(
                                                    f"- {item}"
                                                    for item in items
                                                ),
                                            ),
                                        ),
                                    ],
                                    "reminder",
                                )
                                settled = False
                                yield HarnessEvent(
                                    kind=HarnessEventKind.REASONING_DELTA,
                                    text=(
                                        "\n[QwenPaw] The turn ended while "
                                        "this was still running in the "
                                        f"background: {'; '.join(items)}. "
                                        "The agent was told to wait for it.\n"
                                    ),
                                )
                                continue
                            item = queue.get_nowait()
                        if item is _DONE:
                            for settled_one in [
                                p for p in pending if p in answered
                            ]:
                                pending.remove(settled_one)
                            continue
                        for event in mapper.convert(item):
                            if event.kind == HarnessEventKind.TOOL_STARTED:
                                tools_started += 1
                            yield event
                    # Read before the result closes the calls left open.
                    running = _running_calls(mapper, session)
                    events, broken = self._turn_result(
                        answered[-1].task,
                        mapper,
                    )
                    if broken:
                        async with self._session_lock:
                            await self._disconnect(session.server)
                    if (
                        running
                        and events[-1].kind == HarnessEventKind.COMPLETED
                    ):
                        logger.warning(
                            "agy: session %s ended its turn with tool call(s) "
                            "still running (%s)",
                            session.acp_id,
                            "; ".join(running.values()),
                        )
                        events.insert(
                            len(events) - 1,
                            HarnessEvent(
                                kind=HarnessEventKind.TEXT_DELTA,
                                text=_STILL_RUNNING_NOTE.format(
                                    items="; ".join(running.values()),
                                ),
                            ),
                        )
                    for event in events:
                        yield event
                finally:
                    session.queue = None
                    session.call_context = None
                    unanswered = [p.task for p in pending if not p.task.done()]
                    if unanswered:
                        await finish(self._cancel_turn(session, unanswered))

    def _may_remind(
        self,
        session: _Session,
        prompt: _Prompt,
        *,
        reminders: int,
        tools_started: int,
    ) -> bool:
        """Whether a turn that left work running is told to wait for it."""
        if reminders >= _MAX_WAIT_REMINDERS_PER_TURN:
            return False
        if prompt.kind == "reminder" and not tools_started:
            return False
        prompt_task = prompt.task
        if prompt_task.cancelled() or prompt_task.exception() is not None:
            return False
        reason = getattr(prompt_task.result(), "stop_reason", "")
        if str(reason or "end_turn") != "end_turn":
            return False
        return (
            self._by_acp_id.get(session.acp_id) is session
            and session.server.alive
        )

    @asynccontextmanager
    async def _locked_session(
        self,
        context: HarnessCallContext,
        identity: str,
    ) -> AsyncIterator[_Session]:
        """The session for a turn, with its lock held."""
        while True:
            session = await self._session_for(context, identity)
            await session.lock.acquire()
            if self._live.get(identity) is session:
                break
            session.lock.release()
        try:
            yield session
        finally:
            session.server.last_used_at = time.monotonic()
            session.lock.release()

    def _turn_result(
        self,
        prompt_task: asyncio.Future,
        mapper: AgyEventMapper,
    ) -> tuple[list[HarnessEvent], bool]:
        """Return ``(events, server_broken)`` once the prompt has settled."""
        try:
            response = prompt_task.result()
        except RequestError as exc:
            if exc.code == _AUTH_REQUIRED:
                self._account = None
                self._account_checked_at = 0.0
                return mapper.close() + [_error(_LOGIN_HINT)], False
            return mapper.close() + [_error(_request_error_text(exc))], False
        except (OSError, RuntimeError) as exc:
            # The server went away mid-turn.
            return (
                mapper.close()
                + [_error(f"Antigravity CLI stopped unexpectedly: {exc}")],
                True,
            )
        except Exception as exc:  # pylint: disable=broad-except
            return (
                mapper.close()
                + [_error(f"Antigravity CLI failed unexpectedly: {exc}")],
                False,
            )
        reason = str(getattr(response, "stop_reason", "") or "end_turn")
        events = mapper.close()
        if reason == "cancelled":
            return (
                events + [HarnessEvent(kind=HarnessEventKind.CANCELLED)],
                False,
            )
        if reason == "refusal":
            return (
                events + [_error("The model declined to continue.")],
                False,
            )
        if reason in {"max_tokens", "max_turn_requests"}:
            events.append(
                HarnessEvent(
                    kind=HarnessEventKind.TEXT_DELTA,
                    text=(
                        "\n\n(The turn stopped at Antigravity's "
                        f"{reason.replace('_', ' ')} limit. Send a message "
                        "to continue.)"
                    ),
                ),
            )
        return (
            events + [HarnessEvent(kind=HarnessEventKind.COMPLETED)],
            False,
        )

    async def _cancel_turn(
        self,
        session: _Session,
        prompt_tasks: list[asyncio.Future],
    ) -> None:
        """Ask the server to stop the turn and wait briefly for it to."""
        approvals = tuple(session.approvals)
        for task in approvals:
            task.cancel()
        if approvals:
            await asyncio.gather(*approvals, return_exceptions=True)
        try:
            await session.server.conn.cancel(session_id=session.acp_id)
        except Exception:  # pylint: disable=broad-except
            logger.debug("agy: cancel request failed", exc_info=True)
        try:
            async with asyncio.timeout(_CANCEL_GRACE_SECONDS):
                await asyncio.gather(*prompt_tasks, return_exceptions=True)
        except TimeoutError:
            for prompt_task in prompt_tasks:
                prompt_task.cancel()
            await asyncio.gather(*prompt_tasks, return_exceptions=True)
            async with self._session_lock:
                others_running = any(
                    other.server is session.server
                    and other is not session
                    and other.queue is not None
                    for other in self._live.values()
                )
                if others_running:
                    logger.warning(
                        "agy: session %s did not confirm the cancel; "
                        "dropping it",
                        session.acp_id,
                    )
                    for key, live in tuple(self._live.items()):
                        if live is session:
                            del self._live[key]
                    self._by_acp_id.pop(session.acp_id, None)
                else:
                    logger.warning(
                        "agy: session %s did not confirm the cancel; "
                        "resetting server",
                        session.acp_id,
                    )
                    await self._disconnect(session.server)

    async def _prompt_blocks(
        self,
        prompt: str,
        attachments: tuple[HarnessAttachment, ...],
    ) -> list[Any]:
        blocks: list[Any] = []
        files: list[tuple[HarnessAttachment, Path]] = []
        for attachment in attachments:
            raw_str = str(attachment.path)
            if attachment.kind == HarnessAttachmentKind.IMAGE:
                if raw_str.startswith("data:"):
                    mime_type, encoded = _parse_data_url(raw_str)
                    blocks.append(image_block(encoded, mime_type))
                else:
                    local_path = _local_path(attachment.path)
                    data = await run_io(local_path.read_bytes)
                    mime_type = (
                        _sniff_image_mime(data)
                        or mimetypes.guess_type(local_path.name)[0]
                        or "image/png"
                    )
                    blocks.append(
                        image_block(
                            base64.b64encode(data).decode("ascii"),
                            mime_type,
                        ),
                    )
            else:
                files.append((attachment, _local_path(attachment.path)))
        text = prompt
        if files:
            # Named in the text too: a resource link alone leaves it to the
            # model to notice that a file came with the message.
            listed = "\n".join(f"- {_resolved(path)}" for _, path in files)
            text = f"Attached files:\n{listed}\n\n{prompt}".strip()
        if text:
            blocks.insert(0, text_block(text))
        for attachment, local_path in files:
            path = _resolved(local_path)
            blocks.append(
                resource_link_block(
                    attachment.name or path.name,
                    path.as_uri(),
                    mime_type=mimetypes.guess_type(path.name)[0],
                ),
            )
        if not blocks:
            blocks.append(text_block(prompt))
        return blocks

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    async def reset_session(self, context: HarnessCallContext) -> None:
        """Close and forget one conversation."""
        await self.prepare()
        identity = self._session_key(context)
        lock = self._turn_locks.setdefault(identity, asyncio.Lock())
        async with lock:
            async with self._session_lock:
                await finish(self._reset_session(context, identity))

    async def _reset_session(
        self,
        context: HarnessCallContext,
        identity: str,
    ) -> None:
        acp_id = await self._claim_session(context)
        session = self._live.pop(identity, None)
        if session is not None:
            self._by_acp_id.pop(session.acp_id, None)
            approvals = tuple(session.approvals)
            for task in approvals:
                task.cancel()
            if approvals:
                await asyncio.gather(*approvals, return_exceptions=True)
            if session.queue is not None and session.server.alive:
                try:
                    await session.server.conn.cancel(session_id=session.acp_id)
                except Exception:  # pylint: disable=broad-except
                    logger.debug(
                        "agy: cancel on reset failed",
                        exc_info=True,
                    )
            if session.server.session_id == identity:
                await self._disconnect(session.server)
            else:
                await self._close_acp_session(session.server, session.acp_id)
        if acp_id is not None or identity in self._sessions:
            payload = dict(self._sessions)
            payload.pop(identity, None)
            await self._save_sessions(payload)

    async def close(self) -> None:
        """Stop every server process and forget their sessions."""
        async with self._close_lock:
            self._closed = True
            await finish(self._close())

    async def _close(self) -> None:
        async with self._session_lock:
            for server in tuple(self._servers.values()):
                await self._disconnect(server)
            self._live.clear()
            self._by_acp_id.clear()
            self._turn_locks.clear()

    async def _session_for(
        self,
        context: HarnessCallContext,
        identity: str,
    ) -> _Session:
        capabilities = (
            context.runtime_capabilities or HarnessRuntimeCapabilities()
        )
        directory = str((await run_io(context.cwd.resolve)))
        skip_permissions = (
            _effective_permission_mode(context.settings) == BYPASS_PERMISSIONS
        )
        isolate_session = bool(capabilities.mcp_servers)
        server_session_id = identity if isolate_session else ""
        key = (
            directory,
            capabilities.fingerprint,
            skip_permissions,
            isolate_session,
        )
        while True:
            auth_fp = await self._current_auth_fingerprint()
            async with self._session_lock:
                existing = self._live.get(identity)
                if (
                    existing is not None
                    and existing.lock.locked()
                    and (
                        existing.key != key
                        or (
                            _auth_stale(existing.server, auth_fp)
                            and not self._server_busy(
                                existing.server,
                                ignore_session=existing,
                            )
                        )
                    )
                ):
                    busy = existing
                else:
                    server = await self._server(
                        directory,
                        skip_permissions=skip_permissions,
                        auth_fingerprint=auth_fp,
                        session_id=server_session_id,
                    )
                    session = self._live.get(identity)
                    if (
                        session is not None
                        and session.key == key
                        and session.server is server
                    ):
                        server.last_used_at = time.monotonic()
                        return session
                    if session is None or not session.lock.locked():
                        if session is not None:
                            # The directory, the MCP servers, the approval
                            # preset's server or the active account changed:
                            # reopen the same conversation there.
                            self._live.pop(identity, None)
                            self._by_acp_id.pop(session.acp_id, None)
                            if session.server.session_id == identity:
                                reused_same = server is session.server
                                await self._disconnect(session.server)
                                if reused_same:
                                    server = await self._server(
                                        directory,
                                        skip_permissions=skip_permissions,
                                        auth_fingerprint=auth_fp,
                                        session_id=server_session_id,
                                    )
                            else:
                                await self._close_acp_session(
                                    session.server,
                                    session.acp_id,
                                )
                        return await self._open_session(
                            context=context,
                            identity=identity,
                            directory=directory,
                            key=key,
                            server=server,
                            capabilities=capabilities,
                        )
                    busy = session
            # Wait for the active turn to finish before replacing its
            # session; never acquire session.lock inside _session_lock.
            async with busy.lock:
                pass

    async def _open_session(  # pylint: disable=too-many-arguments
        self,
        *,
        context: HarnessCallContext,
        identity: str,
        directory: str,
        key: tuple[Any, ...],
        server: _Server,
        capabilities: HarnessRuntimeCapabilities,
    ) -> _Session:
        servers = mcp_servers(
            capabilities,
            allow_http=server.mcp_http,
            allow_sse=server.mcp_sse,
        )
        conn = server.conn
        meta = await run_io(_session_meta, context.cwd)
        acp_id = await self._claim_session(context)
        response: Any = None
        try:
            async with asyncio.timeout(_CONNECT_TIMEOUT_SECONDS):
                if acp_id:
                    try:
                        response = await conn.resume_session(
                            cwd=directory,
                            session_id=acp_id,
                            mcp_servers=servers,
                            **meta,
                        )
                    except RequestError as exc:
                        if exc.code == _AUTH_REQUIRED:
                            raise
                        logger.warning(
                            "agy: conversation %s could not be resumed "
                            "(%s); starting a new one",
                            acp_id,
                            exc,
                        )
                        acp_id = None
                if not acp_id:
                    response = await conn.new_session(
                        cwd=directory,
                        mcp_servers=servers,
                        **meta,
                    )
                    acp_id = str(response.session_id)
        except TimeoutError as exc:
            await self._disconnect(server)
            raise SDKError(
                "Antigravity CLI did not open the conversation within "
                f"{_CONNECT_TIMEOUT_SECONDS} seconds.",
            ) from exc
        except OSError as exc:
            await self._disconnect(server)
            raise SDKError(
                f"Antigravity CLI connection failed: {exc}",
            ) from exc
        except RequestError as exc:
            if exc.code == _AUTH_REQUIRED:
                self._account = None
                self._account_checked_at = 0.0
                raise SDKError(_LOGIN_HINT) from exc
            raise SDKError(_request_error_text(exc)) from exc
        if self._sessions.get(identity) != acp_id:
            await self._save_sessions({**self._sessions, identity: acp_id})
        session = _Session(
            acp_id=acp_id,
            key=key,
            server=server,
        )
        self._record_config(session, response)
        session.defaults = dict(session.config)
        self._record_catalog(response)
        self._live[identity] = session
        self._by_acp_id[acp_id] = session
        return session

    @staticmethod
    async def _close_acp_session(server: _Server, acp_id: str) -> None:
        if not server.alive:
            return
        try:
            async with asyncio.timeout(_CANCEL_GRACE_SECONDS):
                await server.conn.close_session(session_id=acp_id)
        except Exception:  # pylint: disable=broad-except
            logger.debug("agy: closing session %s failed", acp_id)

    async def _apply_settings(
        self,
        session: _Session,
        settings: Mapping[str, Any],
    ) -> None:
        model = str(settings.get("model") or "").strip()
        effort = str(settings.get("reasoning_effort") or "").strip()
        offered = session.offered.get("model") or []
        if model and model not in offered:
            # A full model id such as ``gemini-4-carbon-high`` names the
            # model and the thinking level in one.
            base, _, suffix = model.rpartition("-")
            if base in offered and suffix in _EFFORTS:
                model, effort = base, effort or suffix
            else:
                raise SDKError(
                    f"Antigravity does not offer the model {model!r}. "
                    f"Available: {', '.join(offered) or 'none'}.",
                )
        if not model:
            model = session.defaults.get("model", "")
        mode = session.permission_mode
        if mode not in _AGY_MODES:
            # Unknown modes and the bypass preset run in the CLI's default
            # mode; the bypass answers requests on this side.
            mode = "default"
        # The model first: it decides which thinking levels there are.
        await self._set_option_if_needed(session, "model", model)
        if not effort:
            effort = self._default_effort(session)
        await self._set_option_if_needed(session, "thought_level", effort)
        await self._set_option_if_needed(session, "mode", mode)

    async def _set_option_if_needed(
        self,
        session: _Session,
        option: str,
        value: str,
    ) -> None:
        if not value or session.config.get(option) == value:
            return
        if value not in (session.offered.get(option) or []):
            if option == "mode":
                # Going on would leave the session in whatever mode it is in,
                # which may approve more than was asked for.
                raise SDKError(
                    "Antigravity does not offer the permission mode "
                    f"{value!r} for this conversation, so the turn was "
                    "not started.",
                )
            # For example a thinking level the chosen model lacks.
            return
        try:
            response = await session.server.conn.set_config_option(
                config_id=option,
                session_id=session.acp_id,
                value=value,
            )
        except OSError as exc:
            async with self._session_lock:
                await self._disconnect(session.server)
            raise SDKError(
                f"Antigravity CLI connection failed: {exc}",
            ) from exc
        except RequestError as exc:
            raise SDKError(_request_error_text(exc)) from exc
        self._record_config(session, response)

    def _default_effort(self, session: _Session) -> str:
        """Default thinking level when ``reasoning_effort`` is unset."""
        offered = session.offered.get("thought_level") or []
        if not offered:
            return ""
        active_model = session.config.get("model") or ""
        initial_effort = session.defaults.get("thought_level") or ""
        if (
            active_model == session.defaults.get("model")
            and initial_effort in offered
        ):
            return initial_effort
        for entry in self._catalog:
            if (
                entry.id == active_model
                and entry.default_reasoning_effort in offered
            ):
                return str(entry.default_reasoning_effort)
        if "medium" in offered:
            return "medium"
        return offered[0]

    @staticmethod
    def _record_config(session: _Session, response: Any) -> None:
        """Take the session's config options from a response or update."""
        options = getattr(response, "config_options", None)
        if not options:
            return
        config: dict[str, str] = {}
        offered: dict[str, list[str]] = {}
        for option in options:
            option_id = str(getattr(option, "id", "") or "")
            if not option_id or not hasattr(option, "options"):
                continue
            config[option_id] = str(
                getattr(option, "current_value", "") or "",
            )
            offered[option_id] = [
                str(getattr(item, "value", "") or "")
                for item in option.options
                if getattr(item, "value", None)
            ]
        session.config = config
        session.offered = offered

    def _record_catalog(self, response: Any) -> None:
        """Remember the account's models from a session response."""
        full_ids = {
            str(model.model_id)
            for model in getattr(
                getattr(response, "models", None),
                "available_models",
                None,
            )
            or []
        }
        catalog: list[HarnessModel] = []
        for option in getattr(response, "config_options", None) or []:
            if getattr(option, "id", None) != "model":
                continue
            current = str(getattr(option, "current_value", "") or "")
            for item in getattr(option, "options", None) or []:
                value = str(getattr(item, "value", "") or "")
                if not value:
                    continue
                efforts = tuple(
                    effort
                    for effort in _EFFORTS
                    if f"{value}-{effort}" in full_ids
                )
                catalog.append(
                    HarnessModel(
                        id=value,
                        name=str(getattr(item, "name", "") or value),
                        description=str(
                            getattr(item, "description", "") or "",
                        ),
                        is_default=value == current,
                        reasoning_efforts=efforts,
                        default_reasoning_effort=(
                            "medium"
                            if "medium" in efforts
                            else (efforts[0] if efforts else None)
                        ),
                    ),
                )
        if catalog:
            if not any(model.is_default for model in catalog):
                catalog[0] = replace(catalog[0], is_default=True)
            self._catalog = catalog

    # ------------------------------------------------------------------
    # The server process
    # ------------------------------------------------------------------

    async def _current_auth_fingerprint(self) -> str:
        fp = await async_agy_auth_fingerprint(self._auth_fingerprint)
        if (
            fp
            and self._last_auth_fingerprint
            and fp != self._last_auth_fingerprint
        ):
            self._account = None
            self._account_checked_at = 0.0
            self._probe_error = None
            self._probe_failed_at = 0.0
            self._catalog = []
        if fp:
            self._last_auth_fingerprint = fp
        return fp

    def _server_busy(
        self,
        server: _Server,
        *,
        ignore_session: _Session | None = None,
    ) -> bool:
        return any(
            item.server is server
            and item is not ignore_session
            and (item.lock.locked() or item.queue is not None)
            for item in self._live.values()
        )

    async def _evict_idle_isolated_servers(
        self,
        *,
        keep_key: str = "",
        reserve_slot: bool = False,
    ) -> None:
        """Disconnect dead, TTL-expired, or excess LRU idle isolated servers.

        Call with ``_session_lock`` held. Busy servers are never evicted;
        evicted conversations keep their persisted ``acp_id`` so the next
        turn resumes transparently.
        """
        now = time.monotonic()
        idle: list[_Server] = []
        for item in tuple(self._servers.values()):
            if not item.session_id or item.key == keep_key:
                continue
            if self._server_busy(item):
                continue
            if not item.alive or (
                self._idle_isolated_server_ttl > 0
                and now - item.last_used_at >= self._idle_isolated_server_ttl
            ):
                logger.info(
                    "agy: reaping idle isolated server for session %s",
                    item.session_id[:40],
                )
                await self._disconnect(item)
                continue
            idle.append(item)
        if self._max_idle_isolated_servers is None:
            return
        limit = max(
            self._max_idle_isolated_servers - (1 if reserve_slot else 0),
            0,
        )
        if len(idle) <= limit:
            return
        idle.sort(key=lambda item: item.last_used_at)
        for victim in idle[: len(idle) - limit]:
            logger.info(
                "agy: evicting LRU idle isolated server for session %s "
                "(cap=%d)",
                victim.session_id[:40],
                self._max_idle_isolated_servers,
            )
            await self._disconnect(victim)

    async def _server(
        self,
        directory: str,
        *,
        skip_permissions: bool = False,
        timeout: float = _CONNECT_TIMEOUT_SECONDS,
        auth_fingerprint: str = "",
        session_id: str = "",
    ) -> _Server:
        """Return the server started in ``directory``, starting it when
        there is none, it has exited, or an idle server belongs to another
        account. Call with the session lock held."""
        key = _server_key(directory, skip_permissions, session_id=session_id)
        server = self._servers.get(key)
        if server is not None and server.alive:
            if _auth_stale(server, auth_fingerprint):
                if not self._server_busy(server):
                    logger.info(
                        "agy: active account changed for %s; recycling "
                        "agy acp server",
                        directory,
                    )
                    await self._disconnect(server)
                    server = None
                else:
                    server.last_used_at = time.monotonic()
                    return server
            else:
                if auth_fingerprint and not server.auth_fingerprint:
                    server.auth_fingerprint = auth_fingerprint
                server.last_used_at = time.monotonic()
                await self._evict_idle_isolated_servers(
                    keep_key=key,
                    reserve_slot=False,
                )
                return server
        if server is not None:
            await self._disconnect(server)
        await self._evict_idle_isolated_servers(
            keep_key=key,
            reserve_slot=bool(session_id),
        )
        resolution = await self._require_resolution()
        stack = AsyncExitStack()
        try:
            async with asyncio.timeout(timeout):
                conn, process = await stack.enter_async_context(
                    self._spawn(
                        _Client(self),
                        str(resolution.path),
                        "acp",
                        *(
                            [_SKIP_PERMISSIONS_FLAG]
                            if skip_permissions
                            else []
                        ),
                        env=_clean_agy_env(),
                        cwd=directory,
                        transport_kwargs={
                            "limit": _STDIO_LIMIT_BYTES,
                            # The server logs to stderr; an unread pipe
                            # fills up and blocks it.
                            "stderr": asyncio.subprocess.DEVNULL,
                        },
                    ),
                )
                initialized = await conn.initialize(
                    protocol_version=PROTOCOL_VERSION,
                    client_capabilities=ClientCapabilities(),
                    client_info=Implementation(
                        name="qwenpaw-harness-agy",
                        title="QwenPaw",
                        version=_CLIENT_VERSION,
                    ),
                )
            if initialized.protocol_version != PROTOCOL_VERSION:
                raise SDKError(
                    "Antigravity CLI speaks ACP protocol version "
                    f"{initialized.protocol_version}; this backend "
                    f"needs {PROTOCOL_VERSION}.",
                )
        except TimeoutError as exc:
            await _close_stack(stack)
            raise SDKError(
                f"Antigravity CLI did not start within {timeout:g} seconds.",
            ) from exc
        except BaseException:
            await _close_stack(stack)
            raise
        agent_caps = getattr(initialized, "agent_capabilities", None)
        mcp_caps = getattr(agent_caps, "mcp_capabilities", None)
        server = _Server(
            conn=conn,
            process=process,
            stack=stack,
            directory=directory,
            mcp_http=bool(getattr(mcp_caps, "http", False)),
            mcp_sse=bool(getattr(mcp_caps, "sse", False)),
            skip_permissions=skip_permissions,
            key=key,
            auth_fingerprint=auth_fingerprint,
            session_id=session_id,
            last_used_at=time.monotonic(),
        )
        self._servers[key] = server
        return server

    async def _disconnect(self, server: _Server) -> None:
        """Stop one server and drop the sessions that lived on it."""
        key = server.key or server.directory
        if self._servers.get(key) is server:
            del self._servers[key]
        approvals: list[asyncio.Task] = []
        for session_id, session in tuple(self._live.items()):
            if session.server is not server:
                continue
            for task in tuple(session.approvals):
                task.cancel()
                approvals.append(task)
            del self._live[session_id]
            self._by_acp_id.pop(session.acp_id, None)
        if approvals:
            await asyncio.gather(*approvals, return_exceptions=True)
        await _close_stack(server.stack)

    async def _probe_account(self, force: bool = False) -> dict[str, Any]:
        """Check the login by opening a session, and read what it offers.

        Opening a session is the only thing the server refuses when nobody
        is logged in; a session nobody prompts leaves no conversation
        behind.
        """
        auth_fp = await self._current_auth_fingerprint()
        fresh = (
            time.monotonic() - self._account_checked_at
            < _ACCOUNT_CACHE_SECONDS
        )
        if self._account is not None and fresh and not force:
            return dict(self._account)
        if (
            not force
            and self._probe_error is not None
            and time.monotonic() - self._probe_failed_at
            < _PROBE_FAILURE_CACHE_SECONDS
        ):
            raise self._probe_error
        try:
            account = await self._probe_account_now(
                auth_fingerprint=auth_fp,
            )
        except (OSError, RuntimeError, TimeoutError, SDKError) as exc:
            self._probe_error = exc
            self._probe_failed_at = time.monotonic()
            raise
        self._probe_error = None
        return account

    async def _probe_account_now(
        self,
        *,
        auth_fingerprint: str = "",
    ) -> dict[str, Any]:
        async with self._session_lock:
            for item in tuple(self._servers.values()):
                if (
                    item.alive
                    and _auth_stale(item, auth_fingerprint)
                    and not self._server_busy(item)
                ):
                    await self._disconnect(item)
            # Any non-stale running server knows the account; none running
            # means one is started in the backend's own state directory.
            server = next(
                (
                    item
                    for item in self._servers.values()
                    if item.alive and not _auth_stale(item, auth_fingerprint)
                ),
                None,
            )
            started_for_probe = server is None
            if server is None:
                await run_io(
                    self._state_dir.mkdir,
                    parents=True,
                    exist_ok=True,
                )
                server = await self._server(
                    str(self._state_dir),
                    timeout=_PROBE_TIMEOUT_SECONDS,
                    auth_fingerprint=auth_fingerprint,
                )
            elif auth_fingerprint and not server.auth_fingerprint:
                server.auth_fingerprint = auth_fingerprint
            try:
                async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
                    response = await server.conn.new_session(
                        cwd=server.directory,
                    )
                await self._close_acp_session(
                    server,
                    str(response.session_id),
                )
                self._record_catalog(response)
                account: dict[str, Any] = {"type": "google"}
                meta = getattr(response, "field_meta", None) or {}
                tier = (meta.get("antigravity") or {}).get("tier") or {}
                if tier.get("name"):
                    account["plan"] = str(tier["name"])
                self._account = account
                self._account_checked_at = time.monotonic()
                return dict(account)
            except TimeoutError as exc:
                self._account = None
                await self._disconnect(server)
                raise SDKError(
                    "Antigravity CLI did not answer within "
                    f"{_PROBE_TIMEOUT_SECONDS} seconds.",
                ) from exc
            except OSError as exc:
                self._account = None
                await self._disconnect(server)
                raise SDKError(
                    f"Antigravity CLI connection failed: {exc}",
                ) from exc
            except RequestError as exc:
                self._account = None
                if exc.code == _AUTH_REQUIRED:
                    raise _NotLoggedIn() from exc
                raise SDKError(_request_error_text(exc)) from exc
            finally:
                # Do not keep a probe-only daemon running: stopping it saves
                # memory and ensures a fresh process picks up credentials
                # written by `agy acp --login`.
                if started_for_probe and not any(
                    item.server is server for item in self._live.values()
                ):
                    await self._disconnect(server)

    # ------------------------------------------------------------------
    # Callbacks from the server
    # ------------------------------------------------------------------

    def handle_update(self, acp_id: str, update: Any) -> None:
        """Route one ACP ``session/update`` notification to its session."""
        session = self._by_acp_id.get(acp_id)
        if session is None:
            return
        kind = getattr(update, "session_update", None)
        if kind == "config_option_update":
            self._record_config(session, update)
            return
        if kind in {"tool_call", "tool_call_update"}:
            call_id = str(getattr(update, "tool_call_id", "") or "")
            known = session.tools.setdefault(call_id, {})
            for name in ("title", "kind", "raw_input"):
                value = getattr(update, name, None)
                if value is not None:
                    known[name] = value
        if session.queue is not None:
            session.queue.put_nowait(update)

    async def handle_permission(
        self,
        acp_id: str,
        options: list[Any],
        tool_call: Any,
    ) -> RequestPermissionResponse:
        """Resolve one ACP permission request against the live call."""
        session = self._by_acp_id.get(acp_id)
        allow = _option(options, "allow_once", "allow_always")
        reject = _option(options, "reject_once", "reject_always")
        if (
            session is None
            or session.queue is None
            or session.call_context is None
        ):
            logger.warning(
                "agy: permission request for %s session %s was cancelled",
                "an unknown" if session is None else "an idle",
                acp_id,
            )
            return _cancelled()
        if session.permission_mode == BYPASS_PERMISSIONS:
            return _selected(allow) if allow is not None else _cancelled()
        ask = asyncio.ensure_future(
            self._ask_user(session, session.call_context, tool_call),
        )
        session.approvals.add(ask)
        try:
            decision = await ask
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise
            # The turn was cancelled while the user was being asked.
            return _cancelled()
        except Exception:  # pylint: disable=broad-except
            # Nobody could be asked: treat as a refusal so the CLI receives
            # a clean response rather than a protocol error.
            logger.warning(
                "agy: asking for approval failed; refusing",
                exc_info=True,
            )
            decision = "rejected"
        finally:
            session.approvals.discard(ask)
        if decision == "approved" and allow is not None:
            return _selected(allow)
        if decision == "cancelled":
            return _cancelled()
        # Choosing the reject option lets the turn go on and tell the model;
        # "cancelled" would end the turn there.
        return _selected(reject) if reject is not None else _cancelled()

    async def _ask_user(
        self,
        session: _Session,
        call_context: HarnessCallContext,
        tool_call: Any,
    ) -> str:
        """Put one permission request to the user through the plugin SDK."""
        call_id = str(getattr(tool_call, "tool_call_id", "") or "")
        known = session.tools.get(call_id) or {}
        title = str(
            getattr(tool_call, "title", None) or known.get("title") or "tool",
        )
        kind = str(
            getattr(tool_call, "kind", None) or known.get("kind") or "",
        )
        raw_input = getattr(tool_call, "raw_input", None)
        if raw_input is None:
            raw_input = known.get("raw_input")
        summary = HarnessApprovalSummary(
            tool_name=title,
            title=title,
            description=_input_summary(raw_input) or title,
            severity="high" if kind in _RISKY_KINDS else "medium",
            parameters={
                "provider": PROVIDER_ID,
                "provider_item_id": call_id,
                "tool_name": title,
                "tool_kind": kind,
                "input": _json_safe(raw_input),
            },
        )
        return await call_context.request_approval(
            summary,
            timeout=_APPROVAL_TIMEOUT_SECONDS,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _resolution(self) -> AgyBinaryResolution | None:
        try:
            return await run_io(resolve_agy_binary_info, self._binary)
        except OSError as exc:
            raise SDKError(
                "Could not discover Antigravity CLI; "
                f"check its executable path: {exc}",
            ) from exc

    async def _require_resolution(self) -> AgyBinaryResolution:
        resolution = await self._resolution()
        if resolution is None:
            raise SDKError("Antigravity CLI executable was not found.")
        return resolution

    @staticmethod
    def _status(
        resolution: AgyBinaryResolution,
        *,
        authenticated: bool = False,
        account: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> HarnessStatus:
        return HarnessStatus(
            installed=True,
            authenticated=authenticated,
            account=account,
            runtime_path=str(resolution.path),
            runtime_source=resolution.source,
            error=error,
            available=True,
        )


class _NotLoggedIn(Exception):
    """The server refused to open a session without a login."""


def _connection_alive(conn: Any) -> bool:
    """Check whether an ACP connection still looks open."""
    inner = vars(conn).get("_conn") if hasattr(conn, "__dict__") else None
    if inner is not None and hasattr(inner, "__dict__"):
        state = vars(inner)
        if state.get("_disconnected") or state.get("_closed"):
            return False
    return True


async def _close_stack(stack: AsyncExitStack) -> None:
    try:
        await stack.aclose()
    except Exception:  # pylint: disable=broad-except
        logger.debug("agy: stopping the server failed", exc_info=True)


def _clean_agy_env(
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Copy the environment while stripping parent Antigravity IPC vars.

    When QwenPaw is launched from an Antigravity IDE terminal or ``agy``
    subshell, inherited ``ANTIGRAVITY_LS_ADDRESS`` /
    ``ANTIGRAVITY_CSRF_TOKEN`` / ``ANTIGRAVITY_AGENT`` variables make child
    ``agy acp`` processes attach to the parent session instead of booting
    their own backend.
    """
    source = base_env if base_env is not None else os.environ
    return {
        key: value
        for key, value in source.items()
        if not key.startswith("ANTIGRAVITY_")
        or key == "ANTIGRAVITY_APP_DATA_DIR"
    }


def _server_key(
    directory: str,
    skip_permissions: bool,
    *,
    session_id: str = "",
) -> str:
    """Where a server is kept: one per directory, approval kind, and
    (when isolated for per-session MCP servers) session."""
    base = f"{directory}\0unattended" if skip_permissions else directory
    if session_id:
        return f"{base}\0session:{session_id}"
    return base


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(int(raw), 0)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return default


def _auth_stale(server: _Server, auth_fingerprint: str) -> bool:
    """Whether an active-account change makes ``server`` belong to an old login."""
    return bool(
        auth_fingerprint
        and server.auth_fingerprint
        and server.auth_fingerprint != auth_fingerprint,
    )


def _running_calls(
    mapper: AgyEventMapper,
    session: _Session,
) -> dict[str, str]:
    """The tool calls still in progress, each with a line that names it.

    When a turn has ended these are what the CLI left running in the
    background. A command started to keep running, as a server is, is not
    one of them.
    """
    running: dict[str, str] = {}
    for call_id in mapper.unfinished():
        known = session.tools.get(call_id) or {}
        raw_input = known.get("raw_input")
        if isinstance(raw_input, dict) and raw_input.get("IsDaemon") is True:
            continue
        running[call_id] = _running_item(known)
    return running


def _running_item(known: dict[str, Any]) -> str:
    """Name one running tool call: the command line, or tool and args."""
    title = str(known.get("title") or "").strip()
    summary = _input_summary(known.get("raw_input"))
    if str(known.get("kind") or "") == "execute":
        text = title or summary
    else:
        # agy titles a tool it has no kind for "Run <tool>".
        text = f"{title.removeprefix('Run ').strip()} {summary}".strip()
    text = " ".join(text.split()) or "a tool call"
    if len(text) > _MAX_RUNNING_ITEM_CHARS:
        text = text[:_MAX_RUNNING_ITEM_CHARS] + "…"
    return f"`{text}`"


def _with_command_note(prompt: str) -> str:
    """The prompt, with the host's note when it starts with a CLI command
    that needs one."""
    if not prompt.startswith("/"):
        return prompt
    name, _, arguments = prompt[1:].partition(" ")
    name = name.strip().lower()
    note = _COMMAND_NOTES.get(name)
    if note is None:
        return prompt
    first = arguments.split(None, 1)[0].lower() if arguments.strip() else ""
    if first in _COMMAND_NOTE_EXEMPT.get(name, set()):
        return prompt
    return f"{prompt}\n\n{note}"


def _session_meta(directory: Path) -> dict[str, Any]:
    """The ``_meta`` a session is opened with (the SDK takes it as
    keyword arguments): the host rules and the agent's memory files.

    Reads files, so call it off the event loop.
    """
    sections = [_HOST_RULES]
    rest = _agents_rest(directory)
    if rest:
        sections.append(
            f"{_AGENTS_REST_RULES}\n\n<AGENTS.md-rest>\n{rest}\n"
            "</AGENTS.md-rest>",
        )
    memory = _workspace_memory(directory)
    if memory:
        sections.append(f"{_MEMORY_RULES}\n\n{memory}")
    return {
        "antigravity": {"systemPrompt": {"append": "\n\n".join(sections)}},
    }


def _agents_rest(directory: Path) -> str:
    """The part of the workspace's AGENTS.md that the CLI does not load."""
    try:
        data = (directory / _AGENTS_FILE).read_bytes()
    except OSError:
        return ""
    if len(data) <= _CLI_AGENTS_BYTES:
        return ""
    # The CLI keeps whole lines: what it drops starts after the last line
    # break inside its limit.
    line_break = data.rfind(b"\n", 0, _CLI_AGENTS_BYTES)
    start = line_break + 1 if line_break >= 0 else _CLI_AGENTS_BYTES
    text = data[start:].decode("utf-8", errors="replace").strip()
    if len(text) > _MAX_AGENTS_REST_CHARS:
        text = (
            text[:_MAX_AGENTS_REST_CHARS]
            + f"\n… ({_AGENTS_FILE} is longer still; read the file for the "
            "rest)"
        )
    return text


def _workspace_memory(directory: Path) -> str:
    """The workspace's memory files, each under its own tag."""
    parts: list[str] = []
    for name in _MEMORY_FILES:
        try:
            text = (directory / name).read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue
        text = text.strip()
        if not text:
            continue
        if len(text) > _MAX_MEMORY_FILE_CHARS:
            text = (
                text[:_MAX_MEMORY_FILE_CHARS]
                + f"\n… ({name} is longer; read the file for the rest)"
            )
        parts.append(f"<{name}>\n{text}\n</{name}>")
    return "\n\n".join(parts)


def _error(text: str) -> HarnessEvent:
    return HarnessEvent(kind=HarnessEventKind.ERROR, text=text)


def _request_error_text(exc: RequestError) -> str:
    """The server's message, with the detail it puts in ``data``."""
    text = str(exc) or "Antigravity CLI reported an error."
    data = exc.data
    detail = ""
    if isinstance(data, dict):
        detail = str(data.get("details") or data.get("message") or "")
    elif isinstance(data, str):
        detail = data
    if detail and detail not in text:
        text = f"{text}: {detail}"
    return text


def _sniff_image_mime(data: bytes) -> str | None:
    """Detect image MIME type from magic bytes when available."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _file_url_to_local_path(raw: str) -> str | None:
    """Convert a ``file://`` URL to a local filesystem path."""
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "file":
        return None
    if parsed.netloc and parsed.netloc not in {"", "localhost"}:
        # UNC path on Windows (file://server/share/path).
        return f"//{parsed.netloc}{url2pathname(parsed.path)}"
    return url2pathname(parsed.path)


def _local_path(path: Path) -> Path:
    raw = str(path)
    if raw.startswith("file:"):
        local = _file_url_to_local_path(raw)
        if local:
            return Path(local).expanduser()
    return path.expanduser()


def _parse_data_url(data_url: str) -> tuple[str, str]:
    header, sep, payload = data_url.partition(",")
    if not sep or not payload:
        raise SDKError("Invalid inline image data URL.")
    meta = header[5:]  # strip "data:"
    parts = [part.strip() for part in meta.split(";") if part.strip()]
    mime_type = (
        parts[0]
        if parts and "/" in parts[0] and parts[0] != "base64"
        else "image/png"
    )
    if "base64" in parts:
        return mime_type, payload.strip()
    return mime_type, base64.b64encode(unquote_to_bytes(payload)).decode(
        "ascii",
    )


def _resolved(path: Path) -> Path:
    return _local_path(path).resolve(strict=False)


def _option(options: list[Any], *kinds: str) -> Any:
    """The first offered option of the first kind that is offered."""
    for kind in kinds:
        for option in options or []:
            if getattr(option, "kind", None) == kind:
                return option
    return None


def _selected(option: Any) -> RequestPermissionResponse:
    return RequestPermissionResponse(
        outcome=AllowedOutcome(
            option_id=str(option.option_id),
            outcome="selected",
        ),
    )


def _cancelled() -> RequestPermissionResponse:
    return RequestPermissionResponse(
        outcome=DeniedOutcome(outcome="cancelled"),
    )


def _json_safe(value: Any) -> Any:
    """Ensure approval payloads contain only JSON-serializable values."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    try:
        return json.loads(json.dumps(value, default=str, allow_nan=False))
    except (TypeError, ValueError):
        return str(value)


def _input_summary(raw_input: Any) -> str:
    """What the tool is about to do, for the approval card."""
    if isinstance(raw_input, dict):
        for key in ("CommandLine", "command", "command_line"):
            value = raw_input.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return json.dumps(raw_input, ensure_ascii=False, default=str)[:2000]
    if raw_input is None:
        return ""
    return str(raw_input)[:2000]


__all__ = ["AgyBackend", "BYPASS_PERMISSIONS", "PROVIDER_ID", "PROVIDER_NAME"]
