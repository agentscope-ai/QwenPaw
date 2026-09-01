# -*- coding: utf-8 -*-
"""MCP 2026-07-28 Streamable-HTTP clients (stateless + dual-era auto).

``HttpStatelessClient`` speaks modern per-request ``_meta`` / headers.
``HttpAutoClient`` tries modern first, then falls back once to
``HttpStatefulClient`` for handshake-era peers.
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
import logging
import re
import time
from datetime import timedelta
from typing import Any

import httpx
from mcp import types as mcp_types

from ...__version__ import __version__ as _QWENPAW_VERSION

logger = logging.getLogger(__name__)

_MODERN_PROTOCOL_VERSION = "2026-07-28"
# Streamable-HTTP handshake-era only; 2024-11-05 is HTTP+SSE, not fallback.
_HANDSHAKE_PROTOCOL_VERSIONS = frozenset(
    {"2025-03-26", "2025-06-18", "2025-11-25"},
)

_MCP_PROTOCOL_VERSION_HEADER = "mcp-protocol-version"
_MCP_METHOD_HEADER = "mcp-method"
_MCP_NAME_HEADER = "mcp-name"
_MCP_PARAM_HEADER_PREFIX = "mcp-param-"
_X_MCP_HEADER = "x-mcp-header"

_PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
_CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"
_CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"

_JSONRPC_METHOD_NOT_FOUND = -32601
_JSONRPC_HEADER_MISMATCH = -32020
_JSONRPC_MISSING_REQUIRED_CLIENT_CAPABILITY = -32021
_JSONRPC_UNSUPPORTED_PROTOCOL_VERSION = -32022
_MCP_SESSION_ID_HEADER = "mcp-session-id"

_LIST_TOOLS_MAX_PAGES = 50
_IEEE754_SAFE_INT_MIN = -(2**53 - 1)
_IEEE754_SAFE_INT_MAX = 2**53 - 1

_B64_SENTINEL = re.compile(r"^=\?base64\?.*\?=$")
_HEADER_SAFE = re.compile(r"^[\x20-\x7E]*$")
_HTTP_FIELD_NAME = re.compile(r"^[!#$%&'*+\-.0-9A-Z^_`a-z|~]+$")
_INT_STRING = re.compile(r"^-?\d+$")
# Spec primitives only; ["string","null"] rejects the whole tool.
_PRIMITIVE_HEADER_TYPES = frozenset({"string", "integer", "boolean"})
# Skip instance-data keys so example x-mcp-header does not reject the tool.
_SKIP_GENERIC_WALK_KEYS = frozenset(
    {
        "properties",
        "example",
        "examples",
        "default",
        "const",
        "enum",
        "required",
    },
)
# (property_path, header_name, json_type)
_HeaderBinding = tuple[tuple[str, ...], str, str]
_MISSING = object()


class _LegacyProtocolError(Exception):
    """Handshake-era peer; triggers AutoClient fallback."""


class _JsonRpcError(Exception):
    """JSON-RPC error returned by an MCP server."""

    def __init__(
        self,
        code: int,
        message: str,
        data: Any = None,
        *,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.data = data
        self.http_status = http_status

    @classmethod
    def from_payload(
        cls,
        payload: Any,
        *,
        http_status: int | None = None,
    ) -> "_JsonRpcError":
        if not isinstance(payload, dict):
            return cls(-32000, str(payload), None, http_status=http_status)
        try:
            code_int = int(payload.get("code", -32000))
        except (TypeError, ValueError):
            code_int = -32000
        msg = str(payload.get("message") or "MCP JSON-RPC error")
        return cls(code_int, msg, payload.get("data"), http_status=http_status)


def _is_jsonrpc_envelope(data: Any) -> bool:
    return isinstance(data, dict) and data.get("jsonrpc") == "2.0"


def _ids_match(left: Any, right: Any) -> bool:
    return left == right or str(left) == str(right)


def _timeout_seconds(value: float | timedelta) -> float:
    return (
        value.total_seconds() if isinstance(value, timedelta) else float(value)
    )


def _normalized_port(url: httpx.URL) -> int:
    if url.port is not None:
        return url.port
    return 443 if url.scheme == "https" else 80


def _same_origin(left: httpx.URL, right: httpx.URL) -> bool:
    return (
        left.scheme == right.scheme
        and left.host == right.host
        and _normalized_port(left) == _normalized_port(right)
    )


def _is_https_upgrade(url: httpx.URL, location: httpx.URL) -> bool:
    """Allow http:80 → https:443 on the same host only."""
    return (
        url.host == location.host
        and url.scheme == "http"
        and _normalized_port(url) == 80
        and location.scheme == "https"
        and _normalized_port(location) == 443
    )


def _headers_without_session_id(
    headers: dict[str, str] | None,
) -> dict[str, str]:
    """Copy headers, dropping leftover Mcp-Session-Id.

    Does not mutate the caller-owned mapping.
    """
    return {
        key: value
        for key, value in (headers or {}).items()
        if key.casefold() != _MCP_SESSION_ID_HEADER
    }


def _encode_mcp_header_value(value: str) -> str:
    """Encode a header value, using the MCP base64 sentinel when needed."""
    if (
        _HEADER_SAFE.fullmatch(value)
        and value == value.strip()
        and not _B64_SENTINEL.fullmatch(value)
    ):
        return value
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"=?base64?{encoded}?="


def _supported_versions_from_payload(payload: Any) -> list[str] | None:
    """Extract supported protocol versions from discover / -32022 payloads."""
    if not isinstance(payload, dict):
        return None
    # Official keys: discover supportedVersions, -32022 supported.
    raw = payload.get("supportedVersions")
    if raw is None and isinstance(payload.get("supported"), list):
        raw = payload["supported"]
    if not isinstance(raw, list):
        return None
    return [str(item) for item in raw if isinstance(item, str)]


def _is_legacy_protocol_evidence(
    *,
    status_code: int | None = None,
    error_code: int | None = None,
    supported_versions: list[str] | None = None,
) -> bool:
    # -32020/-32021/-32022 are modern errors, never handshake evidence.
    # Discover -32601 is classified in _negotiate, not here.
    if error_code in (
        _JSONRPC_HEADER_MISMATCH,
        _JSONRPC_MISSING_REQUIRED_CLIENT_CAPABILITY,
        _JSONRPC_UNSUPPORTED_PROTOCOL_VERSION,
    ):
        return False
    if supported_versions is not None:
        has_hs = any(
            v in _HANDSHAKE_PROTOCOL_VERSIONS for v in supported_versions
        )
        has_mod = _MODERN_PROTOCOL_VERSION in supported_versions
        return bool(supported_versions) and has_hs and not has_mod
    return status_code in {400, 404, 405}


class _ModernCallToolResult(mcp_types.CallToolResult):
    """Accept any JSON structuredContent per MCP 2026-07-28."""

    structuredContent: Any = None


def _normalize_call_tool_result(result: Any) -> Any:
    """Normalize snake_case CallToolResult aliases for the installed SDK."""
    if not isinstance(result, dict):
        return result
    out = dict(result)
    for camel, snake in (
        ("structuredContent", "structured_content"),
        ("isError", "is_error"),
        ("resultType", "result_type"),
    ):
        if camel not in out and snake in out:
            out[camel] = out.pop(snake)
    if "content" not in out and "structuredContent" in out:
        out["content"] = []
    return out


def _value_at_path(arguments: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = arguments
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return _MISSING
        cur = cur[key]
    return cur


def _param_value_to_header_string(value: Any, json_type: str) -> str | None:
    """Convert a primitive tool argument to an MCP header string."""
    if json_type == "string":
        return value if isinstance(value, str) else None
    if json_type == "boolean":
        if isinstance(value, bool):
            return "true" if value else "false"
        return value if value in ("true", "false") else None
    number: int | None = None
    if json_type == "integer" and not isinstance(value, bool):
        if isinstance(value, int):
            number = value
        elif isinstance(value, str) and _INT_STRING.fullmatch(value):
            number = int(value)
        elif isinstance(value, float) and value.is_integer():
            number = int(value)
    if (
        number is None
        or number < _IEEE754_SAFE_INT_MIN
        or number > _IEEE754_SAFE_INT_MAX
    ):
        return None
    return str(number)


def _collect_tool_header_bindings(  # noqa: C901
    input_schema: Any,
) -> tuple[list[_HeaderBinding] | None, str | None]:
    """Collect statically reachable ``x-mcp-header`` bindings.

    Returns ``(bindings, None)`` on success, or ``(None, reason)`` to reject
    the whole tool.
    """
    if input_schema is None:
        return [], None
    if not isinstance(input_schema, dict):
        return None, "inputSchema must be an object"

    bindings: list[_HeaderBinding] = []
    seen_headers: dict[str, str] = {}

    def walk(  # pylint: disable=too-many-branches,too-many-return-statements
        node: Any,
        path: tuple[str, ...],
        *,
        static: bool,
    ) -> str | None:
        if not isinstance(node, dict):
            return None
        if "$ref" in node:
            # $ref targets are not statically reachable.
            static = False
        header = node.get(_X_MCP_HEADER)
        if header is not None:
            if not path:
                return f"{_X_MCP_HEADER} must annotate a property"
            if not static:
                return (
                    f"{_X_MCP_HEADER} at {'.'.join(path)} is not "
                    "statically reachable via properties"
                )
            if not isinstance(header, str) or not header:
                return f"{_X_MCP_HEADER} must be a non-empty string"
            if "\r" in header or "\n" in header:
                return f"{_X_MCP_HEADER} contains CR/LF"
            if not _HTTP_FIELD_NAME.fullmatch(header):
                return f"invalid {_X_MCP_HEADER} field name: {header!r}"
            json_type = node.get("type")
            # Reject non-str types (e.g. ["string","null"]) without crashing.
            if (
                not isinstance(json_type, str)
                or json_type not in _PRIMITIVE_HEADER_TYPES
            ):
                return (
                    f"{_X_MCP_HEADER} requires type string/integer/boolean, "
                    f"got {json_type!r}"
                )
            key = header.casefold()
            if key in seen_headers:
                return (
                    f"duplicate {_X_MCP_HEADER} {header!r} "
                    f"(conflicts with {seen_headers[key]!r})"
                )
            seen_headers[key] = header
            bindings.append((path, header, json_type))

        props = node.get("properties")
        if isinstance(props, dict):
            for name, prop in props.items():
                if not isinstance(name, str):
                    continue
                err = walk(prop, path + (name,), static=static)
                if err is not None:
                    return err

        # Non-static walk covers $defs / additionalProperties / etc.
        for key, nested in node.items():
            if key in _SKIP_GENERIC_WALK_KEYS or nested is None:
                continue
            if isinstance(nested, dict):
                err = walk(nested, path, static=False)
                if err is not None:
                    return err
            elif isinstance(nested, list):
                for item in nested:
                    if not isinstance(item, dict):
                        continue
                    err = walk(item, path, static=False)
                    if err is not None:
                        return err
        return None

    err = walk(input_schema, (), static=True)
    if err is not None:
        return None, err
    return bindings, None


def _build_mcp_param_headers(
    bindings: list[_HeaderBinding] | tuple[_HeaderBinding, ...],
    arguments: dict[str, Any] | None,
) -> dict[str, str]:
    """Build ``Mcp-Param-*`` headers from tool bindings and call arguments."""
    args = arguments or {}
    headers: dict[str, str] = {}
    for path, header_name, json_type in bindings:
        value = _value_at_path(args, path)
        if value is _MISSING or value is None:
            continue
        text = _param_value_to_header_string(value, json_type)
        if text is None:
            raise RuntimeError(
                f"Cannot encode {'.'.join(path)} as {json_type} header",
            )
        headers[
            f"{_MCP_PARAM_HEADER_PREFIX}{header_name}"
        ] = _encode_mcp_header_value(text)
    return headers


def _unwrap_jsonrpc_result(
    *,
    method: str,
    status: int,
    data: Any,
    request: httpx.Request,
    request_id: int | str,
    content: bytes = b"",
    headers: dict[str, str] | None = None,
) -> Any:
    """Unwrap a JSON-RPC response body, raising on HTTP / RPC errors."""
    # Require jsonrpc:"2.0" so platform 404 JSON is not misread as RPC.
    if status >= 400:
        if _is_jsonrpc_envelope(data) and isinstance(data.get("error"), dict):
            # Legacy peers may omit/null id on HTTP 4xx JSON-RPC errors.
            raise _JsonRpcError.from_payload(data["error"], http_status=status)
        resp_kw: dict[str, Any] = {
            "headers": headers or {},
            "request": request,
        }
        if isinstance(data, dict):
            resp_kw["json"] = data
        else:
            resp_kw["content"] = content
        raise httpx.HTTPStatusError(
            f"MCP {method} rejected with HTTP {status}",
            request=request,
            response=httpx.Response(status, **resp_kw),
        )
    if not _is_jsonrpc_envelope(data):
        raise RuntimeError(
            f"MCP {method} returned a non-JSON-RPC payload: {data!r}",
        )
    if not _ids_match(data.get("id"), request_id):
        raise RuntimeError(
            f"MCP {method} JSON-RPC id mismatch: "
            f"expected {request_id!r}, got {data.get('id')!r}",
        )
    if "error" in data:
        raise _JsonRpcError.from_payload(data["error"], http_status=status)
    if "result" not in data:
        raise RuntimeError(f"MCP {method} response missing result")
    return data["result"]


def _not_connected(name: str) -> RuntimeError:
    return RuntimeError(
        f"MCP client '{name}' is not connected. Call connect() first.",
    )


def _already_connected(name: str) -> RuntimeError:
    return RuntimeError(
        f"MCP client '{name}' is already connected. "
        "Call close() before connecting again.",
    )


def _discover_rpc_error(exc: _JsonRpcError) -> RuntimeError:
    return RuntimeError(
        f"MCP JSON-RPC error for 'server/discover': "
        f"code={exc.code} message={exc}",
    )


class _HttpClientBase:
    """Shared constructor fields for Streamable-HTTP clients."""

    def __init__(
        self,
        name: Any,
        transport: Any = "streamable_http",
        url: Any = "",
        headers: dict[str, str] | None = None,
        timeout: float = 30,
        sse_read_timeout: float = 60 * 5,
        **client_kwargs: Any,
    ) -> None:
        for label, value in (
            ("name", name),
            ("transport", transport),
            ("url", url),
        ):
            if not isinstance(value, str):
                raise TypeError(
                    f"{label} must be str, got {type(value).__name__}",
                )
        if transport != "streamable_http":
            raise ValueError(
                f"{type(self).__name__} only supports "
                f"transport='streamable_http', got {transport!r}",
            )
        self.name = name
        self.transport = transport
        self.url = url
        self.headers = headers
        self.timeout = timeout
        self.sse_read_timeout = sse_read_timeout
        self.client_kwargs = dict(client_kwargs)
        self.is_stateful = False
        self.is_connected = False


class _AsyncClient(httpx.AsyncClient):
    """Refuse cross-origin redirects; credentials use arbitrary headers."""

    def _redirect_headers(self, request, url, method):
        if _same_origin(request.url, url) or _is_https_upgrade(
            request.url,
            url,
        ):
            return super()._redirect_headers(request, url, method)
        raise RuntimeError(
            f"MCP client refuses cross-origin redirect: "
            f"{request.url} -> {url}",
        )


class HttpStatelessClient(_HttpClientBase):
    """Stateless Streamable-HTTP client for MCP 2026-07-28."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        http_transport = self.client_kwargs.pop("http_transport", None)
        if http_transport is not None:
            self.client_kwargs["transport"] = http_transport
        self._follow_redirects: bool = self.client_kwargs.pop(
            "follow_redirects",
            True,
        )
        self._http: httpx.AsyncClient | None = None
        self._rpc_ids = itertools.count(1)
        self._tool_param_headers: dict[str, list[_HeaderBinding]] = {}
        self._tools_listed = False

    async def connect(self, timeout: float = 30.0) -> None:
        """Connect and negotiate the modern protocol version."""
        if self.is_connected or self._http is not None:
            raise _already_connected(self.name)
        t = _timeout_seconds(self.timeout)
        r = _timeout_seconds(self.sse_read_timeout)
        # Drop leftover session ids without mutating caller-owned headers.
        headers = _headers_without_session_id(self.headers)
        self._http = _AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(connect=t, read=r, write=t, pool=t),
            follow_redirects=self._follow_redirects,
            **self.client_kwargs,
        )
        try:
            await asyncio.wait_for(self._negotiate(), timeout=timeout)
        except BaseException:
            await self.close(ignore_errors=True)
            raise
        self.is_connected = True
        logger.info(
            f"MCP stateless client connected: {self.name} "
            f"(protocol={_MODERN_PROTOCOL_VERSION})",
        )

    async def close(self, ignore_errors: bool = True) -> None:
        """Close the underlying HTTP client and clear tool header cache."""
        self.is_connected = False
        self._tool_param_headers = {}
        self._tools_listed = False
        http = self._http
        if http is None:
            return
        try:
            await http.aclose()
        except Exception as exc:
            if not ignore_errors:
                raise
            logger.warning(
                f"Error closing MCP stateless client '{self.name}': {exc}",
            )
        except BaseException:
            self._http = None
            raise
        self._http = None

    def _reject_tool(self, label: Any, reason: Any) -> None:
        logger.warning(
            f"Rejecting MCP tool {label!r} from '{self.name}': {reason}",
        )

    # pylint: disable=too-many-branches
    async def list_tools(self):  # noqa: C901
        """Return tools, rejecting invalid ``x-mcp-header`` definitions."""
        self._validate_connection()
        accepted: list[mcp_types.Tool] = []
        header_index: dict[str, list[_HeaderBinding]] = {}
        cursor: str | None = None
        seen_cursors: set[str] = set()
        page_count = 0
        while True:
            if page_count >= _LIST_TOOLS_MAX_PAGES:
                raise RuntimeError(
                    f"tools/list pagination exceeded "
                    f"{_LIST_TOOLS_MAX_PAGES} pages",
                )
            page_count += 1
            params: dict[str, Any] = {}
            if cursor is not None:
                if cursor in seen_cursors:
                    raise RuntimeError(
                        f"Repeated tools/list cursor: {cursor!r}",
                    )
                seen_cursors.add(cursor)
                params["cursor"] = cursor
            result = await self._rpc("tools/list", params)
            if not isinstance(result, dict):
                raise RuntimeError(
                    f"Malformed tools/list result: {result!r}",
                )
            raw_tools = result.get("tools")
            if not isinstance(raw_tools, list):
                raise RuntimeError(
                    f"Malformed tools/list tools field: {raw_tools!r}",
                )
            for raw in raw_tools:
                if not isinstance(raw, dict):
                    self._reject_tool(raw, "non-object tool entry")
                    continue
                tool_name = str(raw.get("name") or "")
                schema = raw.get("inputSchema")
                if schema is None:
                    schema = raw.get("input_schema")
                bindings, err = _collect_tool_header_bindings(schema)
                if err is not None:
                    self._reject_tool(tool_name or raw, err)
                    continue
                try:
                    tool = mcp_types.Tool.model_validate(raw)
                except Exception as exc:
                    self._reject_tool(tool_name or raw, exc)
                    continue
                accepted.append(tool)
                header_index[tool.name] = bindings
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                next_cursor = result.get("next_cursor")
            if not next_cursor:
                break
            if not isinstance(next_cursor, str):
                raise RuntimeError(
                    f"Malformed tools/list nextCursor: {next_cursor!r}",
                )
            cursor = next_cursor
        # Replace header index only after full pagination succeeds.
        self._tool_param_headers = header_index
        self._tools_listed = True
        return accepted

    async def call_tool(self, name: str, arguments: dict | None = None):
        """Call a tool, mirroring ``x-mcp-header`` params into HTTP headers."""
        self._validate_connection()
        if not self._tools_listed:
            await self.list_tools()

        async def _call() -> Any:
            return await self._rpc(
                "tools/call",
                {"name": name, "arguments": arguments or {}},
                mcp_name=name,
                extra_headers=_build_mcp_param_headers(
                    self._tool_param_headers.get(name, []),
                    arguments,
                )
                or None,
            )

        try:
            result = await _call()
        except _JsonRpcError as exc:
            if exc.code != _JSONRPC_HEADER_MISMATCH:
                raise
            await self.list_tools()
            result = await _call()
        normalized = _normalize_call_tool_result(result)
        if isinstance(normalized, dict):
            result_type = normalized.get("resultType")
            if result_type == "input_required":
                raise RuntimeError(
                    "MCP tool requires additional input (MRTR), "
                    "which is not supported",
                )
            if result_type is not None and result_type != "complete":
                raise RuntimeError(
                    f"MCP tool returned unsupported resultType="
                    f"{result_type!r}",
                )
        return _ModernCallToolResult.model_validate(normalized)

    async def _negotiate(self) -> None:
        """Probe ``server/discover``; confirm the peer supports 2026-07-28."""
        try:
            result = await self._rpc("server/discover", {})
        except _JsonRpcError as exc:
            if exc.code == _JSONRPC_UNSUPPORTED_PROTOCOL_VERSION:
                supported = _supported_versions_from_payload(exc.data)
                # Handshake-only list: fall back so dual-era peers that
                # only advertise 2025-11-25 still connect via initialize.
                if _is_legacy_protocol_evidence(
                    supported_versions=supported,
                ):
                    raise _LegacyProtocolError(
                        f"legacy-only -32022 versions: {supported}",
                    ) from exc
                raise RuntimeError(
                    f"incompatible modern MCP: {supported or []}",
                ) from exc
            if exc.code == _JSONRPC_METHOD_NOT_FOUND:
                # HTTP 404 + -32601 is the modern unknown-method shape.
                if exc.http_status == 404:
                    raise _discover_rpc_error(exc) from exc
                raise _LegacyProtocolError(str(exc)) from exc
            if _is_legacy_protocol_evidence(
                status_code=exc.http_status,
                error_code=exc.code,
            ):
                raise _LegacyProtocolError(str(exc)) from exc
            raise _discover_rpc_error(exc) from exc
        except httpx.HTTPStatusError as exc:
            # Bare 400/404/405 ⇒ one legacy fallback.
            if _is_legacy_protocol_evidence(
                status_code=exc.response.status_code,
            ):
                raise _LegacyProtocolError(str(exc)) from exc
            raise

        supported = _supported_versions_from_payload(result)
        if supported is None:
            raise RuntimeError(f"Malformed MCP discover result: {result!r}")
        # Handshake-only discover is dual-era fallback, not a modern hard-fail.
        if _is_legacy_protocol_evidence(supported_versions=supported):
            raise _LegacyProtocolError(
                f"legacy-only discover versions: {supported}",
            )
        if _MODERN_PROTOCOL_VERSION not in supported:
            raise RuntimeError(
                "No mutually supported modern protocol version "
                f"(server: {supported})",
            )

    async def _rpc(  # noqa: C901
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        mcp_name: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        """POST one JSON-RPC request and unwrap the response."""
        if self._http is None:
            raise _not_connected(self.name)
        body_params = dict(params or {})
        meta = dict(body_params.get("_meta") or {})
        meta[_PROTOCOL_VERSION_META_KEY] = _MODERN_PROTOCOL_VERSION
        # Empty capabilities: do not advertise MRTR/elicitation.
        meta.setdefault(_CLIENT_CAPABILITIES_META_KEY, {})
        if _CLIENT_INFO_META_KEY not in meta:
            meta[_CLIENT_INFO_META_KEY] = {
                "name": "qwenpaw",
                "version": _QWENPAW_VERSION,
            }
        body_params["_meta"] = meta
        request_id = next(self._rpc_ids)
        headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            _MCP_PROTOCOL_VERSION_HEADER: _MODERN_PROTOCOL_VERSION,
            _MCP_METHOD_HEADER: method,
        }
        if mcp_name is not None:
            headers[_MCP_NAME_HEADER] = _encode_mcp_header_value(mcp_name)
        if extra_headers:
            headers.update(extra_headers)
        async with self._http.stream(
            "POST",
            self.url,
            json={
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": body_params,
            },
            headers=headers,
        ) as response:
            status = response.status_code
            ctype = (response.headers.get("content-type") or "").lower()
            response_headers = dict(response.headers)
            raw_body = b""
            if status == 401:
                await response.aread()
                raise RuntimeError(
                    f"MCP client '{self.name}' requires OAuth "
                    "authorization (HTTP 401). Please authorize "
                    "via the UI.",
                )
            if "text/event-stream" in ctype:
                data = await self._read_sse_rpc_response(
                    response,
                    method=method,
                    request_id=request_id,
                    status=status,
                )
                if data is None and status < 400:
                    raise RuntimeError(
                        f"Empty SSE response for MCP method '{method}'",
                    )
            else:
                raw_body = await response.aread()
                text = raw_body.decode("utf-8", errors="replace")
                try:
                    data = json.loads(text) if text.strip() else None
                except json.JSONDecodeError:
                    data = None
            request = response.request
        return _unwrap_jsonrpc_result(
            method=method,
            status=status,
            data=data,
            request=request,
            request_id=request_id,
            content=raw_body,
            headers=response_headers,
        )

    async def _read_sse_rpc_response(
        self,
        response: httpx.Response,
        *,
        method: str,
        request_id: int | str,
        status: int,
    ) -> dict[str, Any] | None:
        """Return the first SSE JSON-RPC response matching *request_id*."""
        data_lines: list[str] = []

        def flush() -> dict[str, Any] | None:
            nonlocal data_lines
            raw = "\n".join(data_lines).strip()
            data_lines = []
            if not raw:
                return None
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug(
                    f"Ignoring non-JSON SSE data for '{method}': {raw[:200]}",
                )
                return None
            if not isinstance(event, dict):
                return None
            if _ids_match(event.get("id"), request_id):
                has_body = "result" in event or "error" in event
                return event if has_body else None
            # 4xx JSON-RPC errors may omit/null id (same as JSON unwrap).
            if status >= 400 and "error" in event:
                return event
            return None

        async for line in response.aiter_lines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
            elif line.strip() == "":
                matched = flush()
                if matched is not None:
                    return matched
        return flush()

    def _validate_connection(self) -> None:
        if not self.is_connected or self._http is None:
            raise _not_connected(self.name)


