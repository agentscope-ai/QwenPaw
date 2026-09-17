# -*- coding: utf-8 -*-
# pylint:disable=too-many-public-methods
"""Native Messaging bridge state for Chrome browser control mode."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

from ...governance.error_codes import BrowserErrorCode
from ....utils.logging import sanitize_log_value
from .protocol import (
    COMMAND_OBSERVED_STATES,
    ReceiptState,
    contract_snapshot,
    MIN_COMPATIBLE_PROTOCOL_VERSION,
    NM_MAX_OUTBOUND_BYTES,
    PROTOCOL_VERSION as SUPPORTED_PROTOCOL_VERSION,
)
from ...telemetry.trace import record_browser_trace_event

JSONRPC_VERSION = "2.0"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
logger = logging.getLogger(__name__)

_CLOSE_CODE_MESSAGES = {
    4000: "Chrome closed the native messaging host (normal shutdown).",
    4001: "The native messaging channel received a malformed frame; "
    "the connection was reset.",
    4002: "A page observation was too large for the native messaging "
    "channel; narrow the query and retry.",
    4003: "The native messaging host hit an internal error; see "
    "~/.qwenpaw/logs/nm-host.log.",
}
_NO_CLOSE_REASON = "NM bridge disconnected (no close reason reported)."


def _disconnect_message(close_code: int | None, close_reason: str) -> str:
    """Render a remote close frame into agent-actionable recovery text."""
    base = _CLOSE_CODE_MESSAGES.get(close_code or 0, _NO_CLOSE_REASON)
    if close_reason:
        return f"{base} Reported reason: {close_reason}"
    return base


class NMBridgeError(RuntimeError):
    """Base error for Native Messaging bridge failures."""

    browser_error_code = str(BrowserErrorCode.UNKNOWN.value)

    def __init__(
        self,
        message: str = "",
        *,
        code: str | BrowserErrorCode | None = None,
    ) -> None:
        super().__init__(message or self.__class__.__name__)
        if code is not None:
            self.browser_error_code = (
                code.value if isinstance(code, BrowserErrorCode) else str(code)
            )


class NMBridgeDisconnectedError(NMBridgeError):
    """Raised when no Native Messaging WebSocket is connected."""

    browser_error_code = str(BrowserErrorCode.BRIDGE_DISCONNECTED.value)


class BridgeNotReadyError(NMBridgeError):
    """Raised until the Native Messaging hello exchange is acknowledged."""

    browser_error_code = str(BrowserErrorCode.BRIDGE_DISCONNECTED.value)


class NMBridgeTimeoutError(NMBridgeError):
    """Transport uncertainty: no response was observed before deadline."""

    browser_error_code = str(BrowserErrorCode.BRIDGE_REQUEST_TIMEOUT.value)


class NMBridgeWireError(NMBridgeError):
    """Observed extension failure reported in a JSON-RPC error envelope."""

    browser_error_code = str(BrowserErrorCode.UNKNOWN.value)

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        data: object | None = None,
    ) -> None:
        super().__init__(message, code=code)
        self.data = data


class BridgeMessageTooLargeError(NMBridgeError):
    """Raised when a command would exceed Chrome's host-to-extension limit."""

    browser_error_code = str(BrowserErrorCode.BROWSER_COMMAND_TOO_LARGE.value)


class CommandTransportUncertainError(NMBridgeError):
    """No response was observed; this never authorizes command replay."""

    def __init__(
        self,
        message: str,
        *,
        reconcile_keys: tuple[tuple[str, str], ...],
    ) -> None:
        super().__init__(message, code="command_transport_uncertain")
        self.reconcile_keys = reconcile_keys
        self.observed_state = "UNKNOWN"


class TabOccupiedError(NMBridgeError):
    """Raised when a tab is already held by another holder."""

    browser_error_code = str(BrowserErrorCode.BROWSER_TAB_OCCUPIED.value)


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    """One observed extension receipt for an exact command."""

    session_id: str
    command_id: str
    command_fingerprint: str
    state: ReceiptState
    result: object | None = None


@dataclass(frozen=True, slots=True)
class CommandFactProjection:
    """Host projection when a target receipt is absent or evicted."""

    observed_state: str


