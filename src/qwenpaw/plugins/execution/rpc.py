# -*- coding: utf-8 -*-
"""Bidirectional JSON-RPC dispatcher over the framed transport."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from .errors import (
    ProtocolValidationError,
    RpcClosedError,
    RpcError,
    RpcTimeoutError,
)
from .framing import FramedTransport
from .models import (
    CancelParams,
    RpcErrorObject,
    RpcMessage,
    RpcNotification,
    RpcRequest,
    RpcResponse,
    parse_rpc_message,
    validate_method_params,
)

JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603
RPC_REQUEST_ID_IN_USE = -32020
RPC_BACKPRESSURE = -32021
_TASK_SHUTDOWN_TIMEOUT = 0.1


def _reject_non_finite(value: str) -> object:
    """Reject non-standard JSON numeric constants."""
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _strict_json_dumps(value: object) -> str:
    """Encode one JSON-RPC message using strict JSON numbers."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _valid_request_id(value: object) -> str | int | None:
    """Return a valid request ID from a malformed JSON-RPC envelope."""
    if not isinstance(value, Mapping) or "id" not in value:
        return None
    request_id = value["id"]
    if (
        isinstance(request_id, (str, int))
        and not isinstance(request_id, bool)
        and request_id != ""
    ):
        return request_id
    return None


RequestHandler = Callable[[Any, RpcRequest], Any]
NotificationHandler = Callable[[Any, RpcNotification], Any]
PublicationCallback = Callable[[], Any]
PublicationPrepareCallback = Callable[[], Any]
PublicationWriteFailedCallback = Callable[[], Any]
PublicationAbortCallback = Callable[[str], Any]


@dataclass
class RpcResponsePublication:
    """Bind an internal result to response publication callbacks."""

    result: object
    on_prepare: PublicationPrepareCallback
    on_published: PublicationCallback
    on_write_failed: PublicationWriteFailedCallback
    on_write_deferred: PublicationCallback
    on_aborted: PublicationAbortCallback
    published: bool = False
    deferred: bool = False


