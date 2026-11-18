# -*- coding: utf-8 -*-
"""Runner-safe Twilio ConversationRelay ingress boundary."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import time
from typing import Any, Protocol
from urllib.parse import parse_qs, quote, urlsplit
import uuid

import aiohttp
from aiohttp import web

from qwenpaw.channel_protocol import PlatformAuthenticationError
from .runner_twilio_manager import (
    RunnerTwilioManager,
    TwilioAuthenticationError,
    VoiceWebhookSnapshot,
)
from .twiml import build_conversation_relay_twiml, build_error_twiml

logger = logging.getLogger(__name__)

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_TOKEN_TTL_S = 60.0
_DEFAULT_MAX_TOKENS = 100
_DEFAULT_MAX_CONNECTIONS = 64
_DEFAULT_EVENT_QUEUE_SIZE = 32
_DEFAULT_SHUTDOWN_TIMEOUT_S = 5.0
_TERMINAL_STATUSES = frozenset(
    {"busy", "failed", "canceled", "completed", "no-answer"},
)


class RequestValidator(Protocol):
    """Describe the Twilio request validator used by the platform."""

    def validate(
        self,
        uri: str,
        params: Mapping[str, str],
        signature: str,
    ) -> bool:
        """Return whether a Twilio request signature is valid."""


@dataclass(frozen=True)
class TunnelInfo:
    """Describe the public URLs returned by a tunnel driver."""

    public_url: str
    public_wss_url: str


class TunnelDriver(Protocol):
    """Describe the tunnel lifecycle used by the Voice platform."""

    async def start(self, local_port: int) -> TunnelInfo:
        """Expose one local listener and return its public URLs."""

    async def stop(self) -> None:
        """Stop the public tunnel."""


class RunnerTwilioWebhookManager(Protocol):
    """Describe the Twilio phone-number configuration operation."""

    async def fetch_voice_webhook(
        self,
        phone_number_sid: str,
    ) -> VoiceWebhookSnapshot:
        """Fetch the exact Voice webhook fields."""

    async def apply_voice_webhook(
        self,
        phone_number_sid: str,
        snapshot: VoiceWebhookSnapshot,
    ) -> None:
        """Apply the exact Voice webhook fields."""


class VoicePlatformError(RuntimeError):
    """Report a platform result with a classified side-effect risk."""

    def __init__(
        self,
        reason_code: str,
        *,
        side_effect_possible: bool = False,
        retryable: bool = False,
    ) -> None:
        self.retryable = retryable
        self.reason_code = reason_code
        self.side_effect_possible = side_effect_possible
        super().__init__(reason_code)


@dataclass(frozen=True)
class VoiceEndpoint:
    """Describe the actual Runner-owned Voice listener."""

    host: str
    port: int
    readiness: str
    public_base_url: str | None
    bound_externally: bool
    auth_required: bool = True


@dataclass(frozen=True)
class VoiceNativeEvent:
    """Carry one ordered native Voice event to the Driver."""

    event_id: str
    event_kind: str
    connection_id: str
    generation: int
    sequence: int
    session_binding: str
    platform_session_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _TokenRecord:
    call_sid: str
    expires_at: float
    from_number: str = ""
    to_number: str = ""


@dataclass(eq=False)
class _Admission:
    task: asyncio.Task[Any]
    transport: asyncio.Transport | None
    websocket: web.WebSocketResponse | None = None


@dataclass(eq=False)
class _Connection:
    connection_id: str
    expected_call_sid: str
    generation: int
    websocket: web.WebSocketResponse
    queue: asyncio.Queue[VoiceNativeEvent | None]
    transport: asyncio.Transport | None
    from_number: str = ""
    to_number: str = ""
    platform_session_id: str = ""
    session_binding: str = ""
    sequence: int = 0
    setup_received: bool = False
    close_enqueued: bool = False
    cleaned: bool = False
    end_attempted: bool = False
    worker: asyncio.Task[None] | None = None
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    state_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    cleanup_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


ValidatorFactory = Callable[[str], RequestValidator]
TunnelFactory = Callable[[], TunnelDriver]
RunnerTwilioManagerFactory = Callable[
    [str, str],
    RunnerTwilioWebhookManager,
]
EventHandler = Callable[[VoiceNativeEvent], Awaitable[None]]
EndpointHandler = Callable[
    [str, VoiceEndpoint | None],
    Awaitable[None],
]


def _default_validator_factory(auth_token: str) -> RequestValidator:
    """Load Twilio's validator only inside the Runner platform path."""
    from twilio.request_validator import RequestValidator as Validator

    return Validator(auth_token)


def _default_tunnel_factory() -> TunnelDriver:
    """Load the tunnel implementation only inside the Runner path."""
    from qwenpaw.tunnel import CloudflareTunnelDriver

    return CloudflareTunnelDriver()


def _default_twilio_manager_factory(
    account_sid: str,
    auth_token: str,
) -> RunnerTwilioWebhookManager:
    """Create the Runner-owned Twilio API wrapper."""
    return RunnerTwilioManager(account_sid, auth_token)


def _normalize_host(value: object) -> str:
    """Normalize one listener host with a loopback default."""
    if not isinstance(value, str):
        raise ValueError("Voice ingress_host must be a string")
    return value.strip().strip("[]") or _DEFAULT_HOST


def _is_external_host(host: str) -> bool:
    """Return whether a bind host exposes the listener externally."""
    normalized = host.strip().lower()
    if normalized == "localhost":
        return False
    try:
        address = ipaddress.ip_address(normalized.split("%", 1)[0])
    except ValueError:
        return True
    return not address.is_loopback