@dataclass(frozen=True, slots=True)
class CommandExecutionResponse:
    """Typed command.execute transport response."""

    receipt: CommandReceipt


@dataclass(frozen=True, slots=True)
class CommandStatusResponse:
    """Typed read-only status response for one target command."""

    target_receipt: CommandReceipt | None
    target_command_fact: CommandFactProjection


class NMBridge:
    """Central bridge that owns Native Messaging connection state."""

    def __init__(self) -> None:
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._ws: Any | None = None
        self._next_id = 1
        self._lock = asyncio.Lock()
        self._event_handlers: dict[
            str,
            list[Callable[[dict[str, Any]], Any]],
        ] = defaultdict(list)
        self.protocol_error: dict[str, Any] | None = None
        self._ready: bool = False
        self._connected_since: datetime | None = None
        self._extension_version = ""
        self._extension_contract: dict[str, object] = {}
        self._extension_build: dict[str, object] = {}
        self._last_extension_disconnect: dict[str, object] = {}
        self._last_connected_at: datetime | None = None
        self._last_disconnected_at: datetime | None = None
        self._last_disconnect_reason = ""
        self._last_error_code = ""
        self._last_error_message = ""
        self._last_request_timeout_at: datetime | None = None
        self._reconnect_count = 0
        self._last_self_test: dict[str, Any] | None = None
        self._ready_observers: list[Callable[[], Any]] = []
        self._closed = False

    def get_connection(self) -> "NMBridge":
        return self

    def add_event_listener(
        self,
        method: str,
        handler: Callable[[dict[str, Any]], Any],
    ) -> Callable[[], None]:
        self._event_handlers[method].append(handler)

        def unsubscribe() -> None:
            if handler in self._event_handlers[method]:
                self._event_handlers[method].remove(handler)

        return unsubscribe

    def is_connected(self) -> bool:
        return bool(not self._closed and self._ws is not None and self._ready)

    def owns_websocket(self, websocket: Any) -> bool:
        """Return whether *websocket* is this bridge's active socket."""
        return websocket is self._ws

    @property
    def websocket(self) -> Any | None:
        """Expose the active socket to the WebSocket route lifecycle."""
        return self._ws

    def subscribe_ready(
        self,
        callback: Callable[[], Any],
    ) -> Callable[[], None]:
        """Schedule *callback* after successful hello acknowledgement."""
        self._ready_observers.append(callback)

        def unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._ready_observers.remove(callback)

        return unsubscribe

    def _mark_ready(
        self,
        _websocket: Any,
        hello: Mapping[str, Any] | None = None,
    ) -> None:
        """Commit a successful hello after its acknowledgement is sent."""
        if self._closed:
            return
        now = datetime.now(UTC)
        if self._last_connected_at is not None:
            self._reconnect_count += 1
        self._ready = True
        self._connected_since = now
        self._last_connected_at = now
        self._last_error_code = ""
        self._last_error_message = ""
        self._update_extension_version(hello or {})
        contract_ok = bool(self._extension_contract) and all(
            self._extension_contract.get(key) == value
            for key, value in contract_snapshot().items()
        )
        commit = str(self._extension_build.get("commit") or "unknown")
        built_at = str(self._extension_build.get("builtAt") or "unknown")
        logger.info(
            "browser.ws.hello extension_version=%s commit=%s builtAt=%s "
            "contract_ok=%s",
            sanitize_log_value(self._extension_version or "unknown"),
            sanitize_log_value(commit),
            sanitize_log_value(built_at),
            contract_ok,
        )
        logger.info("browser.ws.handshake_complete")
        for callback in list(self._ready_observers):
            asyncio.create_task(self._safe_observer(callback))

    def _mark_not_ready(
        self,
        reason: str,
        *,
        message: str = "Native Messaging bridge disconnected",
        error_code: str
        | BrowserErrorCode = BrowserErrorCode.BRIDGE_DISCONNECTED,
    ) -> None:
        """Commit a disconnection and fail requests waiting on this bridge."""
        self._ready = False
        self._connected_since = None
        self._extension_version = ""
        self._extension_contract = {}
        self._extension_build = {}
        self._last_disconnected_at = datetime.now(UTC)
        self._last_disconnect_reason = reason
        self._last_error_code = str(error_code)
        self._last_error_message = message
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(NMBridgeDisconnectedError(message))
        self._pending.clear()
        _record_lifecycle_trace(
            "close" if reason == "closed" else "disconnect",
            status="error",
            error_code=error_code,
            metadata={"reason": reason},
        )

    async def _safe_observer(self, callback: Callable[[], Any]) -> None:
        """Run one ready observer without exposing it to the socket loop."""
        try:
            result = callback()
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception("Native Messaging ready observer failed")

    def snapshot(self) -> dict[str, Any]:
        """Return a stable, read-only view of bridge connection state."""
        return {
            "connected": self.is_connected(),
            "connected_since": self._connected_since,
            "extension_version": self._extension_version,
            "extension_contract": dict(self._extension_contract),
            "extension_build": dict(self._extension_build),
            "last_extension_disconnect": dict(
                self._last_extension_disconnect,
            ),
            "last_connected_at": self._last_connected_at,
            "last_disconnected_at": self._last_disconnected_at,
            "last_disconnect_reason": self._last_disconnect_reason,
            "last_error_code": self._last_error_code,
            "last_error_message": self._last_error_message,
            "last_request_timeout_at": self._last_request_timeout_at,
            "reconnect_count": self._reconnect_count,
            "last_self_test": self._last_self_test,
        }

    def record_self_test(self, result: dict[str, Any]) -> None:
        """Retain the latest read-only status diagnosis on the bridge."""
        self._last_self_test = result

    def _update_extension_version(self, payload: Mapping[str, Any]) -> None:
        contract = payload.get("contract")
        if isinstance(contract, Mapping):
            self._extension_contract = dict(contract)
        build = payload.get("build")
        if isinstance(build, Mapping):
            self._extension_build = dict(build)
        last_disconnect = payload.get("lastDisconnect")
        if isinstance(last_disconnect, Mapping):
            self._last_extension_disconnect = dict(last_disconnect)
            logger.info(
                "Native Messaging extension reported last disconnect "
                "reason=%s at=%s",
                sanitize_log_value(last_disconnect.get("reason") or "unknown"),
                sanitize_log_value(last_disconnect.get("at") or "unknown"),
            )
        version = (
            payload.get("extension_version")
            or payload.get("extensionVersion")
            or payload.get("version")
        )
        version_text = str(version or "").strip()
        if version_text:
            self._extension_version = version_text

    def _mark_request_timeout(self, method: str, timeout: float) -> None:
        """Record a request timeout in the bridge-owned lifecycle snapshot."""
        self._last_error_code = BrowserErrorCode.BRIDGE_REQUEST_TIMEOUT.value
        self._last_error_message = (
            f"request '{method}' timed out after {timeout}s"
        )
        self._last_request_timeout_at = datetime.now(UTC)
        _record_lifecycle_trace(
            "request_timeout",
            status="error",
            error_code=BrowserErrorCode.BRIDGE_REQUEST_TIMEOUT,
            metadata={"method": method, "timeout": timeout},
        )

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def attach_websocket(self, websocket: Any) -> None:
        if self._closed:
            raise NMBridgeDisconnectedError("NM bridge is closed")
        self._ws = websocket

    async def detach_websocket(
        self,
        websocket: Any | None = None,
        *,
        reason: str = "disconnected",
        close_code: int | None = None,
        close_reason: str = "",
    ) -> None:
        if websocket is not None and websocket is not self._ws:
            return
        self._mark_not_ready(
            reason=reason,
            message=_disconnect_message(close_code, close_reason),
        )
        self._ws = None

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        websocket = self._ws
        if websocket is not None:
            await self.detach_websocket(websocket, reason="closed")
        else:
            self._mark_not_ready(
                reason="closed",
                message="NM bridge closed",
            )

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        timeout = (
            DEFAULT_REQUEST_TIMEOUT_SECONDS if timeout is None else timeout
        )
        if self._closed:
            raise NMBridgeDisconnectedError("NM bridge is closed")
        if not self._ready:
            raise BridgeNotReadyError("Bridge is not ready")

        async with self._lock:
            request_id = self._next_id
            self._next_id += 1

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        message = {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        try:
            ws = self._ws
            if ws is None or not self._ready:
                raise BridgeNotReadyError("Bridge is not ready")
            encoded = json.dumps(message, separators=(",", ":")).encode(
                "utf-8",
            )
            if len(encoded) > NM_MAX_OUTBOUND_BYTES:
                raise BridgeMessageTooLargeError(
                    f"command payload is {len(encoded)} bytes, above Chrome's "
                    f"{NM_MAX_OUTBOUND_BYTES}-byte host-to-extension limit",
                )
            await ws.send_json(message)
            response = await asyncio.wait_for(future, timeout=timeout)
            if "error" in response:
                error = response["error"]
                raise NMBridgeWireError(
                    _wire_error_message(error),
                    code=(
                        error.get("code")
                        if isinstance(error, Mapping)
                        else None
                    ),
                    data=(
                        error.get("data")
                        if isinstance(error, Mapping)
                        else None
                    ),
                )
            result = response.get("result")
            if isinstance(result, Mapping):
                return dict(result)
            if isinstance(result, list):
                return result
            return {}
        except asyncio.TimeoutError as exc:
            self._mark_request_timeout(method, timeout)
            raise NMBridgeTimeoutError(
                f"request '{method}' timed out after {timeout}s",
            ) from exc
        except NMBridgeDisconnectedError:  # pylint: disable=try-except-raise
            raise
        except (ConnectionError, OSError) as exc:
            await self.detach_websocket(ws, reason="send_failed")
            if future.done():
                future.exception()
            raise NMBridgeDisconnectedError(
                f"NM bridge local send failed: {exc}",
            ) from exc
        finally:
            self._pending.pop(request_id, None)

    # RESERVED, NOT WIRED. At-most-once command receipts are implemented on
    # both sides but no verb reaches them; mutating verbs still use cdp.send.
    # When they are wired, only CONCLUSIVE_OBSERVED_STATES may drive a
    # decision - every other observed state is uncertain and differs for
    # diagnostics only.
    # Rationale and remaining gaps:
    # .docs/20260727-unified-browser-adr-transport-uncertainty.md
    async def execute_command(
        self,
        *,
        session_id: str,
        command_id: str,
        command_fingerprint: str,
        command_type: str,
        dispatch_context: Mapping[str, object],
        payload: Mapping[str, object],
        timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> CommandExecutionResponse:
        """Execute one independently identified extension command."""
        normalized_session = _required_command_text(session_id, "sessionId")
        normalized_command = _required_command_text(command_id, "commandId")
        normalized_fingerprint = _required_command_text(
            command_fingerprint,
            "commandFingerprint",
        )
        try:
            response = await self.request(
                "command.execute",
                {
                    "sessionId": normalized_session,
                    "commandId": normalized_command,
                    "commandFingerprint": normalized_fingerprint,
                    "commandType": _required_command_text(
                        command_type,
                        "commandType",
                    ),
                    "dispatchContext": dict(dispatch_context),
                    "payload": dict(payload),
                },
                timeout=timeout,
            )
        except (NMBridgeTimeoutError, NMBridgeDisconnectedError) as exc:
            raise CommandTransportUncertainError(
                "command response was not observed",
                reconcile_keys=((normalized_command, normalized_fingerprint),),
            ) from exc
        if not isinstance(response, Mapping):
            raise NMBridgeError("command.execute returned an invalid result")
        return CommandExecutionResponse(
            receipt=_parse_command_receipt(response.get("receipt")),
        )

    async def query_command_status(
        self,
        *,
        session_id: str,
        target_command_id: str,
        target_command_fingerprint: str,
        timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> CommandStatusResponse:
        """Issue a fresh read-only STATUS_QUERY for one target command."""
        normalized_target = _required_command_text(
            target_command_id,
            "targetCommandId",
        )
        normalized_target_fingerprint = _required_command_text(
            target_command_fingerprint,
            "targetCommandFingerprint",
        )
        try:
            response = await self.request(
                "command.status",
                {
                    "sessionId": _required_command_text(
                        session_id,
                        "sessionId",
                    ),
                    "targetCommandId": normalized_target,
                    "targetCommandFingerprint": normalized_target_fingerprint,
                },
                timeout=timeout,
            )
        except (NMBridgeTimeoutError, NMBridgeDisconnectedError) as exc:
            raise CommandTransportUncertainError(
                "status response was not observed",
                reconcile_keys=(
                    (normalized_target, normalized_target_fingerprint),
                ),
            ) from exc
        if not isinstance(response, Mapping):
            raise NMBridgeError("command.status returned an invalid result")
        target_payload = response.get("targetReceipt")
        return CommandStatusResponse(
            target_receipt=(
                _parse_command_receipt(target_payload)
                if target_payload is not None
                else None
            ),
            target_command_fact=_parse_command_fact(
                response.get("targetCommandFact"),
            ),
        )

    async def send_cdp(
        self,
        tab_id: int,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self.request(
            "cdp.send",
            {
                "tabId": tab_id,
                "method": method,
                "params": params or {},
            },
        )
        return response if isinstance(response, Mapping) else {}

    async def discover_tabs(self) -> list[dict[str, Any]]:
        response = await self.request("tabs.list", {"query": {}})
        return response if isinstance(response, list) else []

    async def handle_ws_message(
        self,
        message: dict[str, Any],
    ) -> dict[str, Any] | None:
        hello_ack = self.on_hello(message)
        if hello_ack is not None:
            return hello_ack

        request_id = message.get("id")
        if request_id in self._pending:
            future = self._pending[request_id]
            if not future.done():
                future.set_result(message)
            return None

        error = message.get("error")
        if request_id is None and isinstance(error, Mapping):
            in_flight = len(self._pending)
            error_code = error.get("code")
            safe_error_code = sanitize_log_value(error_code)
            if in_flight == 1:
                future = next(iter(self._pending.values()))
                if not future.done():
                    future.set_exception(
                        NMBridgeWireError(
                            _wire_error_message(error),
                            code=error_code,
                            data=error.get("data"),
                        ),
                    )
                logger.info(
                    "Native Messaging orphan error assigned to sole request "
                    "in_flight=%s code=%s",
                    in_flight,
                    safe_error_code,
                )
            elif in_flight == 0:
                logger.info(
                    "Native Messaging orphan error with no request "
                    "in_flight=%s code=%s",
                    in_flight,
                    safe_error_code,
                )
            else:
                logger.warning(
                    "Native Messaging orphan error left unassigned "
                    "in_flight=%s code=%s",
                    in_flight,
                    safe_error_code,
                )
            return None
        if request_id is not None and isinstance(error, Mapping):
            logger.info(
                "Native Messaging stale error id=%s in_flight=%s code=%s",
                sanitize_log_value(request_id),
                len(self._pending),
                sanitize_log_value(error.get("code")),
            )
            return None

        method = message.get("method")
        if isinstance(method, str):
            params = message.get("params")
            event = params if isinstance(params, dict) else {}
            await self._dispatch_event(method, event)
        return None

    def on_hello(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Build the hello acknowledgement without changing readiness."""
        return self.handle_bridge_hello(message)

    async def _dispatch_event(
        self,
        method: str,
        event: dict[str, Any],
    ) -> None:
        """Dispatch an event without letting one handler isolate its peers."""
        for handler in list(self._event_handlers.get(method, [])):
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception(
                    "Native Messaging bridge event handler failed: %s",
                    sanitize_log_value(method),
                )

    def handle_bridge_hello(
        self,
        message: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Return hello_ack for chrome backend handshakes."""
        if message.get("type") != "hello":
            return None
        raw_protocol_version = message.get("protocolVersion")
        if raw_protocol_version is None:
            raw_protocol_version = message.get("protocol_version", 1)
        try:
            actual_protocol_version = int(raw_protocol_version)
        except (OverflowError, TypeError, ValueError):
            return self._protocol_version_rejection(
                str(raw_protocol_version),
                entry_id=str(message.get("entryId") or ""),
            )
        if (
            actual_protocol_version < MIN_COMPATIBLE_PROTOCOL_VERSION
            or actual_protocol_version > SUPPORTED_PROTOCOL_VERSION
        ):
            return self._protocol_version_rejection(
                actual_protocol_version,
                entry_id=str(message.get("entryId") or ""),
            )
        entry_id = str(message.get("entryId") or "")
        self.protocol_error = None
        self._update_extension_version(message)
        return {
            "type": "hello_ack",
            "status": "ok",
            "entryId": entry_id,
            "protocolVersion": SUPPORTED_PROTOCOL_VERSION,
        }

    def _protocol_version_rejection(
        self,
        actual_protocol_version: int | str,
        *,
        entry_id: str,
    ) -> dict[str, Any]:
        self.protocol_error = {
            "code": str(
                BrowserErrorCode.BROWSER_PROTOCOL_VERSION_MISMATCH.value,
            ),
            "expected_min_protocol_version": (MIN_COMPATIBLE_PROTOCOL_VERSION),
            "expected_protocol_version": SUPPORTED_PROTOCOL_VERSION,
            "actual_protocol_version": actual_protocol_version,
        }
        self._clear_handshake()
        return {
            "type": "hello_ack",
            "status": "error",
            "entryId": entry_id,
            **self.protocol_error,
        }

    def _clear_handshake(self) -> None:
        self._mark_not_ready(
            "protocol_error",
            message="Native Messaging bridge rejected hello",
            error_code=BrowserErrorCode.BROWSER_PROTOCOL_VERSION_MISMATCH,
        )
        self._ws = None

    def remove_event_listener(
        self,
        method: str,
        handler: Callable[[dict[str, Any]], Any],
    ) -> None:
        handlers = self._event_handlers.get(method)
        if not handlers:
            return
        with contextlib.suppress(ValueError):
            handlers.remove(handler)


def _required_command_text(value: object, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise NMBridgeError(
            f"{field_name} is required",
            code="command_identity_invalid",
        )
    return normalized


def _parse_command_receipt(value: object) -> CommandReceipt:
    if not isinstance(value, Mapping):
        raise NMBridgeError("extension command receipt is invalid")
    try:
        state = ReceiptState(str(value.get("state") or ""))
    except ValueError as exc:
        raise NMBridgeError(
            "extension command receipt state is invalid",
        ) from exc
    return CommandReceipt(
        session_id=_required_command_text(value.get("sessionId"), "sessionId"),
        command_id=_required_command_text(value.get("commandId"), "commandId"),
        command_fingerprint=_required_command_text(
            value.get("commandFingerprint"),
            "commandFingerprint",
        ),
        state=state,
        result=value.get("result"),
    )


def _parse_command_fact(value: object) -> CommandFactProjection:
    observed = (
        str(value.get("observedState") or "")
        if isinstance(value, Mapping)
        else ""
    )
    if observed not in COMMAND_OBSERVED_STATES:
        raise NMBridgeError(
            f"extension reported an unknown observed state: {observed!r}",
            code="command_identity_invalid",
        )
    return CommandFactProjection(observed)


def _wire_error_message(value: object) -> str:
    if isinstance(value, Mapping):
        return str(value.get("message") or value.get("code") or "wire error")
    return str(value or "wire error")


def _record_lifecycle_trace(
    action: str,
    *,
    status: str,
    error_code: BrowserErrorCode | str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    record_browser_trace_event(
        session_id="nm-bridge",
        phase="bridge_lifecycle",
        backend_id="user.chrome_extension",
        selected_context="user",
        action=action,
        status=status,
        error_code=str(error_code or ""),
        metadata=metadata,
    )


_GLOBAL_BRIDGE: NMBridge | None = None


def get_nm_bridge() -> NMBridge:
    global _GLOBAL_BRIDGE
    if _GLOBAL_BRIDGE is None or _GLOBAL_BRIDGE.is_closed:
        _GLOBAL_BRIDGE = NMBridge()
    return _GLOBAL_BRIDGE


async def shutdown_nm_bridge() -> None:
    global _GLOBAL_BRIDGE
    if _GLOBAL_BRIDGE is None:
        return
    await _GLOBAL_BRIDGE.close()
    _GLOBAL_BRIDGE = None
