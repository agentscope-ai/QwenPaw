# -*- coding: utf-8 -*-
"""Runner-safe OneBot v11 reverse WebSocket platform boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass
import hmac
import ipaddress
import json
import logging
from pathlib import Path
import socket
from typing import Any
import uuid

import aiohttp
from aiohttp import web

from qwenpaw.app.channels.utils import file_url_to_local_path, split_text

from .codec import (
    _clean_onebot_plain_text,
    _normalize_media_ref,
    _run_in_thread,
    session_id,
)
from .media import OneBotInboundMedia

logger = logging.getLogger(__name__)

_AUTH_SCHEMES = frozenset({"bearer", "token"})
_DEFAULT_EVENT_TASK_HARD_CAP = 500
_DEFAULT_SHUTDOWN_TIMEOUT = 5.0
_DEFAULT_WS_HOST = "127.0.0.1"


class OneBotPlatformError(RuntimeError):
    """Report a platform operation with a classified side-effect risk."""

    def __init__(
        self,
        reason_code: str,
        *,
        side_effect_possible: bool = False,
        retryable: bool = False,
    ) -> None:
        self.reason_code = reason_code
        self.side_effect_possible = side_effect_possible
        self.retryable = retryable
        super().__init__(reason_code)


@dataclass(frozen=True)
class OneBotEndpoint:
    """Describe the actual reverse WebSocket listener state."""

    host: str
    port: int
    readiness: str
    bound_externally: bool
    auth_required: bool


EventHandler = Callable[
    [Mapping[str, Any]],
    Coroutine[Any, Any, None],
]
EndpointHandler = Callable[[str, OneBotEndpoint], Awaitable[None]]


def _normalize_host(value: object) -> str:
    """Normalize a bind host while preserving the loopback default."""
    if not isinstance(value, str):
        raise ValueError("OneBot ws_host must be a string")
    return value.strip().strip("[]") or _DEFAULT_WS_HOST


def _is_external_host(host: str) -> bool:
    """Return whether a listener is exposed beyond loopback."""
    normalized = host.strip().lower()
    if normalized == "localhost":
        return False
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return True
    return not address.is_loopback


def _probe_host(host: str) -> str:
    """Map wildcard bind addresses to a local health-probe address."""
    normalized = host.strip().lower()
    if normalized in {"0.0.0.0", ""}:
        return "127.0.0.1"
    if normalized == "::":
        return "::1"
    return host


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
        raise ValueError(f"OneBot ws_host cannot be resolved: {host}") from exc
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
        raise ValueError(f"OneBot ws_host has no bind address: {host}")
    return min(candidates)[1]


def _extract_auth_token(value: str) -> str:
    """Extract a supported OneBot Authorization header token."""
    scheme, _, token = value.strip().partition(" ")
    if scheme.lower() not in _AUTH_SCHEMES:
        return ""
    return token.strip()


def _tokens_match(provided: str, expected: str) -> bool:
    """Compare access tokens without content-dependent timing."""
    return hmac.compare_digest(
        provided.encode("utf-8"),
        expected.encode("utf-8"),
    )


def _log_remote(request: web.Request) -> str:
    """Return a single-line remote address for diagnostics."""
    return (
        (request.remote or "unknown")
        .replace("\r", "")
        .replace(
            "\n",
            "",
        )
    )


class OneBotPlatform:
    """Own OneBot listener, native WebSockets, and echo-based APIs."""

    def __init__(
        self,
        *,
        event_task_hard_cap: int = _DEFAULT_EVENT_TASK_HARD_CAP,
        watchdog_interval: float = 10.0,
        api_timeout: float = 15.0,
        shutdown_timeout: float = _DEFAULT_SHUTDOWN_TIMEOUT,
    ) -> None:
        if event_task_hard_cap <= 0:
            raise ValueError("event_task_hard_cap must be positive")
        if watchdog_interval <= 0:
            raise ValueError("watchdog_interval must be positive")
        if api_timeout <= 0:
            raise ValueError("api_timeout must be positive")
        if shutdown_timeout <= 0:
            raise ValueError("shutdown_timeout must be positive")
        self._event_task_hard_cap = event_task_hard_cap
        self._watchdog_interval = watchdog_interval
        self._api_timeout = api_timeout
        self._shutdown_timeout = shutdown_timeout
        self._ws_host = _DEFAULT_WS_HOST
        self._bind_host = _DEFAULT_WS_HOST
        self._ws_port = 6199
        self._access_token = ""
        self._bound_externally = False
        self._auth_required = False
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._connections: set[web.WebSocketResponse] = set()
        self._connection_transports: dict[
            web.WebSocketResponse,
            asyncio.BaseTransport,
        ] = {}
        self._pending_calls: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._event_tasks: set[asyncio.Task[None]] = set()
        self._watchdog_task: asyncio.Task[None] | None = None
        self._event_handler: EventHandler | None = None
        self._endpoint_handler: EndpointHandler | None = None
        self._last_endpoint: OneBotEndpoint | None = None
        self._desired_endpoint: OneBotEndpoint | None = None
        self._desired_endpoint_operation: str | None = None
        self._endpoint_publication_pending = False
        self._accepting = False
        self._stopping = False
        self._prepared = False
        self._runner_event_dropped_total = 0
        self._platform_rebind_total = 0
        self._session_queues: dict[str, asyncio.Queue] = {}
        self._session_workers: dict[str, asyncio.Task] = {}
        self._share_session_in_group = False
        self._api_tasks: set[asyncio.Task] = set()
        self._reader_tasks: set[asyncio.Task] = set()
        self._cleanup_tasks: set[asyncio.Task] = set()
        self._close_task: asyncio.Task | None = None
        self._send_tasks: set[asyncio.Task] = set()
        self._inbound_media: OneBotInboundMedia | None = None

    @property
    def listen_port(self) -> int | None:
        """Return the actual bound port, if a listener exists."""
        if self._site is None:
            return None
        server = getattr(self._site, "_server", None)
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
    def endpoint(self) -> OneBotEndpoint | None:
        """Return the most recently reported endpoint."""
        return self._last_endpoint

    async def prepare(
        self,
        config: Mapping[str, Any],
        secret: Mapping[str, str],
    ) -> None:
        """Validate non-secret config and consume the access token."""
        host = _normalize_host(config.get("ws_host", _DEFAULT_WS_HOST))
        port = config.get("ws_port", 6199)
        if (
            not isinstance(port, int)
            or isinstance(port, bool)
            or not 0 <= port <= 65535
        ):
            raise ValueError("OneBot ws_port must be between 0 and 65535")
        access_token = secret.get("access_token", "")
        if not isinstance(access_token, str):
            raise ValueError("OneBot access_token must be a string")
        self._ws_host = host
        self._bind_host = await _resolve_dynamic_bind_host(host, port)
        self._ws_port = port
        self._access_token = access_token.strip()
        self._bound_externally = _is_external_host(host)
        self._auth_required = self._bound_externally or bool(
            self._access_token,
        )
        self._share_session_in_group = bool(
            config.get("share_session_in_group", False),
        )
        workspace = config.get("workspace_dir")
        self._workspace_dir = (
            Path(workspace).expanduser() if workspace else None
        )
        if config.get("media_dir"):
            self._media_dir = Path(config["media_dir"]).expanduser()
        elif self._workspace_dir:
            self._media_dir = self._workspace_dir / "media"
        else:
            from qwenpaw.constant import DEFAULT_MEDIA_DIR

            self._media_dir = DEFAULT_MEDIA_DIR
        self._roots = (self._media_dir.resolve(),) + (
            (self._workspace_dir.resolve(),) if self._workspace_dir else ()
        )
        self._media_base64 = bool(config.get("media_base64", False))
        base64_mb = int(config.get("media_base64_max_mb", 10))
        download_mb = int(config.get("media_download_max_mb", 50))
        self._media_base64_max_bytes = (
            base64_mb if base64_mb > 0 else 10
        ) * 1_000_000
        self._inbound_media = OneBotInboundMedia(
            media_dir=self._media_dir,
            max_download_bytes=(download_mb if download_mb > 0 else 50)
            * 1_000_000,
            call_api=self.call_api,
            allowed_roots=self._roots,
        )
        self._prepared = True

    async def start(
        self,
        event_handler: EventHandler,
        endpoint_handler: EndpointHandler,
    ) -> None:
        """Bind the listener, publish ownership and start health recovery."""
        if not self._prepared:
            raise RuntimeError("OneBot platform is not prepared")
        if self._watchdog_task is not None:
            return
        self._event_handler = event_handler
        self._endpoint_handler = endpoint_handler
        self._stopping = False
        await self._inbound_media.start()
        await self._start_ws_server("register")
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def quiesce(self) -> None:
        """Stop admitting new platform traffic and release the listener."""
        await self.close()

    async def stop_accepting(self):
        """Close only this listener's entrance, retaining established sockets."""
        self._stopping = True
        self._accepting = False
        task = self._watchdog_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await self._wait_tasks_until(
                (task,),
                asyncio.get_running_loop().time() + self._shutdown_timeout,
            )
            self._watchdog_task = None
        if self._site is not None:
            await self._site.stop()
            self._site = None

    async def close(self, *, deadline=None):
        """Drain owned work; cleanup failure preserves resources for a retry."""
        self._stopping = True
        self._accepting = False
        if self._close_task is None or self._close_task.done():
            end = asyncio.get_running_loop().time() + self._shutdown_timeout
            if deadline is not None:
                end = min(end, deadline)
            self._close_task = asyncio.create_task(self._close_resources(end))
        try:
            await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            await self._close_task
            raise

    def health_snapshot(self) -> dict[str, Any]:
        """Return non-secret listener diagnostics."""
        return {
            "prepared": self._prepared,
            "listening": self.listen_port is not None,
            "accepting": self._accepting,
            "listen_port": self.listen_port,
            "connection_count": len(self._connections),
            "runner_event_dropped_total": (self._runner_event_dropped_total),
            "platform_rebind_total": self._platform_rebind_total,
            "session_queue_count": len(self._session_queues),
            "session_queued_count": sum(
                queue.qsize() for queue in self._session_queues.values()
            ),
            "pending_api_count": len(self._pending_calls),
            "endpoint_publication_pending": self._endpoint_publication_pending,
        }

    async def _start_ws_server(self, operation: str) -> None:
        """Attempt one bind and report either ready or degraded state."""
        self._accepting = False
        self._app = web.Application()
        self._app.router.add_get("/ws", self._handle_ws_connection)
        self._app.router.add_get("/ws/", self._handle_ws_connection)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner,
            self._bind_host,
            self._ws_port,
        )
        try:
            await self._site.start()
        except OSError:
            await self._cleanup_failed_bind()
            await self._report_endpoint(operation, "degraded")
            logger.warning(
                f"onebot: bind failed for "
                f"{self._bind_host}:{self._ws_port}; watchdog will retry",
            )
            return
        if self.listen_port is None:
            await self._cleanup_failed_bind()
            raise OneBotPlatformError("INGRESS_ENDPOINT_AMBIGUOUS")
        await self._report_endpoint(
            operation,
            (
                "degraded"
                if self._bound_externally and not self._access_token
                else "ready"
            ),
        )
        logger.info(
            f"onebot: reverse WS server listening on "
            f"{self._bind_host}:{self.listen_port}",
        )

    async def _cleanup_failed_bind(self) -> None:
        """Discard a failed aiohttp bind attempt."""
        runner = self._runner
        if runner is not None:
            await runner.cleanup()
        self._site = self._runner = self._app = None

    async def _report_endpoint(
        self,
        operation: str,
        readiness: str,
    ) -> None:
        """Publish the actual listener state before accepting traffic."""
        port = self.listen_port
        if port is None:
            port = self._ws_port
        endpoint = OneBotEndpoint(
            host=self._bind_host,
            port=port,
            readiness=readiness,
            bound_externally=self._bound_externally,
            auth_required=self._auth_required,
        )
        self._desired_endpoint_operation = operation
        self._desired_endpoint = endpoint
        self._endpoint_publication_pending = True
        await self._publish_desired_endpoint()

    async def _publish_desired_endpoint(self) -> None:
        """Publish and acknowledge the latest desired endpoint state."""
        handler = self._endpoint_handler
        if handler is None:
            raise RuntimeError("OneBot endpoint handler is unavailable")
        operation = self._desired_endpoint_operation
        endpoint = self._desired_endpoint
        if not self._endpoint_publication_pending:
            return
        if operation is None or endpoint is None:
            raise RuntimeError("OneBot desired endpoint is unavailable")
        await handler(operation, endpoint)
        if (
            self._desired_endpoint_operation != operation
            or self._desired_endpoint is not endpoint
        ):
            return
        self._last_endpoint = endpoint
        self._endpoint_publication_pending = False
        if (
            endpoint.readiness == "ready"
            and not self._stopping
            and self.listen_port == endpoint.port
        ):
            self._accepting = True

    async def _close_resources(self, deadline):
        failures = []
        current = asyncio.current_task()
        tasks = (
            set(self._event_tasks)
            | set(self._session_workers.values())
            | self._api_tasks
            | self._send_tasks
        )
        if self._watchdog_task is not None:
            tasks.add(self._watchdog_task)
        tasks.discard(current)
        for task in tasks:
            task.cancel()
        try:
            await self._wait_tasks_until(tuple(tasks), deadline)
        except Exception as exc:
            failures.append(exc)
        if self._watchdog_task is not None and self._watchdog_task.done():
            self._watchdog_task = None
        try:
            await self._stop_ws_server(deadline)
        except Exception as exc:
            failures.append(exc)
        if self._inbound_media is not None:
            try:
                await self._run_cleanup_until(
                    self._inbound_media.close(),
                    deadline,
                    "media close",
                )
            except Exception as exc:
                failures.append(exc)
        # A deadline does not prove that a cancelled coroutine or socket exited.
        if any(not task.done() for task in self._cleanup_tasks):
            failures.append(RuntimeError("ONEBOT_CLEANUP_TASKS_REMAIN"))
        if failures:
            raise RuntimeError("ONEBOT_STOP_INCOMPLETE") from failures[0]
        self._event_tasks.clear()
        self._session_workers.clear()
        self._session_queues.clear()

    async def _stop_ws_server(self, deadline=None):
        self._accepting = False
        if deadline is None:
            deadline = (
                asyncio.get_running_loop().time() + self._shutdown_timeout
            )
        failures = []
        site, runner = self._site, self._runner
        server = getattr(site, "_server", None)
        if server is not None:
            server.close()
        for future in tuple(self._pending_calls.values()):
            if not future.done():
                future.cancel()
        self._pending_calls.clear()
        connections = tuple(self._connections)
        transports = {
            ws: self._connection_transports.get(ws) for ws in connections
        }
        close_tasks = {
            ws: asyncio.create_task(ws.close()) for ws in connections
        }
        self._cleanup_tasks.update(close_tasks.values())
        try:
            await self._wait_tasks_until(tuple(close_tasks.values()), deadline)
        except Exception as exc:
            failures.append(exc)
        finally:
            for ws in connections:
                transport = transports[ws]
                try:
                    ws.force_close()
                    if transport is not None:
                        transport.close()
                except Exception as exc:
                    failures.append(exc)
                task = close_tasks[ws]
                close_ack = (
                    task.done()
                    and not task.cancelled()
                    and task.exception() is None
                )
                transport_closed = transport is not None and (
                    transport.is_closing()
                    if hasattr(transport, "is_closing")
                    else bool(getattr(transport, "closed", False))
                )
                if (
                    close_ack
                    or bool(getattr(ws, "closed", False))
                    or transport_closed
                ):
                    self._connections.discard(ws)
                    self._connection_transports.pop(ws, None)
                else:
                    failures.append(RuntimeError("ONEBOT_CONNECTION_REMAINS"))
        readers = tuple(
            task
            for task in self._reader_tasks
            if task is not asyncio.current_task()
        )
        for task in readers:
            task.cancel()
        try:
            await self._wait_tasks_until(readers, deadline)
        except Exception as exc:
            failures.append(exc)
        for resource, operation, name in (
            (site, "stop", "_site"),
            (runner, "cleanup", "_runner"),
        ):
            if resource is not None:
                # aiohttp unregisters a stopped site but retains its server.
                if operation == "stop" and (
                    runner is not None and resource not in runner.sites
                ):
                    if self._site is resource:
                        self._site = None
                    continue
                try:
                    await self._run_cleanup_until(
                        getattr(resource, operation)(),
                        deadline,
                        operation,
                    )
                except Exception as exc:
                    failures.append(exc)
                else:
                    if getattr(self, name) is resource:
                        setattr(self, name, None)
        if self._site is None and self._runner is None:
            self._app = None
        # Completed tasks can be discarded only after their result was inspected.
        self._cleanup_tasks = {
            task for task in self._cleanup_tasks if not task.done()
        }
        if failures:
            raise RuntimeError(
                "ONEBOT_LISTENER_STOP_INCOMPLETE",
            ) from failures[0]

    async def _run_cleanup_until(self, awaitable, deadline, operation):
        task = asyncio.ensure_future(awaitable)
        self._cleanup_tasks.add(task)
        try:
            await self._wait_tasks_until((task,), deadline)
            if task.cancelled():
                raise RuntimeError("ONEBOT_CLEANUP_TIMEOUT:" + operation)
            task.result()
        finally:
            if (
                task.done()
                and not task.cancelled()
                and task.exception() is None
            ):
                self._cleanup_tasks.discard(task)

    async def _wait_tasks_until(self, tasks, deadline):
        if not tasks:
            return
        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        _, pending = await asyncio.wait(tasks, timeout=remaining)
        for task in pending:
            task.cancel()
        if pending:
            # Give cooperative cancellation one loop turn. Stubborn tasks retain
            # their references and fail shutdown rather than becoming orphans.
            await asyncio.sleep(0)
        if any(not task.done() for task in tasks):
            self._cleanup_tasks.update(
                task for task in tasks if not task.done()
            )
            raise RuntimeError("ONEBOT_TASKS_REMAIN")
        for task in tasks:
            if not task.cancelled():
                task.result()

    async def _watchdog_loop(self) -> None:
        """Recover a missing or unhealthy listener with endpoint updates."""
        while not self._stopping:
            await asyncio.sleep(self._watchdog_interval)
            if self._stopping:
                return
            try:
                await self._watchdog_iteration()
            except Exception:
                logger.warning(
                    "onebot: watchdog recovery attempt failed",
                    exc_info=True,
                )

    async def _watchdog_iteration(self) -> None:
        """Reconcile endpoint publication or perform one listener rebind."""
        if await self._is_server_healthy():
            if self._endpoint_publication_pending:
                await self._publish_desired_endpoint()
            return
        self._accepting = False
        if (
            self._last_endpoint is not None
            or self._desired_endpoint is not None
        ):
            try:
                await self._report_endpoint("update", "degraded")
            except Exception:
                logger.warning(
                    "onebot: degraded endpoint update failed",
                    exc_info=True,
                )
        await self._stop_ws_server()
        if self._stopping:
            return
        try:
            await self._start_ws_server("update")
        finally:
            if self._site is not None and self.listen_port is not None:
                self._platform_rebind_total += 1

    async def _is_server_healthy(self) -> bool:
        """Return whether the current TCP listener accepts connections."""
        port = self.listen_port
        if self._site is None or port is None:
            return False
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(_probe_host(self._bind_host), port),
                timeout=3.0,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, asyncio.TimeoutError):
            return False

    def _token_authorized(self, request: web.Request) -> bool:
        """Validate the OneBot Authorization header."""
        provided = _extract_auth_token(
            request.headers.get("Authorization", ""),
        )
        return bool(provided) and _tokens_match(
            provided,
            self._access_token,
        )

    async def _handle_ws_connection(
        self,
        request: web.Request,
    ) -> web.StreamResponse:
        """Handle one OneBot reverse WebSocket connection."""
        if self._auth_required and not self._access_token:
            logger.error(
                f"onebot: rejected connection from {_log_remote(request)}: "
                f"ws_host={self._ws_host} requires access_token",
            )
            if "access_token" in request.query:
                logger.warning(
                    "onebot: use the Authorization header, not access_token in the query",
                )
            return web.Response(status=401, text="Unauthorized")
        if self._access_token and not self._token_authorized(request):
            logger.warning(
                f"onebot: rejected connection from "
                f"{_log_remote(request)} (bad token)",
            )
            if "access_token" in request.query:
                logger.warning(
                    "onebot: use the Authorization header, not access_token in the query",
                )
            return web.Response(status=401, text="Unauthorized")
        if not self._accepting:
            return web.Response(status=503, text="Unavailable")

        connection = web.WebSocketResponse()
        await connection.prepare(request)
        self._connections.add(connection)
        reader = asyncio.current_task()
        self._reader_tasks.add(reader)
        transport = request.transport
        if transport is not None:
            self._connection_transports[connection] = transport
        try:
            async for message in connection:
                if message.type == aiohttp.WSMsgType.TEXT:
                    self._handle_text_frame(message.data)
                elif message.type in {
                    aiohttp.WSMsgType.ERROR,
                    aiohttp.WSMsgType.CLOSE,
                }:
                    break
        except Exception:
            logger.exception("onebot: WebSocket connection failed")
        finally:
            self._connections.discard(connection)
            self._connection_transports.pop(connection, None)
            self._reader_tasks.discard(reader)
        return connection

    def _handle_text_frame(self, value: str) -> None:
        """Route native echo responses and platform events separately."""
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            logger.warning(f"onebot: invalid JSON: {value[:200]}")
            return
        if not isinstance(data, Mapping):
            logger.warning("onebot: native WebSocket payload is not an object")
            return
        native = dict(data)
        if "echo" in native:
            self._handle_api_response(native)
            return
        if self._stopping or not self._accepting:
            return
        handler = self._event_handler
        if handler is None:
            return
        if native.get("post_type") == "message":
            self._dispatch_message_event(native)
        else:
            self._spawn_event_task(handler(native))

    def _dispatch_message_event(self, native):
        if self._stopping:
            return
        is_group = native.get("message_type") == "group"
        key = session_id(
            str(native.get("user_id") or ""),
            {
                "is_group": is_group,
                "group_id": str(native.get("group_id") or ""),
            },
            self._share_session_in_group,
        )
        queue = self._session_queues.get(key)
        if queue is None:
            if len(self._session_queues) >= self._event_task_hard_cap:
                self._runner_event_dropped_total += 1
                return
            queue = asyncio.Queue(maxsize=50)
            self._session_queues[key] = queue
            self._session_workers[key] = asyncio.create_task(
                self._session_worker_loop(key, queue),
            )
        try:
            queue.put_nowait(native)
        except asyncio.QueueFull:
            self._runner_event_dropped_total += 1
            logger.warning("onebot: session queue full; event dropped")

    async def _session_worker_loop(self, key, queue):
        try:
            while not self._stopping:
                value = await queue.get()
                try:
                    await self._event_handler(value)
                except Exception:
                    logger.exception("onebot: session event failed")
                finally:
                    queue.task_done()
                if queue.empty():
                    break
        finally:
            if self._session_workers.get(key) is asyncio.current_task():
                self._session_workers.pop(key, None)
                self._session_queues.pop(key, None)

    def _spawn_event_task(
        self,
        coro: Coroutine[Any, Any, None],
    ) -> None:
        """Schedule native event work without blocking echo responses."""
        if len(self._event_tasks) >= self._event_task_hard_cap:
            self._runner_event_dropped_total += 1
            coro.close()
            logger.warning(
                f"onebot: event task cap "
                f"{self._event_task_hard_cap} reached; event dropped",
            )
            return
        task = asyncio.create_task(coro)
        self._event_tasks.add(task)
        task.add_done_callback(self._event_task_done)

    def _event_task_done(self, task: asyncio.Task[None]) -> None:
        """Release a completed event task and consume its failure."""
        self._event_tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            logger.exception("onebot: platform event handler failed")

    async def call_api(
        self,
        action: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Call a OneBot action through the reverse WebSocket echo path."""
        if self._stopping:
            raise OneBotPlatformError("ONEBOT_STOPPING")
        if not self._connections:
            raise OneBotPlatformError("INGRESS_CONNECTION_UNKNOWN")
        if len(self._pending_calls) >= self._event_task_hard_cap:
            raise OneBotPlatformError("INGRESS_API_BACKPRESSURE")
        echo = str(uuid.uuid4())
        future: asyncio.Future[
            dict[str, Any]
        ] = asyncio.get_running_loop().create_future()
        self._pending_calls[echo] = future
        payload = json.dumps(
            {
                "action": action,
                "params": dict(params),
                "echo": echo,
            },
            ensure_ascii=False,
        )
        owner = asyncio.current_task()
        self._api_tasks.add(owner)
        try:
            connection = next(
                (ws for ws in self._connections if not ws.closed),
                None,
            )
            if connection is None:
                raise OneBotPlatformError("INGRESS_CONNECTION_UNKNOWN")
            try:
                await connection.send_str(payload)
            except Exception as exc:
                # A raised write may already have reached NapCat; never replay
                # it on another connection without an authoritative rejection.
                raise OneBotPlatformError(
                    "PLATFORM_RESULT_UNKNOWN",
                    side_effect_possible=True,
                ) from exc
            result = await asyncio.wait_for(
                future,
                timeout=self._api_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise OneBotPlatformError(
                "PLATFORM_RESULT_UNKNOWN",
                side_effect_possible=True,
            ) from exc
        except asyncio.CancelledError as exc:
            if asyncio.current_task().cancelling():
                raise
            raise OneBotPlatformError(
                "PLATFORM_RESULT_UNKNOWN",
                side_effect_possible=True,
            ) from exc
        finally:
            self._pending_calls.pop(echo, None)
            self._api_tasks.discard(owner)
            if not future.done():
                future.cancel()
        if result.get("retcode") != 0:
            raise OneBotPlatformError(
                (
                    "PLATFORM_RESULT_UNKNOWN"
                    if result.get("status") == "async"
                    else "PLATFORM_API_FAILED"
                ),
                side_effect_possible=result.get("status") == "async",
            )
        return result

    def _handle_api_response(self, data: dict[str, Any]) -> None:
        """Resolve an echo waiter without blocking the WebSocket reader."""
        echo = data.get("echo")
        if not isinstance(echo, str):
            return
        future = self._pending_calls.get(echo)
        if future is not None and not future.done():
            future.set_result(data)

    async def send_message(
        self,
        to_handle,
        content_parts,
        content_source=None,
    ):
        """Keep native text/media/file order; never reconstruct host-lost order."""
        if self._stopping:
            raise OneBotPlatformError("ONEBOT_STOPPING")
        is_group, target = self._resolve_target(to_handle)
        key = "group_id" if is_group else "user_id"
        action = "send_group_msg" if is_group else "send_private_msg"
        owner = asyncio.current_task()
        self._send_tasks.add(owner)
        calls, message_ids, texts = 0, [], []
        source = getattr(content_source, "value", content_source)

        async def invoke(method, parameters):
            nonlocal calls
            result = await self.call_api(method, parameters)
            calls += 1
            data = result.get("data")
            if (
                isinstance(data, Mapping)
                and data.get("message_id") is not None
            ):
                message_ids.append(str(data["message_id"]))

        async def flush():
            if not texts:
                return
            body = "\n".join(texts)
            texts.clear()
            if source != "direct":
                body = body.strip()
            body = await _run_in_thread(_clean_onebot_plain_text, body)
            if body.strip():
                for chunk in split_text(body):
                    await invoke(
                        action,
                        {
                            key: target,
                            "message": [
                                {"type": "text", "data": {"text": chunk}},
                            ],
                        },
                    )

        try:
            for part in content_parts:
                kind = part.get("type")
                if kind == "text":
                    if part.get("text"):
                        texts.append(str(part["text"]))
                    continue
                if kind not in {"image", "audio", "video", "file"}:
                    continue
                await flush()
                field = "data" if kind == "audio" else kind + "_url"
                ref = str(part.get(field) or "")
                if not ref:
                    continue
                local_text = file_url_to_local_path(ref)
                if local_text:
                    path = Path(local_text).expanduser()
                    if (path.is_absolute() or path.is_file()) and not any(
                        path.resolve().is_relative_to(root)
                        for root in self._roots
                    ):
                        raise OneBotPlatformError("MEDIA_PATH_UNAUTHORIZED")
                ref = await _normalize_media_ref(
                    ref,
                    media_base64=self._media_base64,
                    media_base64_max_bytes=self._media_base64_max_bytes,
                )
                if kind == "file":
                    await invoke(
                        "upload_group_file"
                        if is_group
                        else "upload_private_file",
                        {
                            key: target,
                            "file": ref,
                            "name": part.get("filename") or "file",
                        },
                    )
                else:
                    segment_type = "record" if kind == "audio" else kind
                    await invoke(
                        action,
                        {
                            key: target,
                            "message": [
                                {"type": segment_type, "data": {"file": ref}},
                            ],
                        },
                    )
            await flush()
            return {
                "api_calls": str(calls),
                "native_message_ids": json.dumps(message_ids),
            }
        except OneBotPlatformError as exc:
            if calls and not exc.side_effect_possible:
                raise OneBotPlatformError(
                    "PARTIAL_DELIVERY",
                    side_effect_possible=True,
                ) from exc
            raise
        finally:
            self._send_tasks.discard(owner)

    @staticmethod
    def _resolve_target(to_handle: str) -> tuple[bool, int]:
        """Resolve the existing OneBot group/private target syntax."""
        is_group = to_handle.startswith("group:")
        value = to_handle.removeprefix("group:") if is_group else to_handle
        try:
            return is_group, int(value)
        except ValueError as exc:
            raise OneBotPlatformError("OUTBOUND_TARGET_UNKNOWN") from exc


__all__ = [
    "OneBotEndpoint",
    "OneBotPlatform",
    "OneBotPlatformError",
]