class HttpAutoClient(_HttpClientBase):
    """Dual-era Streamable-HTTP client: modern first, one legacy fallback."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._impl: Any = None
        self._lifecycle_lock = asyncio.Lock()

    def _require_impl(self) -> Any:
        if not self.is_connected or self._impl is None:
            raise _not_connected(self.name)
        return self._impl

    async def connect(self, timeout: float = 30.0) -> None:
        """Connect via modern client, falling back once to legacy if needed."""
        async with self._lifecycle_lock:
            await self._connect_locked(timeout)

    async def _connect_locked(self, timeout: float) -> None:
        """Run connect while holding `_lifecycle_lock`."""
        if self.is_connected or self._impl is not None:
            raise _already_connected(self.name)
        kw = dict(self.client_kwargs)
        http_transport = kw.pop("http_transport", None)
        follow_redirects = kw.pop("follow_redirects", True)
        shared = {
            "name": self.name,
            "transport": "streamable_http",
            "url": self.url,
            "headers": _headers_without_session_id(self.headers) or None,
            "timeout": self.timeout,
            "sse_read_timeout": self.sse_read_timeout,
            **kw,
        }
        deadline = time.monotonic() + float(timeout)
        if http_transport is not None:
            shared["http_transport"] = http_transport
        modern = HttpStatelessClient(
            follow_redirects=follow_redirects,
            **shared,
        )
        try:
            await modern.connect(timeout=timeout)
        except _LegacyProtocolError as exc:
            logger.info(
                f"MCP client '{self.name}' falling back to legacy: {exc}",
            )
        else:
            self._impl = modern
            self.is_stateful = False
            self.is_connected = True
            return
        finally:
            if self._impl is not modern:
                await modern.close(ignore_errors=True)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"MCP client '{self.name}' timed out during modern negotiate "
                "before legacy fallback",
            )
        shared.pop("http_transport", None)
        from .mcp_stateful_client import HttpStatefulClient

        legacy = HttpStatefulClient(**shared)
        try:
            await legacy.connect(timeout=remaining)
        except BaseException:
            await legacy.close(ignore_errors=True)
            raise
        self._impl = legacy
        self.is_stateful = True
        self.is_connected = True

    async def close(self, ignore_errors: bool = True) -> None:
        """Close the active modern or legacy implementation."""
        async with self._lifecycle_lock:
            self.is_connected = False
            self.is_stateful = False
            impl = self._impl
            if impl is None:
                return
            try:
                await impl.close(ignore_errors=ignore_errors)
            except Exception:
                if not ignore_errors:
                    raise
            self._impl = None

    async def list_tools(self):
        async with self._lifecycle_lock:
            impl = self._require_impl()
        return await impl.list_tools()

    async def call_tool(self, name: str, arguments: dict | None = None):
        async with self._lifecycle_lock:
            impl = self._require_impl()
        return await impl.call_tool(name, arguments)