async def _resolve_dynamic_bind_host(host: str, port: int) -> str:
    """Resolve a dynamic hostname to one deterministic socket address."""
    if port != 0:
        return host
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        return host
    except ValueError:
        pass
    try:
        results = await asyncio.get_running_loop().getaddrinfo(
            host,
            0,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError(
            f"Voice ingress_host cannot be resolved: {host}",
        ) from exc
    candidates: set[tuple[int, str]] = set()
    for family, _, _, _, address in results:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        resolved = str(address[0])
        if family == socket.AF_INET6 and len(address) > 3 and address[3]:
            resolved = f"{resolved}%{address[3]}"
        priority = 0 if family == socket.AF_INET else 1
        candidates.add((priority, resolved))
    if not candidates:
        raise ValueError(f"Voice ingress_host has no address: {host}")
    return min(candidates)[1]


class VoicePlatform:  # pylint: disable=too-many-instance-attributes
    """Own Twilio HTTP/WebSocket ingress and active call connections."""

    def __init__(
        self,
        *,
        validator_factory: ValidatorFactory | None = None,
        tunnel_factory: TunnelFactory | None = None,
        twilio_manager_factory: RunnerTwilioManagerFactory | None = None,
        clock: Callable[[], float] | None = None,
        token_factory: Callable[[], str] | None = None,
        token_ttl_s: float = _DEFAULT_TOKEN_TTL_S,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        max_connections: int = _DEFAULT_MAX_CONNECTIONS,
        event_queue_size: int = _DEFAULT_EVENT_QUEUE_SIZE,
        shutdown_timeout_s: float = _DEFAULT_SHUTDOWN_TIMEOUT_S,
    ) -> None:
        if token_ttl_s <= 0:
            raise ValueError("Voice token_ttl_s must be positive")
        if max_tokens <= 0:
            raise ValueError("Voice max_tokens must be positive")
        if max_connections <= 0:
            raise ValueError("Voice max_connections must be positive")
        if event_queue_size <= 0:
            raise ValueError("Voice event_queue_size must be positive")
        if shutdown_timeout_s <= 0:
            raise ValueError("Voice shutdown_timeout_s must be positive")
        self._validator_factory = (
            validator_factory or _default_validator_factory
        )
        self._tunnel_factory = tunnel_factory or _default_tunnel_factory
        self._twilio_manager_factory = (
            twilio_manager_factory or _default_twilio_manager_factory
        )
        self._clock = clock or time.monotonic
        self._token_factory = token_factory or (
            lambda: secrets.token_urlsafe(32)
        )
        self._token_ttl_s = token_ttl_s
        self._max_tokens = max_tokens
        self._max_connections = max_connections
        self._event_queue_size = event_queue_size
        self._shutdown_timeout_s = shutdown_timeout_s
        self._configured_host = _DEFAULT_HOST
        self._bind_host = _DEFAULT_HOST
        self._configured_port = 0
        self._generation = 0
        self._config: dict[str, Any] = {}
        self._validator: RequestValidator | None = None
        self._twilio_manager: RunnerTwilioWebhookManager | None = None
        self._tunnel: TunnelDriver | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._app: web.Application | None = None
        self._event_handler: EventHandler | None = None
        self._endpoint_handler: EndpointHandler | None = None
        self._tokens: OrderedDict[str, _TokenRecord] = OrderedDict()
        self._token_lock = asyncio.Lock()
        self._admission_lock = asyncio.Lock()
        self._admissions: dict[asyncio.Task[Any], _Admission] = {}
        self._connections: dict[str, _Connection] = {}
        self._calls: dict[str, _Connection] = {}
        self._bindings: dict[str, _Connection] = {}
        self._accepting = False
        self._stopping = False
        self._public_base_url: str | None = None
        self._public_wss_url: str | None = None
        self._last_endpoint: VoiceEndpoint | None = None
        self._forwarding: dict[str, Any] | None = None
        self._runner_backpressure_total = 0
        self._connection_overload_total = 0
        self._unknown_status_total = 0
        self._initialize_startup_transaction()

    def _initialize_startup_transaction(self) -> None:
        """Initialize one in-memory provisional webhook transaction."""
        self._endpoint_registration_attempted = False
        self._webhook_previous: VoiceWebhookSnapshot | None = None
        self._webhook_candidate: VoiceWebhookSnapshot | None = None
        self._webhook_rollback_eligible = False
        self._webhook_transaction_state = "idle"
        self._webhook_rollback_reason: str | None = None
        self._startup_failure_reason: str | None = None
        self._endpoint_cleanup_reason: str | None = None
        self._startup_aborting = False
        self._startup_task: asyncio.Task[Any] | None = None
        self._startup_settled = asyncio.Event()
        self._startup_settled.set()
        self._startup_abort_task: asyncio.Task[None] | None = None
        self._cleanup_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None
        self._cleanup_complete = False
        self._cleanup_tasks: set[asyncio.Task[Any]] = set()
        self._cleanup_operations: dict[tuple[int, str], asyncio.Task[Any]] = {}

    @property
    def listen_port(self) -> int | None:
        """Return the single actual listener port."""
        site = self._site
        server = getattr(site, "_server", None)
        if server is None:
            return None
        ports = {
            int(bound_socket.getsockname()[1])
            for bound_socket in server.sockets or ()
        }
        if len(ports) != 1:
            return None
        return ports.pop()

    @property
    def endpoint(self) -> VoiceEndpoint | None:
        """Return the most recently acknowledged endpoint."""
        return self._last_endpoint

    @property
    def cleanup_complete(self) -> bool:
        """Return whether all local ingress resources were released."""
        return self._cleanup_complete

    async def prepare(
        self,
        config: Mapping[str, Any],
        secret: Mapping[str, str],
    ) -> None:
        """Validate config and consume the Twilio auth token."""
        if "twilio_auth_token" in config:
            raise ValueError(
                "Voice config snapshot contains twilio_auth_token",
            )
        host = _normalize_host(config.get("ingress_host", _DEFAULT_HOST))
        port = config.get("ingress_port", 0)
        if (
            not isinstance(port, int)
            or isinstance(port, bool)
            or not 0 <= port <= 65535
        ):
            raise ValueError(
                "Voice ingress_port must be between 0 and 65535",
            )
        account_sid = str(config.get("twilio_account_sid") or "")
        phone_number_sid = str(config.get("phone_number_sid") or "")
        auth_token = secret.get("twilio_auth_token", "")
        if not account_sid:
            raise ValueError("Voice twilio_account_sid is required")
        if not phone_number_sid:
            raise ValueError("Voice phone_number_sid is required")
        if not isinstance(auth_token, str) or not auth_token:
            raise ValueError("Voice twilio_auth_token is required")
        self._configured_host = host
        self._bind_host = await _resolve_dynamic_bind_host(host, port)
        self._configured_port = port
        self._config = dict(config)
        self._validator = self._validator_factory(auth_token)
        manager = self._twilio_manager_factory(
            account_sid,
            auth_token,
        )
        self._twilio_manager = manager
        self._initialize_startup_transaction()
        try:
            await manager.fetch_voice_webhook(phone_number_sid)
        except TwilioAuthenticationError as exc:
            raise PlatformAuthenticationError(
                "Twilio authentication failed",
            ) from exc

    async def start(
        self,
        event_handler: EventHandler,
        endpoint_handler: EndpointHandler,
        generation: int,
    ) -> None:
        """Build one provisional ingress and external webhook transaction."""
        if self._validator is None or self._twilio_manager is None:
            raise RuntimeError("Voice platform is not prepared")
        if self._runner is not None:
            return
        self._event_handler = event_handler
        self._endpoint_handler = endpoint_handler
        self._generation = generation
        self._stopping = False
        self._startup_aborting = False
        self._startup_abort_task = None
        self._startup_task = asyncio.current_task()
        self._startup_settled.clear()
        try:
            await self._start_server()
            self._endpoint_registration_attempted = True
            await self._report_endpoint("register", "starting")
            tunnel = self._tunnel_factory()
            self._tunnel = tunnel
            if self._forwarding is None:
                raise VoicePlatformError("VOICE_HOST_FORWARDING_UNAVAILABLE")
            tunnel_info = await tunnel.start(self._forwarding["host_port"])
            self._public_base_url = tunnel_info.public_url.rstrip("/")
            self._public_wss_url = tunnel_info.public_wss_url.rstrip("/")
            await self._begin_twilio_transaction()
            await self._report_endpoint("update", "ready")
            self._webhook_transaction_state = "provisional"
        except BaseException:
            self.mark_startup_failed("STARTUP_FAILED")
            self._startup_settled.set()
            await self._abort_startup_resilient()
            raise
        finally:
            self._startup_task = None
            self._startup_settled.set()

    async def _start_server(self) -> None:
        """Create the three Runner-owned Twilio routes."""
        app = web.Application()
        app.router.add_post("/voice/incoming", self._handle_incoming)
        app.router.add_get("/voice/ws", self._handle_websocket)
        app.router.add_post(
            "/voice/status-callback",
            self._handle_status_callback,
        )
        runner = web.AppRunner(app)
        self._app, self._runner = app, runner
        await runner.setup()
        site = web.TCPSite(runner, self._bind_host, self._configured_port)
        self._site = site
        await site.start()
        if self.listen_port is None:
            raise VoicePlatformError("INGRESS_ENDPOINT_AMBIGUOUS")

    async def _begin_twilio_transaction(self) -> None:
        """Snapshot the remote webhook and apply one provisional candidate."""
        manager = self._twilio_manager
        base_url = self._public_base_url
        if manager is None or base_url is None:
            raise RuntimeError("Voice public endpoint is unavailable")
        phone_number_sid = str(self._config["phone_number_sid"])
        self._webhook_transaction_state = "snapshot_pending"
        previous = await manager.fetch_voice_webhook(phone_number_sid)
        candidate = VoiceWebhookSnapshot(
            voice_url=self._public_route(base_url, "/voice/incoming"),
            voice_method="POST",
            status_callback=self._public_route(
                base_url,
                "/voice/status-callback",
            ),
            status_callback_method="POST",
        )
        self._webhook_previous = previous
        self._webhook_candidate = candidate
        self._webhook_rollback_eligible = True
        self._webhook_transaction_state = "candidate_pending"
        await manager.apply_voice_webhook(phone_number_sid, candidate)

    def confirm_startup(self) -> None:
        """Commit the provisional webhook at response publication."""
        if self._startup_aborting:
            return
        if self._webhook_transaction_state != "provisional":
            return
        self._webhook_transaction_state = "confirmed"
        self._accepting = True

    def complete_startup(self) -> None:
        """Release rollback evidence only after connected publication."""
        if (
            self._startup_aborting
            or self._webhook_transaction_state != "confirmed"
        ):
            raise VoicePlatformError("VOICE_STARTUP_NOT_CONFIRMED")
        self._webhook_rollback_eligible = False
        self._webhook_previous = None
        self._webhook_candidate = None
        self._webhook_transaction_state = "committed"

    def mark_startup_failed(self, reason_code: str) -> None:
        """Fence ingress synchronously before asynchronous compensation."""
        if self._webhook_transaction_state == "committed":
            return
        self._startup_aborting = True
        self._accepting = False
        if not self._startup_failure_reason:
            self._startup_failure_reason = reason_code

    async def abort_startup(self, reason_code: str) -> None:
        """Finish provisional compensation despite caller cancellation."""
        self.mark_startup_failed(reason_code)
        startup_task = self._startup_task
        if (
            startup_task is not None
            and startup_task is not asyncio.current_task()
        ):
            await self._wait_resilient(self._startup_settled.wait())
        await self._abort_startup_resilient()

    async def _abort_startup_resilient(self) -> None:
        """Share current compensation and retry incomplete cleanup."""
        if self._cleanup_complete:
            return
        task = self._startup_abort_task
        if task is None or task.done():
            task = asyncio.create_task(self._abort_startup_resources())
            self._startup_abort_task = task
        try:
            await self._wait_resilient(task)
        finally:
            if self._startup_abort_task is task:
                self._startup_abort_task = None

    async def _abort_startup_resources(self) -> None:
        """Rollback Twilio, withdraw endpoint, then close resources."""
        await self._rollback_twilio()
        await self._withdraw_endpoint()
        await self._close_resources_once(None)

    async def _rollback_twilio(self) -> None:
        """Restore the snapshot only while this candidate still owns it."""
        if not self._webhook_rollback_eligible:
            return
        manager = self._twilio_manager
        previous = self._webhook_previous
        candidate = self._webhook_candidate
        if manager is None or previous is None or candidate is None:
            self._webhook_transaction_state = "rollback_unknown"
            self._webhook_rollback_reason = "WEBHOOK_SNAPSHOT_UNAVAILABLE"
            return
        phone_number_sid = str(self._config["phone_number_sid"])
        try:
            current = await manager.fetch_voice_webhook(phone_number_sid)
        except BaseException:
            self._webhook_transaction_state = "rollback_unknown"
            self._webhook_rollback_reason = "WEBHOOK_OWNERSHIP_UNKNOWN"
            logger.error(
                "voice: Twilio rollback ownership check failed",
                exc_info=True,
            )
            return
        if current == previous:
            self._webhook_transaction_state = "rolled_back"
            self._webhook_rollback_eligible = False
            return
        if current != candidate:
            self._webhook_transaction_state = "rollback_skipped_owner_changed"
            self._webhook_rollback_reason = "WEBHOOK_OWNER_CHANGED"
            self._webhook_rollback_eligible = False
            return
        try:
            await manager.apply_voice_webhook(phone_number_sid, previous)
        except BaseException:
            self._webhook_transaction_state = "rollback_failed"
            self._webhook_rollback_reason = "WEBHOOK_RESTORE_FAILED"
            logger.error(
                "voice: Twilio webhook restore failed",
                exc_info=True,
            )
            return
        self._webhook_transaction_state = "rolled_back"
        self._webhook_rollback_eligible = False

    async def _withdraw_endpoint(self) -> None:
        """Wait for candidate endpoint withdrawal before local cleanup."""
        if not self._endpoint_registration_attempted:
            return
        handler = self._endpoint_handler
        if handler is None:
            self._endpoint_cleanup_reason = "ENDPOINT_WITHDRAW_FAILED"
            return
        try:
            await handler("unregister", None)
            self._endpoint_registration_attempted = False
            self._last_endpoint = None
            self._endpoint_cleanup_reason = None
        except BaseException:
            self._endpoint_cleanup_reason = "ENDPOINT_WITHDRAW_FAILED"
            logger.error(
                "voice: candidate endpoint withdrawal failed",
                exc_info=True,
            )

    async def _wait_resilient(self, awaitable: Awaitable[Any]) -> Any:
        """Wait for cleanup settlement while preserving cancellation."""
        task = asyncio.ensure_future(awaitable)
        cancellation: asyncio.CancelledError | None = None
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as exc:
                cancellation = exc
        result = task.result()
        if cancellation is not None:
            raise cancellation
        return result

    async def _report_endpoint(
        self,
        operation: str,
        readiness: str,
    ) -> None:
        """Publish the actual listener state before admitting traffic."""
        handler = self._endpoint_handler
        port = self.listen_port
        if handler is None or port is None:
            raise RuntimeError("Voice endpoint handler is unavailable")
        endpoint = VoiceEndpoint(
            host=self._configured_host,
            port=port,
            readiness=readiness,
            public_base_url=self._public_base_url,
            bound_externally=_is_external_host(self._configured_host),
        )
        await handler(operation, endpoint)
        self._last_endpoint = endpoint

    async def stop_accepting(self) -> None:
        """Fence listener admission and close provisional handshakes."""
        async with self._admission_lock:
            self._accepting = False
            admissions = tuple(self._admissions.values())
        site = self._site
        server = getattr(site, "_server", None)
        if server is not None:
            server.close()
        site_stopped = site is None
        if site is not None:
            try:
                await site.stop()
                site_stopped = True
            except Exception:
                logger.debug(
                    "voice: listener stop failed",
                    exc_info=True,
                )
        if site_stopped and self._site is site:
            self._site = None
        current = asyncio.current_task()
        tasks: list[asyncio.Task[Any]] = []
        for admission in admissions:
            task = admission.task
            if task is current or task.done():
                continue
            task.cancel()
            transport = admission.transport
            if transport is not None:
                transport.abort()
            tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self, *, deadline: float | None = None) -> None:
        """Close listener, calls, tunnel, and worker tasks idempotently."""
        self._stopping = True
        self._accepting = False
        if self._webhook_transaction_state != "committed":
            self.mark_startup_failed("STARTUP_CLOSED")
            await self.abort_startup("STARTUP_CLOSED")
            return
        await self._withdraw_endpoint()
        await self._close_resources_once(deadline)

    async def _close_resources_once(
        self,
        deadline: float | None,
    ) -> None:
        """Share cleanup and retry once after joining an expired attempt."""
        retry_after_shared = False
        loop = asyncio.get_running_loop()
        while True:
            async with self._cleanup_lock:
                if self._cleanup_complete:
                    return
                task = self._close_task
                if task is None or task.done():
                    if deadline is not None and loop.time() >= deadline:
                        return
                    task = asyncio.create_task(
                        self._close_resources(deadline),
                    )
                    self._close_task = task
                    owns_attempt = True
                else:
                    owns_attempt = False
            try:
                await self._wait_resilient(task)
            finally:
                async with self._cleanup_lock:
                    if self._close_task is task:
                        self._close_task = None
            if self._cleanup_complete or owns_attempt or retry_after_shared:
                return
            if deadline is not None and loop.time() >= deadline:
                return
            retry_after_shared = True

    async def _close_resources(self, deadline: float | None) -> None:
        """Run forced cleanup within one absolute deadline."""
        loop = asyncio.get_running_loop()
        shutdown_deadline = loop.time() + self._shutdown_timeout_s
        if deadline is not None:
            shutdown_deadline = min(shutdown_deadline, deadline)
        await self.stop_accepting()
        async with self._token_lock:
            self._tokens.clear()
        connections = tuple(self._connections.values())
        tasks = tuple(
            asyncio.create_task(
                self._close_connection(connection, shutdown_deadline),
            )
            for connection in connections
        )
        await self._wait_tasks_until(tasks, shutdown_deadline)
        workers = tuple(
            connection.worker
            for connection in connections
            if connection.worker is not None
        )
        await self._wait_tasks_until(workers, shutdown_deadline)
        tunnel = self._tunnel
        if tunnel is not None:
            stopped = await self._run_until(
                tunnel.stop,
                shutdown_deadline,
            )
            if stopped and self._tunnel is tunnel:
                self._tunnel = None
        runner = self._runner
        if runner is not None:
            cleaned = await self._run_until(
                runner.cleanup,
                shutdown_deadline,
            )
            if cleaned and self._runner is runner:
                self._runner = None
                self._site = None
                self._app = None
                # Only settled sockets/workers may release their bindings.
                # An ignored cancellation must retain the original resource.
                for connection in tuple(self._connections.values()):
                    worker = connection.worker
                    if connection.websocket.closed and (
                        worker is None or worker.done()
                    ):
                        self._connections.pop(connection.connection_id, None)
                        if (
                            self._calls.get(connection.platform_session_id)
                            is connection
                        ):
                            self._calls.pop(
                                connection.platform_session_id,
                                None,
                            )
                        self._bindings.pop(connection.session_binding, None)
        if self._tunnel is None and self._runner is None:
            self._public_base_url = None
            self._public_wss_url = None
        manager = self._twilio_manager
        if not self._webhook_rollback_eligible and manager is not None:
            close = getattr(manager, "close", None)
            if close is None or await self._run_until(
                close,
                shutdown_deadline,
            ):
                self._twilio_manager = None
        self._cleanup_complete = (
            self._site is None
            and self._tunnel is None
            and self._runner is None
            and not self._admissions
            and not self._connections
            and not any(not task.done() for task in self._cleanup_tasks)
            and not self._cleanup_operations
            and not self._endpoint_registration_attempted
            and not self._webhook_rollback_eligible
            and self._twilio_manager is None
        )

    async def _run_until(
        self,
        operation: Callable[[], Awaitable[Any]],
        deadline: float,
    ) -> bool:
        """Run cleanup work within one absolute deadline."""
        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        if remaining <= 0:
            return False
        key = (
            id(getattr(operation, "__self__", operation)),
            operation.__name__,
        )
        task = self._cleanup_operations.get(key)
        if task is None:
            task = asyncio.create_task(operation())
            self._cleanup_operations[key] = task
        done, _ = await asyncio.wait((task,), timeout=remaining)
        if not done:
            task.cancel()
            return False
        self._cleanup_operations.pop(key, None)
        if task.cancelled():
            return False
        try:
            task.result()
        except Exception:
            return False
        return True

    async def _wait_tasks_until(
        self,
        tasks: tuple[asyncio.Task[Any], ...],
        deadline: float,
    ) -> None:
        """Bound the wait while retaining cancellation-resistant tasks."""
        if not tasks:
            return
        self._cleanup_tasks.update(tasks)
        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        done, pending = await asyncio.wait(tasks, timeout=remaining)
        for task in pending:
            task.cancel()
        for task in done:
            self._consume_task(task)
            self._cleanup_tasks.discard(task)
        # Give cooperative cancellation a turn; never await an ignored
        # cancellation beyond the shutdown budget or discard its reference.
        await asyncio.sleep(0)
        for connection in self._connections.values():
            worker = connection.worker
            if (
                worker is not None
                and worker.done()
                and connection.websocket.closed
            ):
                while not connection.queue.empty():
                    connection.queue.get_nowait()
                    connection.queue.task_done()
        for task in tuple(self._cleanup_tasks):
            if task.done():
                self._consume_task(task)
                self._cleanup_tasks.discard(task)

    @staticmethod
    def _consume_task(task: asyncio.Future[Any]) -> None:
        """Consume one cleanup result without leaking task failures."""
        if task.cancelled():
            return
        try:
            task.exception()
        except Exception:
            return

    def set_forwarding(self, value: object) -> None:
        """Consume the trusted endpoint ACK; never infer a host URL/port."""
        fields = {
            "route_query_key",
            "route_selector",
            "host_port",
            "paths",
            "bridge_token",
        }
        paths = {"/voice/incoming", "/voice/ws", "/voice/status-callback"}
        if (
            not isinstance(value, dict)
            or set(value) != fields
            or value.get("route_query_key") != "_qp_endpoint"
            or type(value.get("host_port")) is not int
            or not 1 <= value["host_port"] <= 65535
            or not isinstance(value.get("paths"), list)
            or any(not isinstance(path, str) for path in value["paths"])
            or len(value["paths"]) != 3
            or set(value["paths"]) != paths
            or any(
                not isinstance(value.get(key), str) or not value[key]
                for key in ("route_selector", "bridge_token")
            )
        ):
            raise VoicePlatformError("VOICE_HOST_FORWARDING_UNAVAILABLE")
        if self._forwarding is not None and self._forwarding != value:
            raise VoicePlatformError("VOICE_HOST_FORWARDING_CHANGED")
        self._forwarding = dict(value)

    def _public_route(self, base: str, path: str) -> str:
        binding = self._forwarding
        if binding is None or path not in binding["paths"]:
            raise VoicePlatformError("VOICE_HOST_FORWARDING_UNAVAILABLE")
        return (
            base
            + path
            + "?"
            + binding["route_query_key"]
            + "="
            + quote(binding["route_selector"], safe="")
        )

    def _forwarded_url(self, request: web.Request) -> str | None:
        binding = self._forwarding
        if binding is None:
            return None
        supplied = request.headers.get("X-Qwenpaw-Ingress-Token", "")
        if not hmac.compare_digest(
            supplied.encode(),
            binding["bridge_token"].encode(),
        ):
            return None
        original = request.headers.get("X-Qwenpaw-Ingress-Original-URL", "")
        try:
            parsed = urlsplit(original)
        except ValueError:
            return None
        if (
            parsed.scheme not in {"http", "https", "ws", "wss"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            return None
        raw_target = parsed.path + ("?" + parsed.query if parsed.query else "")
        if (
            parsed.path not in binding["paths"]
            or raw_target != request.raw_path
        ):
            return None
        selectors = parse_qs(parsed.query, keep_blank_values=True).get(
            binding["route_query_key"],
        )
        if selectors is not None and selectors != [binding["route_selector"]]:
            return None
        return original

    async def _handle_incoming(self, request: web.Request) -> web.Response:
        """Validate one Twilio webhook and return ConversationRelay TwiML."""
        if not self._accepting:
            return web.Response(
                text=build_error_twiml(
                    "Voice channel is not ready. Please try later.",
                ),
                content_type="application/xml",
                status=503,
            )
        form = await self._validated_form(request)
        if form is None:
            return web.Response(text="Invalid signature", status=403)
        call_sid = form.get("CallSid", "")
        if not call_sid:
            return web.Response(text="Missing call identifier.", status=400)
        public_wss_url = self._public_wss_url
        if public_wss_url is None:
            return web.Response(
                text=build_error_twiml("Voice tunnel is unavailable."),
                content_type="application/xml",
                status=503,
            )
        token = await self._mint_token(
            call_sid,
            form.get("From", ""),
            form.get("To", ""),
        )
        ws_url = (
            self._public_route(public_wss_url, "/voice/ws")
            + "&token="
            + quote(token, safe="")
        )
        twiml = build_conversation_relay_twiml(
            ws_url,
            welcome_greeting=str(
                self._config.get("welcome_greeting")
                or "Hi! This is QwenPaw. How can I help you?",
            ),
            tts_provider=str(self._config.get("tts_provider") or "google"),
            tts_voice=str(
                self._config.get("tts_voice") or "en-US-Journey-D",
            ),
            stt_provider=str(
                self._config.get("stt_provider") or "deepgram",
            ),
            language=str(self._config.get("language") or "en-US"),
        )
        return web.Response(text=twiml, content_type="application/xml")

    async def _validated_form(
        self,
        request: web.Request,
    ) -> dict[str, str] | None:
        """Return a signed Twilio form or reject it."""
        signature = request.headers.get("X-Twilio-Signature", "")
        if not signature:
            return None
        url = self._forwarded_url(request)
        if url is None:
            return None
        raw_form = await request.post()
        form = {key: str(value) for key, value in raw_form.items()}
        validator = self._validator
        if validator is None or not validator.validate(
            url,
            raw_form,
            signature,
        ):
            return None
        return form

    async def _mint_token(
        self,
        call_sid: str,
        from_number: str = "",
        to_number: str = "",
    ) -> str:
        """Mint one bounded, expiring WebSocket token."""
        async with self._token_lock:
            if not self._accepting:
                raise web.HTTPServiceUnavailable(text="Unavailable")
            self._purge_expired_tokens()
            while len(self._tokens) >= self._max_tokens:
                self._tokens.popitem(last=False)
            token = self._token_factory()
            self._tokens[token] = _TokenRecord(
                call_sid=call_sid,
                expires_at=self._clock() + self._token_ttl_s,
                from_number=from_number,
                to_number=to_number,
            )
            return token

    async def _consume_token(self, token: str) -> _TokenRecord | None:
        """Atomically validate and consume one WebSocket token."""
        async with self._token_lock:
            self._purge_expired_tokens()
            return self._tokens.pop(token, None)

    def _purge_expired_tokens(self) -> None:
        """Remove all tokens that cannot authenticate a new connection."""
        now = self._clock()
        expired = [
            token
            for token, record in self._tokens.items()
            if record.expires_at <= now
        ]
        for token in expired:
            self._tokens.pop(token, None)

    async def _reserve_websocket_admission(
        self,
        request: web.Request,
    ) -> _Admission:
        """Reserve bounded capacity before any admission await point."""
        task = asyncio.current_task()
        if task is None:
            raise web.HTTPServiceUnavailable(text="Unavailable")
        admission = _Admission(task=task, transport=request.transport)
        async with self._admission_lock:
            if not self._accepting:
                raise web.HTTPServiceUnavailable(text="Unavailable")
            active_count = len(self._connections) + len(self._admissions)
            if active_count >= self._max_connections:
                self._connection_overload_total += 1
                raise web.HTTPServiceUnavailable(text="Overloaded")
            self._admissions[task] = admission
        return admission

    async def _attach_admission_websocket(
        self,
        admission: _Admission,
        websocket: web.WebSocketResponse,
    ) -> None:
        """Expose a provisional socket to the admission fence."""
        async with self._admission_lock:
            if (
                not self._accepting
                or self._admissions.get(admission.task) is not admission
            ):
                raise web.HTTPServiceUnavailable(text="Unavailable")
            admission.websocket = websocket

    async def _promote_websocket_admission(
        self,
        admission: _Admission,
        record: _TokenRecord,
        request: web.Request,
        websocket: web.WebSocketResponse,
    ) -> _Connection | None:
        """Atomically promote one prepared socket into the live registry."""
        connection = _Connection(
            connection_id=uuid.uuid4().hex,
            expected_call_sid=record.call_sid,
            from_number=record.from_number,
            to_number=record.to_number,
            generation=self._generation,
            websocket=websocket,
            queue=asyncio.Queue(maxsize=self._event_queue_size),
            transport=request.transport,
        )
        async with self._admission_lock:
            if (
                not self._accepting
                or self._admissions.get(admission.task) is not admission
            ):
                return None
            self._admissions.pop(admission.task, None)
            self._connections[connection.connection_id] = connection
            connection.worker = asyncio.create_task(
                self._event_worker(connection),
            )
        return connection

    async def _receive_websocket_messages(
        self,
        connection: _Connection,
    ) -> None:
        """Receive ConversationRelay frames for one live connection."""
        async for message in connection.websocket:
            if message.type == aiohttp.WSMsgType.TEXT:
                keep_open = await self._handle_text_frame(
                    connection,
                    message.data,
                )
                if not keep_open:
                    break
            elif message.type in {
                aiohttp.WSMsgType.ERROR,
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
            }:
                break

    async def _handle_websocket(
        self,
        request: web.Request,
    ) -> web.StreamResponse:
        """Accept one token-bound ConversationRelay WebSocket."""
        if self._forwarded_url(request) is None:
            raise web.HTTPForbidden(text="Invalid ingress bridge")
        if len(request.query.getall("token", [])) != 1:
            raise web.HTTPForbidden(text="Invalid token")
        admission = await self._reserve_websocket_admission(request)
        websocket: web.WebSocketResponse | None = None
        connection: _Connection | None = None
        try:
            token = request.query.get("token", "")
            record = await self._consume_token(token)
            if record is None:
                raise web.HTTPForbidden(text="Invalid token")
            websocket = web.WebSocketResponse()
            await self._attach_admission_websocket(admission, websocket)
            await websocket.prepare(request)
            connection = await self._promote_websocket_admission(
                admission,
                record,
                request,
                websocket,
            )
            if connection is None:
                return websocket
            await self._receive_websocket_messages(connection)
        except web.HTTPException:
            raise
        except Exception:
            if connection is None:
                raise
            logger.exception(
                f"voice: WebSocket failed for "
                f"connection={connection.connection_id}",
            )
        finally:
            async with self._admission_lock:
                self._admissions.pop(admission.task, None)
            if connection is not None:
                await self._finish_connection(connection, "disconnected")
            elif websocket is not None and not websocket.closed:
                await websocket.close()
        return websocket

    async def _handle_text_frame(
        self,
        connection: _Connection,
        value: str,
    ) -> bool:
        """Parse and enqueue one native ConversationRelay message."""
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            await connection.websocket.close(
                code=1003,
                message=b"Invalid JSON",
            )
            return False
        if not isinstance(data, Mapping):
            await connection.websocket.close(
                code=1003,
                message=b"Invalid payload",
            )
            return False
        try:
            event = await self._native_event(connection, data)
        except ValueError:
            await connection.websocket.close(
                code=1008,
                message=b"Invalid Voice message",
            )
            return False
        if event is None:
            return True
        try:
            connection.queue.put_nowait(event)
        except asyncio.QueueFull:
            self._runner_backpressure_total += 1
            await connection.websocket.close(
                code=1013,
                message=b"Voice ingress overloaded",
            )
            return False
        return True

    async def _native_event(
        self,
        connection: _Connection,
        data: Mapping[str, Any],
    ) -> VoiceNativeEvent | None:
        """Build one ordered native event and bind setup atomically."""
        message_type = data.get("type")
        if not isinstance(message_type, str) or not message_type:
            raise ValueError("Voice message type is required")
        async with connection.state_lock:
            if message_type == "setup":
                await self._bind_setup(connection, data)
                event_kind = "call.started"
                payload = {
                    "from": connection.from_number,
                    "to": connection.to_number,
                }
            elif message_type == "prompt":
                self._require_setup(connection)
                text = data.get("voicePrompt", "")
                if not isinstance(text, str) or not text.strip():
                    return None
                event_kind = "message.query"
                payload = {"text": text}
            elif message_type == "interrupt":
                self._require_setup(connection)
                spoken = data.get("utteranceUntilInterrupt", "")
                if not isinstance(spoken, str):
                    raise ValueError("Voice interrupt text must be a string")
                event_kind = "call.interrupted"
                payload = {"utterance": spoken}
            elif message_type == "dtmf":
                self._require_setup(connection)
                digit = data.get("digit", "")
                if not isinstance(digit, str) or not digit:
                    raise ValueError("Voice DTMF digit is required")
                event_kind = "dtmf"
                payload = {"digit": digit}
            else:
                logger.debug(
                    f"voice: ignored native message type={message_type}",
                )
                return None
            connection.sequence += 1
            sequence = connection.sequence
            return VoiceNativeEvent(
                event_id=(
                    f"voice:g{connection.generation}:"
                    f"{connection.connection_id}:{sequence}"
                ),
                event_kind=event_kind,
                connection_id=connection.connection_id,
                generation=connection.generation,
                sequence=sequence,
                session_binding=connection.session_binding,
                platform_session_id=connection.platform_session_id,
                payload=payload,
            )

    async def _bind_setup(
        self,
        connection: _Connection,
        data: Mapping[str, Any],
    ) -> None:
        """Validate setup and register its call and session bindings."""
        if connection.setup_received:
            raise ValueError("Voice setup must be unique")
        call_sid = data.get("callSid")
        if not isinstance(call_sid, str) or not call_sid:
            raise ValueError("Voice setup CallSid is required")
        if call_sid != connection.expected_call_sid:
            raise ValueError("Voice setup CallSid mismatch")
        existing = self._calls.get(call_sid)
        if existing is not None and existing is not connection:
            raise ValueError("Voice CallSid is already connected")
        caller = str(data.get("from") or connection.from_number)
        callee = str(data.get("to") or connection.to_number)
        if connection.from_number and caller != connection.from_number:
            raise ValueError("Voice setup caller mismatch")
        if connection.to_number and callee != connection.to_number:
            raise ValueError("Voice setup recipient mismatch")
        connection.from_number, connection.to_number = caller, callee
        connection.platform_session_id = call_sid
        connection.session_binding = (
            f"voice:g{connection.generation}:"
            f"{connection.connection_id}:{call_sid}"
        )
        connection.setup_received = True
        self._calls[call_sid] = connection
        self._bindings[connection.session_binding] = connection

    @staticmethod
    def _require_setup(connection: _Connection) -> None:
        """Reject native messages that arrive before setup."""
        if not connection.setup_received:
            raise ValueError("Voice setup must be the first message")

    async def _event_worker(self, connection: _Connection) -> None:
        """Submit one connection's events in strict sequence order."""
        while True:
            event = await connection.queue.get()
            try:
                if event is None:
                    return
                handler = self._event_handler
                if handler is not None:
                    await handler(event)
            except Exception:
                logger.exception(
                    f"voice: event submission failed for "
                    f"connection={connection.connection_id}",
                )
                await connection.websocket.close(
                    code=1013,
                    message=b"Voice event admission failed",
                )
            finally:
                connection.queue.task_done()

    async def _handle_status_callback(
        self,
        request: web.Request,
    ) -> web.Response:
        """Submit one idempotent terminal Twilio status callback."""
        if not self._accepting:
            return web.Response(status=503)
        form = await self._validated_form(request)
        if form is None:
            return web.Response(text="Invalid signature", status=403)
        call_sid = form.get("CallSid", "")
        status = form.get("CallStatus", "")
        if not call_sid or not status:
            return web.Response(status=400)
        if status not in _TERMINAL_STATUSES:
            return web.Response(status=204)
        connection = self._calls.get(call_sid)
        if connection is None:
            self._unknown_status_total += 1
            return web.Response(status=204)
        await self._enqueue_close(
            connection,
            f"status:{status}",
            (f"voice:g{connection.generation}:status:" f"{call_sid}:{status}"),
        )
        await connection.websocket.close()
        return web.Response(status=204)

    async def _enqueue_close(
        self,
        connection: _Connection,
        reason: str,
        event_id: str | None = None,
    ) -> None:
        """Enqueue at most one ordered call.closed event."""
        async with connection.state_lock:
            if connection.close_enqueued or not connection.setup_received:
                return
            connection.close_enqueued = True
            connection.sequence += 1
            sequence = connection.sequence
            event = VoiceNativeEvent(
                event_id=event_id
                or (
                    f"voice:g{connection.generation}:"
                    f"{connection.connection_id}:{sequence}"
                ),
                event_kind="call.closed",
                connection_id=connection.connection_id,
                generation=connection.generation,
                sequence=sequence,
                session_binding=connection.session_binding,
                platform_session_id=connection.platform_session_id,
                payload={
                    "reason": reason,
                    "last_sequence": sequence - 1,
                },
            )
        try:
            connection.queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                await asyncio.wait_for(
                    connection.queue.put(event),
                    timeout=self._shutdown_timeout_s,
                )
            except asyncio.TimeoutError:
                self._runner_backpressure_total += 1

    async def _finish_connection(
        self,
        connection: _Connection,
        reason: str,
    ) -> None:
        """Drain one connection's event queue and remove its binding."""
        async with connection.cleanup_lock:
            if connection.cleaned:
                return
            await self._enqueue_close(connection, reason)
            await connection.queue.join()
            worker = connection.worker
            if worker is not None and not worker.done():
                await connection.queue.put(None)
                await worker
            connection.cleaned = True
            async with self._admission_lock:
                self._connections.pop(connection.connection_id, None)
            if connection.platform_session_id:
                current = self._calls.get(connection.platform_session_id)
                if current is connection:
                    self._calls.pop(connection.platform_session_id, None)
            if connection.session_binding:
                self._bindings.pop(connection.session_binding, None)

    def connection(self, binding: str) -> _Connection:
        connection = self._bindings.get(binding)
        if (
            connection is None
            or connection.cleaned
            or connection.close_enqueued
            or connection.websocket.closed
            or self._stopping
            or connection.generation != self._generation
        ):
            raise VoicePlatformError("CALL_CLOSED")
        return connection

    async def send_text(
        self,
        binding: str,
        text: str,
        *,
        completed: bool = False,
    ) -> None:
        """Send one direct final or the legacy completed-message frame pair."""
        connection = self.connection(binding)
        async with connection.write_lock:
            if self.connection(binding) is not connection:
                raise VoicePlatformError("CALL_CLOSED")
            try:
                await connection.websocket.send_json(
                    {"type": "text", "token": text, "last": not completed},
                )
                if completed:
                    await connection.websocket.send_json(
                        {"type": "text", "token": "", "last": True},
                    )
            except Exception as exc:
                raise VoicePlatformError(
                    "PLATFORM_RESULT_UNKNOWN",
                    side_effect_possible=True,
                ) from exc

    async def _close_connection(
        self,
        connection: _Connection,
        deadline: float,
    ) -> None:
        """Send ConversationRelay end and close one connection."""
        await self._enqueue_close(connection, "shutdown")
        async with connection.write_lock:
            if (
                not connection.websocket.closed
                and not connection.end_attempted
            ):
                connection.end_attempted = True
                try:
                    await connection.websocket.send_json({"type": "end"})
                except Exception:
                    logger.debug(
                        "voice: end frame failed",
                        exc_info=True,
                    )
        remaining = max(
            0.0,
            deadline - asyncio.get_running_loop().time(),
        )
        try:
            await asyncio.wait_for(
                connection.websocket.close(),
                timeout=remaining,
            )
        except (asyncio.TimeoutError, Exception):
            transport = connection.transport
            if transport is not None:
                transport.abort()

    def health_snapshot(self) -> dict[str, Any]:
        """Return non-secret ingress diagnostics."""
        return {
            "listening": self.listen_port is not None,
            "accepting": self._accepting,
            "listen_port": self.listen_port,
            "connection_count": len(self._connections),
            "provisional_connection_count": len(self._admissions),
            "max_connections": self._max_connections,
            "connection_overload_total": self._connection_overload_total,
            "pending_token_count": len(self._tokens),
            "runner_backpressure_total": (self._runner_backpressure_total),
            "unknown_status_total": self._unknown_status_total,
            "webhook_transaction_state": (self._webhook_transaction_state),
            "webhook_rollback_reason": self._webhook_rollback_reason,
            "startup_failure_reason": self._startup_failure_reason,
            "endpoint_cleanup_reason": self._endpoint_cleanup_reason,
            "cleanup_in_progress": (
                self._close_task is not None and not self._close_task.done()
            ),
            "cleanup_complete": self._cleanup_complete,
            "pending_cleanup_tasks": sum(
                not task.done() for task in self._cleanup_tasks
            ),
            "pending_cleanup_operations": len(self._cleanup_operations),
        }


__all__ = [
    "TunnelInfo",
    "VoiceEndpoint",
    "VoiceNativeEvent",
    "VoicePlatform",
    "VoicePlatformError",
]