@dataclass(frozen=True)
class RpcLimits:
    """Limits for one JSON-RPC peer."""

    max_pending_requests: int = 64
    max_incoming_requests: int = 64
    max_notification_tasks: int = 64
    request_timeout: float = 30.0

    def __post_init__(self) -> None:
        """Reject disabled or invalid RPC limits."""
        for name in (
            "max_pending_requests",
            "max_incoming_requests",
            "max_notification_tasks",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ValueError(f"{name} must be positive")
        if (
            not isinstance(self.request_timeout, (int, float))
            or isinstance(self.request_timeout, bool)
            or self.request_timeout <= 0
        ):
            raise ValueError("request_timeout must be positive")


@dataclass
class _PendingRequest:
    """One locally originated request and its completion future."""

    future: asyncio.Future[Any]
    timeout: float


@dataclass
class _RequestCancellation:
    """Track cancellation independently from task exception handling."""

    requested: bool = False


@dataclass
class _IncomingRequest:
    """Bind one inbound request task to its cancellation state."""

    task: asyncio.Task[Any]
    cancellation: _RequestCancellation


_CURRENT_CANCELLATION: ContextVar[_RequestCancellation | None] = ContextVar(
    "plugin_execution_request_cancellation",
    default=None,
)


def request_was_cancelled() -> bool:
    """Return whether the current request or task was cancelled."""
    cancellation = _CURRENT_CANCELLATION.get()
    if cancellation is not None and cancellation.requested:
        return True
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


class RpcCallNotSent(RpcClosedError):
    """Reject a request before it can enter transmission admission."""


class RpcPeer:
    """Run a continuously reading, bidirectional JSON-RPC peer."""

    def __init__(
        self,
        transport: FramedTransport,
        *,
        limits: RpcLimits | None = None,
        params_validator: Callable[[str, object], Any] | None = None,
    ) -> None:
        self._params_validator = params_validator or validate_method_params
        self._transport = transport
        self._limits = limits or RpcLimits()
        self._handlers: dict[str, RequestHandler] = {}
        self._notification_handlers: dict[str, NotificationHandler] = {}
        self._pending: dict[str | int, _PendingRequest] = {}
        self._incoming: dict[str | int, _IncomingRequest] = {}
        self._notification_tasks: set[asyncio.Task[Any]] = set()
        self._request_counter = 0
        self._reader_task: asyncio.Task[None] | None = None
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._started = asyncio.Event()
        self._duplicate_responses = 0
        self._dropped_notifications = 0

    @property
    def is_closed(self) -> bool:
        """Return whether the peer has stopped dispatching."""
        return self._closed

    @property
    def duplicate_responses(self) -> int:
        """Return the number of ignored duplicate or late responses."""
        return self._duplicate_responses

    @property
    def dropped_notifications(self) -> int:
        """Return the number of notifications dropped under backpressure."""
        return self._dropped_notifications

    def register_method(self, method: str, handler: RequestHandler) -> None:
        """Register a request handler for one method."""
        if not method or method in self._handlers:
            raise ValueError("method must be non-empty and unique")
        self._handlers[method] = handler

    def register_notification(
        self,
        method: str,
        handler: NotificationHandler,
    ) -> None:
        """Register a notification handler for one method."""
        if not method or method in self._notification_handlers:
            raise ValueError("method must be non-empty and unique")
        self._notification_handlers[method] = handler

    async def start(self) -> None:
        """Start the reader loop exactly once."""
        if self._reader_task is not None:
            return
        if self._closed:
            raise RpcClosedError("RPC peer is closed")
        self._reader_task = asyncio.create_task(self._reader_loop())
        self._started.set()

    async def wait_closed(self) -> None:
        """Wait until the reader loop has ended."""
        await self._started.wait()
        if self._reader_task is not None:
            with contextlib.suppress(asyncio.CancelledError, RpcClosedError):
                await self._reader_task

    def _next_request_id(self) -> str:
        """Return a process-local request identifier."""
        self._request_counter += 1
        return f"rpc-{self._request_counter}"

    def _claim_request_id(self, request_id: str | int | None) -> str | int:
        """Choose an unused local ID without overwriting an explicit call."""
        if request_id is None:
            request_id = self._next_request_id()
            while request_id in self._pending:
                request_id = self._next_request_id()
        elif _valid_request_id({"id": request_id}) is None:
            raise ValueError("request_id must be a nonempty string or integer")
        if request_id in self._pending:
            raise ValueError("request_id is already pending")
        if isinstance(request_id, str) and request_id.startswith("rpc-"):
            try:
                number = int(request_id[4:])
            except ValueError:
                number = 0
            if request_id == f"rpc-{number}":
                self._request_counter = max(self._request_counter, number)
        return request_id

    async def call(
        self,
        method: str,
        params: Mapping[str, Any] | list[Any] | None = None,
        *,
        timeout: float | None = None,
        request_id: str | int | None = None,
    ) -> Any:
        """Send a request and await its matching response.

        Explicit IDs identify one logical call per peer. Never reuse an ID
        after timeout/cancellation: a late reply can still arrive for it.
        """
        if self._closed or getattr(self._transport, "is_closed", False):
            raise RpcCallNotSent("RPC peer is closed before admission")
        if self._reader_task is None:
            await self.start()
        if self._closed or getattr(self._transport, "is_closed", False):
            raise RpcCallNotSent("RPC peer is closed before admission")
        if len(self._pending) >= self._limits.max_pending_requests:
            raise RpcError(
                RPC_BACKPRESSURE,
                "pending request limit reached",
                data={
                    "reason_code": "RPC_BACKPRESSURE",
                    "retryable": True,
                },
            )
        request_id = self._claim_request_id(request_id)
        future = asyncio.get_running_loop().create_future()
        request_timeout = (
            timeout if timeout is not None else self._limits.request_timeout
        )
        if request_timeout <= 0:
            raise ValueError("timeout must be positive")
        self._pending[request_id] = _PendingRequest(future, request_timeout)
        try:
            await self._send(RpcRequest(request_id, method, params))
            return await asyncio.wait_for(future, timeout=request_timeout)
        except asyncio.TimeoutError as exc:
            if not future.done():
                future.cancel()
            await self.notify(
                "request.cancel",
                CancelParams(
                    request_id=request_id,
                    reason="timeout",
                ).to_mapping(),
            )
            raise RpcTimeoutError(f"request timed out: {method}") from exc
        except asyncio.CancelledError:
            if not future.done():
                future.cancel()
            with contextlib.suppress(RpcClosedError):
                await self.notify(
                    "request.cancel",
                    CancelParams(
                        request_id=request_id,
                        reason="caller_cancelled",
                    ).to_mapping(),
                )
            raise
        finally:
            self._pending.pop(request_id, None)

    async def notify(
        self,
        method: str,
        params: Mapping[str, Any] | list[Any] | None = None,
    ) -> None:
        """Send a notification without creating a pending request."""
        if self._closed:
            raise RpcClosedError("RPC peer is closed")
        if self._reader_task is None:
            await self.start()
        await self._send(RpcNotification(method, params))

    async def _send(
        self,
        message: RpcMessage,
        *,
        publication: RpcResponsePublication | None = None,
    ) -> None:
        """Serialize and send one validated envelope."""
        try:
            encoded = _strict_json_dumps(message.to_mapping())
        except (TypeError, ValueError) as exc:
            raise ProtocolValidationError(
                "RPC message contains non-JSON data",
                reason_code="SCHEMA_MISMATCH",
            ) from exc
        if publication is None:
            await self._transport.send(encoded)
            return
        if not isinstance(message, RpcResponse) or message.error is not None:
            raise RuntimeError("publication requires a success response")

        async def prepare_write() -> str:
            """Build the final response at the writer visibility boundary."""
            result = publication.on_prepare()
            if inspect.isawaitable(result):
                result = await result
            return _strict_json_dumps(
                RpcResponse(message.id, result=result).to_mapping(),
            )

        def write_succeeded() -> Any:
            """Record that the output accepted the complete response frame."""
            result = publication.on_published()
            if not inspect.isawaitable(result):
                publication.published = True
                return None

            async def complete() -> None:
                """Publish one deferred acceptance under its state lock."""
                await result
                publication.published = True

            return complete()

        def write_failed() -> Any:
            """Rollback state when the frame was never accepted."""
            return publication.on_write_failed()

        def write_deferred() -> None:
            """Release publication fencing after timeout or cancellation."""
            publication.deferred = True
            publication.on_write_deferred()

        await self._transport.send(
            encoded,
            prepare_write=prepare_write,
            on_write_succeeded=write_succeeded,
            on_write_failed=write_failed,
            on_write_deferred=write_deferred,
        )

    async def _reader_loop(self) -> None:
        """Read frames and dispatch without waiting for handlers."""
        try:
            while not self._closed:
                raw = await self._transport.receive()
                await self._dispatch_raw(raw)
        except (RpcClosedError, asyncio.CancelledError):
            pass
        except Exception:
            await self._fail_pending()
        finally:
            if self._close_task is None:
                await self.aclose()

    async def _dispatch_raw(self, raw: str) -> None:
        """Parse one JSON frame and schedule its work."""
        message = await self._parse_raw_message(raw)
        if message is None:
            return
        if isinstance(message, RpcResponse):
            self._resolve_response(message)
        elif isinstance(message, RpcNotification):
            self._admit_notification(message)
        else:
            await self._admit_request(message)

    async def _parse_raw_message(self, raw: str) -> RpcMessage | None:
        """Parse one frame and emit the matching conformance error."""
        try:
            value = json.loads(raw, parse_constant=_reject_non_finite)
        except (json.JSONDecodeError, ValueError):
            await self._send_error(
                None,
                JSONRPC_PARSE_ERROR,
                "Parse error",
                allow_null_id=True,
            )
            return None
        try:
            message = parse_rpc_message(value)
        except ProtocolValidationError as exc:
            await self._send_error(
                _valid_request_id(value),
                JSONRPC_INVALID_REQUEST,
                "Invalid Request",
                data={"reason_code": exc.reason_code},
                allow_null_id=True,
            )
            return None
        return message

    def _admit_notification(self, message: RpcNotification) -> None:
        """Handle control notifications or admit bounded ordinary work."""
        if message.method == "request.cancel":
            self._cancel_incoming(message.params)
            return
        if (
            len(self._notification_tasks)
            >= self._limits.max_notification_tasks
        ):
            self._dropped_notifications += 1
            return
        task = asyncio.create_task(self._dispatch_notification(message))
        self._notification_tasks.add(task)
        task.add_done_callback(self._notification_done)

    async def _admit_request(self, message: RpcRequest) -> None:
        """Reject conflicting or overloaded requests before task creation."""
        if message.id in self._incoming:
            await self._send_error(
                message.id,
                RPC_REQUEST_ID_IN_USE,
                "request id is already in use",
                data={"reason_code": "RPC_REQUEST_ID_IN_USE"},
            )
            return
        if len(self._incoming) >= self._limits.max_incoming_requests:
            await self._send_error(
                message.id,
                RPC_BACKPRESSURE,
                "incoming request limit reached",
                data={
                    "reason_code": "RPC_BACKPRESSURE",
                    "retryable": True,
                },
            )
            return
        cancellation = _RequestCancellation()
        task = asyncio.create_task(
            self._dispatch_request(message, cancellation),
        )
        self._incoming[message.id] = _IncomingRequest(
            task=task,
            cancellation=cancellation,
        )
        task.add_done_callback(self._request_callback(message.id))

    def _request_callback(
        self,
        request_id: str | int,
    ) -> Callable[[asyncio.Task[Any]], None]:
        """Build a typed callback for one inbound request task."""

        def callback(completed: asyncio.Task[Any]) -> None:
            self._request_done(request_id, completed)

        return callback

    def _resolve_response(self, response: RpcResponse) -> None:
        """Complete one pending call and ignore late duplicate responses."""
        if response.id is None:
            self._duplicate_responses += 1
            return
        pending = self._pending.get(response.id)
        if pending is None:
            self._duplicate_responses += 1
            return
        if pending.future.done():
            self._duplicate_responses += 1
            return
        if response.error is not None:
            pending.future.set_exception(
                RpcError(
                    response.error.code,
                    response.error.message,
                    data=response.error.data,
                ),
            )
        else:
            pending.future.set_result(response.result)

    # pylint: disable=too-many-branches
    async def _dispatch_request(
        self,
        request: RpcRequest,
        cancellation: _RequestCancellation,
    ) -> None:
        """Run one request handler and return exactly one response."""
        token = _CURRENT_CANCELLATION.set(cancellation)
        publication: RpcResponsePublication | None = None
        response_sent = False
        try:
            handler = self._handlers.get(request.method)
            if handler is None:
                await self._send_error(
                    request.id,
                    JSONRPC_METHOD_NOT_FOUND,
                    "method not found",
                    data={"reason_code": "METHOD_NOT_FOUND"},
                )
                return
            params = self._params_validator(request.method, request.params)
            result = handler(params, request)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, RpcResponsePublication):
                publication = result
                result = publication.result
            if cancellation.requested:
                raise asyncio.CancelledError
            await self._send(
                RpcResponse(request.id, result=result),
                publication=publication,
            )
            response_sent = True
        except ProtocolValidationError as exc:
            if await self._abort_response_publication(
                publication,
                response_sent,
                "PLATFORM_RESULT_UNKNOWN",
            ):
                return
            await self._send_error(
                request.id,
                JSONRPC_INVALID_PARAMS,
                str(exc),
                data={"reason_code": exc.reason_code, "path": list(exc.path)},
            )
        except RpcError as exc:
            if await self._abort_response_publication(
                publication,
                response_sent,
                "PLATFORM_RESULT_UNKNOWN",
            ):
                return
            await self._send_error(
                request.id,
                exc.code,
                exc.message,
                data=exc.data,
            )
        except asyncio.CancelledError:
            if await self._abort_response_publication(
                publication,
                response_sent,
                "REQUEST_CANCELLED",
            ):
                return
            await self._send_error(
                request.id,
                JSONRPC_INTERNAL_ERROR,
                "request cancelled",
                data={"reason_code": "REQUEST_CANCELLED"},
            )
        except Exception as exc:
            if await self._abort_response_publication(
                publication,
                response_sent,
                "PLATFORM_RESULT_UNKNOWN",
            ):
                return
            await self._send_error(
                request.id,
                JSONRPC_INTERNAL_ERROR,
                "internal error",
                data={"reason_code": "INTERNAL_ERROR"},
            )
            _ = exc
        finally:
            _CURRENT_CANCELLATION.reset(token)

    async def _abort_response_publication(
        self,
        publication: RpcResponsePublication | None,
        response_sent: bool,
        reason_code: str,
    ) -> bool:
        """Abort provisional state unless its response was already sent."""
        if (
            response_sent
            or publication is not None
            and (publication.published or publication.deferred)
        ):
            return True
        if publication is not None:
            await self._run_publication_callback(
                lambda: publication.on_aborted(reason_code),
            )
            return publication.published
        return False

    async def _run_publication_callback(
        self,
        callback: PublicationCallback,
    ) -> None:
        """Complete publication bookkeeping despite task cancellation."""
        result = callback()
        if not inspect.isawaitable(result):
            return
        cleanup = asyncio.ensure_future(result)
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                continue
        cleanup.result()

    async def _dispatch_notification(
        self,
        notification: RpcNotification,
    ) -> None:
        """Run one notification handler without sending a response."""
        handler = self._notification_handlers.get(notification.method)
        if handler is None:
            return
        try:
            params = self._params_validator(
                notification.method,
                notification.params,
            )
            result = handler(params, notification)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            _ = exc

    def _cancel_incoming(self, params: object) -> None:
        """Cancel a running inbound request by protocol request ID."""
        try:
            cancel = CancelParams.from_mapping(params)
        except ProtocolValidationError:
            return
        incoming = self._incoming.get(cancel.request_id)
        if incoming is not None and not incoming.task.done():
            incoming.cancellation.requested = True
            incoming.task.cancel()

    async def _send_error(
        self,
        request_id: str | int | None,
        code: int,
        message: str,
        *,
        data: object = None,
        allow_null_id: bool = False,
    ) -> None:
        """Send one JSON-RPC error response when an ID is available."""
        if (request_id is None and not allow_null_id) or self._closed:
            return
        with contextlib.suppress(RpcClosedError):
            await self._send(
                RpcResponse(
                    request_id,
                    error=RpcErrorObject(code, message, data),
                ),
            )

    async def _fail_pending(self) -> None:
        """Fail all locally pending calls after a transport error."""
        for pending in self._pending.values():
            if not pending.future.done():
                pending.future.set_exception(
                    RpcClosedError("RPC peer stopped"),
                )

    def _request_done(
        self,
        request_id: str | int,
        task: asyncio.Task[Any],
    ) -> None:
        """Remove a completed inbound request task."""
        incoming = self._incoming.get(request_id)
        if incoming is not None and incoming.task is task:
            self._incoming.pop(request_id, None)
        self._consume_task_exception(task)

    def _notification_done(self, task: asyncio.Task[Any]) -> None:
        """Remove and consume one completed notification task."""
        self._notification_tasks.discard(task)
        self._consume_task_exception(task)

    @staticmethod
    def _consume_task_exception(task: asyncio.Task[Any]) -> None:
        """Consume callback exceptions to avoid unhandled-task warnings."""
        with contextlib.suppress(asyncio.CancelledError, Exception):
            task.result()

    async def aclose(self) -> None:
        """Close the peer and resolve every pending operation."""
        close_task = self._close_task
        if close_task is None:
            self._closed = True
            close_task = asyncio.create_task(
                self._close_resources(asyncio.current_task()),
            )
            self._close_task = close_task
        await asyncio.shield(close_task)

    async def _close_resources(
        self,
        excluded_task: asyncio.Task[Any] | None,
    ) -> None:
        """Cancel owned work and close the transport exactly once."""
        tasks: list[asyncio.Task[Any]] = []
        reader_task = self._reader_task
        if (
            reader_task is not None
            and reader_task is not excluded_task
            and not reader_task.done()
        ):
            reader_task.cancel()
            tasks.append(reader_task)
        for incoming in self._incoming.values():
            task = incoming.task
            if task is not excluded_task and not task.done():
                incoming.cancellation.requested = True
                task.cancel()
                tasks.append(task)
        for task in self._notification_tasks:
            if task is not excluded_task and not task.done():
                task.cancel()
                tasks.append(task)
        await self._fail_pending()
        with contextlib.suppress(Exception):
            await self._transport.aclose()
        if tasks:
            await asyncio.wait(
                tasks,
                timeout=_TASK_SHUTDOWN_TIMEOUT,
            )


__all__ = [
    "JSONRPC_INVALID_PARAMS",
    "JSONRPC_INVALID_REQUEST",
    "JSONRPC_INTERNAL_ERROR",
    "JSONRPC_METHOD_NOT_FOUND",
    "JSONRPC_PARSE_ERROR",
    "RPC_BACKPRESSURE",
    "RPC_REQUEST_ID_IN_USE",
    "request_was_cancelled",
    "RpcCallNotSent",
    "RpcLimits",
    "RpcPeer",
]
