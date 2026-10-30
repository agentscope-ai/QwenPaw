# -*- coding: utf-8 -*-
"""Host-approved HTTP/WS forwarding over existing channel runtime custody."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
import secrets
from urllib.parse import parse_qsl, urlsplit

import aiohttp
from multidict import CIMultiDict
from starlette.responses import Response
from starlette.websockets import WebSocketState
from yarl import URL

from ...channel_protocol.models import HostForwardingBinding

DEFAULT_ROUTES = {
    ("voice", "voice"): (
        ("POST", "/voice/incoming"),
        ("WEBSOCKET", "/voice/ws"),
        ("POST", "/voice/status-callback"),
    ),
}
_INTERNAL = {b"x-qwenpaw-ingress-token", b"x-qwenpaw-ingress-original-url"}
_HOP = {
    b"connection",
    b"keep-alive",
    b"proxy-authenticate",
    b"proxy-authorization",
    b"proxy-connection",
    b"te",
    b"trailer",
    b"transfer-encoding",
    b"upgrade",
}
_WS_HEADERS = {
    b"sec-websocket-key",
    b"sec-websocket-version",
    b"sec-websocket-accept",
    b"sec-websocket-protocol",
    b"sec-websocket-extensions",
}


@dataclass(frozen=True)
class IngressLimits:
    owner_concurrency: int = 64
    ws_frame_bytes: int = 1024 * 1024
    http_body_bytes: int = 1024 * 1024
    http_chunk_bytes: int = 64 * 1024
    connect_timeout: float = 5.0
    http_timeout: float = 30.0
    shutdown_timeout: float = 2.0

    def __post_init__(self):
        for name, value in vars(self).items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"invalid ingress limit: {name}")
        for name in (
            "owner_concurrency",
            "ws_frame_bytes",
            "http_body_bytes",
            "http_chunk_bytes",
        ):
            if not isinstance(getattr(self, name), int):
                raise ValueError(f"invalid ingress limit: {name}")


class _Unavailable(Exception):
    def __init__(self, status=503):
        self.status = status


@dataclass(eq=False)
class _Binding:
    service: object
    lease: object
    reference: object
    routes: tuple
    wire: HostForwardingBinding = field(repr=False)
    fenced: bool = False
    forwards: set = field(default_factory=set, repr=False)


@dataclass(eq=False)
class _Forward:
    binding: _Binding
    reference: object
    task: asyncio.Task
    upstream: object = None
    websocket: object = None
    pumps: tuple = ()
    closers: tuple = ()
    cleanup: asyncio.Task | None = None
    draining: asyncio.Task | None = None
    close_code: int = 1013
    close_reason: str = "Channel ingress closed"


def _headers(raw, *, websocket=False):
    nominated = {
        token.strip().lower()
        for key, value in raw
        if key.lower() == b"connection"
        for token in value.split(b",")
    }
    excluded = (
        _HOP | _INTERNAL | nominated | (_WS_HEADERS if websocket else set())
    )
    return [(key, value) for key, value in raw if key.lower() not in excluded]


class _HTTPResponse(Response):
    def __init__(self, service, request):
        super().__init__()
        self.service, self.request = service, request

    async def __call__(self, scope, receive, send):
        await self.service._http(self.request, send)


def route_is_unowned(registry, method, path, *, service=None):
    """Read host custody without selecting, forwarding or starting a route."""
    if service is None and registry is not None:
        service = getattr(registry, "channel_ingress_service", None)
    routes = DEFAULT_ROUTES
    if service is not None:
        if service._closed:
            return False
        registry, routes = service.registry, service.routes
    route = (method, path)
    channels = {
        channel for (_, channel), entries in routes.items() if route in entries
    }
    if not channels:
        return False
    if service is not None and any(
        route in binding.routes
        for binding in (*service._bindings.values(), *service._retired)
    ):
        return False
    return registry is None or not any(
        lease.key.kind == "channel" and lease.key.name in channels
        for lease in registry.runtime_owners.leases()
    )


class ChannelIngressService:
    """Index existing RuntimeOwners; never start or own a channel worker.

    ``routes`` is host code, keyed by exact (plugin_id, channel_key), with
    (HTTP method or WEBSOCKET, absolute path) pairs. No child adds routes.
    ``trusted_proxy`` checks the actual direct peer; default trusts none.
    """

    def __init__(
        self,
        registry,
        *,
        host_port,
        routes=None,
        trusted_proxy=None,
        limits=None,
    ):
        if host_port is not None and (
            type(host_port) is not int or not 1 <= host_port <= 65535
        ):
            raise ValueError("HOST_INGRESS_PORT_INVALID")
        self.registry = registry
        self.host_port = host_port
        self.limits = limits or IngressLimits()
        self.trusted_proxy = trusted_proxy or (lambda request: False)
        self.routes = {}
        for owner, entries in (
            DEFAULT_ROUTES if routes is None else routes
        ).items():
            if (
                not isinstance(owner, tuple)
                or len(owner) != 2
                or not all(isinstance(item, str) and item for item in owner)
            ):
                raise ValueError("HOST_INGRESS_RULE_INVALID")
            values = tuple(entries)
            for method, path in values:
                if method not in {
                    "GET",
                    "HEAD",
                    "POST",
                    "PUT",
                    "PATCH",
                    "DELETE",
                    "OPTIONS",
                    "WEBSOCKET",
                }:
                    raise ValueError("HOST_INGRESS_RULE_INVALID")
                HostForwardingBinding.from_mapping(
                    {
                        "route_query_key": "_qp_endpoint",
                        "route_selector": "validation",
                        "host_port": 1,
                        "paths": [path],
                        "bridge_token": "validation",
                    },
                )
            if not values or len(set(values)) != len(values):
                raise ValueError("HOST_INGRESS_RULE_INVALID")
            self.routes[owner] = values
        self._bindings = {}
        self._retired = set()
        self._client = None
        self._watcher = None
        self._closed = False
        self._stopped = False
        previous = getattr(registry, "channel_ingress_service", None)
        if previous is not None and not previous._stopped:
            raise RuntimeError("HOST_INGRESS_ALREADY_ATTACHED")
        registry.channel_ingress_service = self

    def attach(self, proxy):
        """Attach after Manager attaches its exact runtime lease/resource."""
        if (proxy.endpoint_service.plugin_id, proxy.channel) in self.routes:
            proxy.endpoint_service.forwarder = self

    def _owner(self, service, reference):
        endpoint = reference.endpoint
        row = self.registry.get_channel_registration(endpoint.channel_key)
        if (
            row is None
            or not row.global_enabled
            or row.plugin_id != reference.plugin_id
        ):
            return None
        description = row.description_record
        if (
            description is None
            or description.source_revision != reference.source_revision
        ):
            return None
        for lease in self.registry.runtime_owners.leases(reference.plugin_id):
            if (
                lease.key.kind,
                lease.key.name,
                lease.key.scope_id,
                lease.instance_id,
                lease.generation,
            ) != (
                "channel",
                endpoint.channel_key,
                reference.workspace_id,
                endpoint.instance_id,
                endpoint.generation,
            ) or lease.code_root != description.code_root.resolve():
                continue
            proxy = self.registry.runtime_owners.resource(lease)
            if (
                proxy is not None
                and getattr(proxy, "endpoint_service", None) is service
                and getattr(proxy, "_registration", None) is row
                and proxy.enabled
                and service.authority.endpoint_snapshot(
                    endpoint.generation,
                    allow_paused=True,
                )
                is not None
            ):
                return lease
        return None

    def endpoint_changed(self, service, reference):
        """Synchronous registration callback; starting is allowed, routing isn't."""
        self._sweep()
        routes = self.routes.get(
            (reference.plugin_id, reference.endpoint.channel_key),
        )
        if routes is None:
            return None
        lease = self._owner(service, reference)
        if self._closed or lease is None:
            raise RuntimeError("HOST_INGRESS_OWNER_UNAVAILABLE")
        if self.host_port is None:
            raise RuntimeError("HOST_INGRESS_PORT_UNAVAILABLE")
        if reference.loopback_host is None:
            raise RuntimeError("HOST_INGRESS_LOOPBACK_REQUIRED")
        self._canonical_origin(reference)
        prefix = reference.endpoint.path.rstrip("/")
        if any(
            path != prefix and not path.startswith(prefix + "/")
            for _, path in routes
        ):
            raise RuntimeError("HOST_INGRESS_PATH_UNAUTHORIZED")
        binding = self._bindings.get(service)
        if (
            binding is not None
            and binding.lease == lease
            and not binding.fenced
        ):
            self._cancel_revision(binding, binding.reference)
            binding.reference = reference
        else:
            if binding is not None:
                self._fence(binding)
            paths = tuple(dict.fromkeys(path for _, path in routes))
            binding = _Binding(
                service,
                lease,
                reference,
                routes,
                HostForwardingBinding(
                    "_qp_endpoint",
                    secrets.token_urlsafe(24),
                    self.host_port,
                    paths,
                    secrets.token_urlsafe(32),
                ),
            )
            self._bindings[service] = binding
        if self._watcher is None:
            self._watcher = asyncio.create_task(
                self._watch(),
                name="channel-ingress-custody",
            )
        return binding.wire

    def pause_endpoint(self, service):
        binding = self._bindings.get(service)
        if binding is not None:
            self._cancel_revision(binding, binding.reference)

    def fence_endpoint(self, service):
        binding = self._bindings.get(service)
        if binding is not None:
            self._fence(binding)

    @staticmethod
    def _cancel_revision(binding, reference):
        for forward in tuple(binding.forwards):
            if (
                forward.reference is reference
                and not forward.task.done()
                and not forward.task.cancelling()
            ):
                forward.task.cancel()

    def _fence(self, binding):
        binding.fenced = True
        if self._bindings.get(binding.service) is binding:
            del self._bindings[binding.service]
        self._retired.add(binding)
        for forward in tuple(binding.forwards):
            if not forward.task.done() and not forward.task.cancelling():
                forward.task.cancel()

    def _sweep(self):
        for binding in tuple(self._bindings.values()):
            if (
                self._owner(binding.service, binding.reference)
                != binding.lease
            ):
                self._fence(binding)
        self._retired = {
            binding for binding in self._retired if binding.forwards
        }

    async def _watch(self):
        while not self._closed:
            self._sweep()
            await asyncio.sleep(0.05)

    def _current(self, binding, reference):
        return (
            not self._closed
            and not binding.fenced
            and binding.reference is reference
            and self._bindings.get(binding.service) is binding
            and self._owner(binding.service, reference) == binding.lease
            and binding.service.is_current(reference, forwarding=True)
        )

    def _select(self, request, method):
        self._sweep()
        if self._closed:
            raise _Unavailable()
        try:
            selectors = [
                value
                for key, value in parse_qsl(
                    request.scope.get("query_string", b"").decode("ascii"),
                    keep_blank_values=True,
                    max_num_fields=4096,
                )
                if key == "_qp_endpoint"
            ]
        except (ValueError, UnicodeError):
            raise _Unavailable(400) from None
        if len(selectors) > 1 or selectors == [""]:
            raise _Unavailable(400)
        candidates = [
            binding
            for binding in self._bindings.values()
            if (method, request.scope["path"]) in binding.routes
            and (not selectors or binding.wire.route_selector == selectors[0])
            and self._current(binding, binding.reference)
        ]
        if len(candidates) != 1:
            raise _Unavailable(409 if len(candidates) > 1 else 503)
        binding = candidates[0]
        owned = sum(
            len(item.forwards)
            for item in (*self._bindings.values(), *self._retired)
            if item.lease.key == binding.lease.key
        )
        if owned >= self.limits.owner_concurrency:
            raise _Unavailable()
        forward = _Forward(binding, binding.reference, asyncio.current_task())
        binding.forwards.add(forward)
        return forward

    @staticmethod
    def _raw_target(request):
        path = request.scope.get("raw_path") or request.scope["path"].encode(
            "utf-8",
        )
        query = request.scope.get("query_string", b"")
        return path.decode("ascii") + (
            ("?" + query.decode("ascii")) if query else ""
        )

    @staticmethod
    def _canonical_origin(reference):
        """An approved owner's public origin authenticates no upstream URL."""
        origin = reference.endpoint.public_base_url
        if origin is None:
            return None
        try:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or "?" in origin
                or "#" in origin
                or any(ord(c) < 33 or ord(c) > 126 for c in origin)
                or any(c in parsed.netloc for c in "\\%?#")
                or parsed.port is not None
                and not 1 <= parsed.port <= 65535
            ):
                raise ValueError()
        except ValueError:
            raise RuntimeError("HOST_INGRESS_PUBLIC_ORIGIN_INVALID") from None
        return origin.rstrip("/")

    def _original_url(self, request, reference):
        hosts = request.headers.getlist("host")
        if len(hosts) > 1:
            raise _Unavailable(400)
        server = request.scope.get("server")
        host = (
            hosts[0]
            if hosts
            else (f"{server[0]}:{server[1]}" if server else "")
        )
        scheme = request.scope.get("scheme", "http")
        if self.trusted_proxy(request):
            for header, current in (
                ("x-forwarded-host", host),
                ("x-forwarded-proto", scheme),
            ):
                values = request.headers.getlist(header)
                if len(values) > 1 or values and "," in values[0]:
                    raise _Unavailable(400)
                value = values[0] if values else current
                if header.endswith("host"):
                    host = value
                else:
                    scheme = value
        if (
            scheme not in {"http", "https", "ws", "wss"}
            or not host
            or any(c.isspace() or ord(c) < 33 for c in host)
        ):
            raise _Unavailable(400)
        try:
            parsed = urlsplit(scheme + "://" + host)
            if (
                not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError()
            parsed.port
        except ValueError:
            raise _Unavailable(400) from None
        canonical = self._canonical_origin(reference)
        if canonical is not None:
            public = urlsplit(canonical)
            actual = urlsplit(public.scheme + "://" + host)
            default_port = 443 if public.scheme == "https" else 80
            if (actual.hostname, actual.port or default_port) != (
                public.hostname,
                public.port or default_port,
            ):
                raise _Unavailable(403)
            # Only the current authorized endpoint supplies this origin;
            # external forwarded headers never create or override it.
            return canonical + self._raw_target(request)
        return scheme + "://" + host + self._raw_target(request)

    def _request_headers(self, request, forward, *, websocket=False):
        headers = CIMultiDict(
            (key.decode("latin1"), value.decode("latin1"))
            for key, value in _headers(
                request.scope["headers"],
                websocket=websocket,
            )
        )
        headers["X-Qwenpaw-Ingress-Token"] = forward.binding.wire.bridge_token
        headers["X-Qwenpaw-Ingress-Original-URL"] = self._original_url(
            request,
            forward.reference,
        )
        return headers

    def _url(self, request, forward, *, websocket=False):
        reference = forward.reference
        if not self._current(forward.binding, reference):
            raise _Unavailable()
        host = reference.loopback_host
        if ":" in host:
            host = "[" + host + "]"
        return URL(
            ("ws" if websocket else "http")
            + "://"
            + host
            + ":"
            + str(reference.endpoint.port)
            + self._raw_target(request),
            encoded=True,
        )

    def _session(self):
        if self._client is None:
            self._client = aiohttp.ClientSession(
                trust_env=False,
                auto_decompress=False,
                cookie_jar=aiohttp.DummyCookieJar(),
                timeout=aiohttp.ClientTimeout(
                    total=None,
                    connect=self.limits.connect_timeout,
                ),
                skip_auto_headers={
                    "User-Agent",
                    "Accept",
                    "Accept-Encoding",
                    "Content-Type",
                },
                connector=aiohttp.TCPConnector(force_close=True),
            )
            # aiohttp retries stale pooled connections on idempotent methods.
            # A WS GET may consume a single-use platform token, so disable it.
            self._client._retry_connection = False
            original = self._client._request

            async def no_redirect(method, url, **kwargs):
                # ws_connect doesn't expose allow_redirects on supported aiohttp.
                kwargs["allow_redirects"] = False
                return await original(method, url, **kwargs)

            self._client._request = no_redirect
        return self._client

    async def forward_http(self, request):
        return _HTTPResponse(self, request)

    async def _http(self, request, send):
        forward, started, overflow = None, False, False
        try:
            forward = self._select(request, request.method)
            if forward.reference.endpoint.protocol not in {"http", "http+ws"}:
                raise _Unavailable()
            length = request.headers.get("content-length")
            if length is not None:
                try:
                    if int(length) < 0:
                        raise ValueError()
                    if int(length) > self.limits.http_body_bytes:
                        raise _Unavailable(413)
                except ValueError:
                    raise _Unavailable(400) from None

            async def body():
                nonlocal overflow
                size = 0
                async for chunk in request.stream():
                    if not self._current(forward.binding, forward.reference):
                        raise _Unavailable()
                    size += len(chunk)
                    if size > self.limits.http_body_bytes:
                        overflow = True
                        raise _Unavailable(413)
                    for offset in range(
                        0,
                        len(chunk),
                        self.limits.http_chunk_bytes,
                    ):
                        yield chunk[
                            offset : offset + self.limits.http_chunk_bytes
                        ]

            async with asyncio.timeout(self.limits.http_timeout):
                response = await self._session().request(
                    request.method,
                    self._url(request, forward),
                    data=body(),
                    headers=self._request_headers(request, forward),
                    timeout=aiohttp.ClientTimeout(
                        total=self.limits.http_timeout,
                        connect=self.limits.connect_timeout,
                    ),
                )
                forward.upstream = response
                if not self._current(forward.binding, forward.reference):
                    raise _Unavailable()
                await send(
                    {
                        "type": "http.response.start",
                        "status": response.status,
                        "headers": _headers(response.raw_headers),
                    },
                )
                started = True
                async for chunk in response.content.iter_chunked(
                    self.limits.http_chunk_bytes,
                ):
                    if not self._current(forward.binding, forward.reference):
                        raise _Unavailable()
                    await send(
                        {
                            "type": "http.response.body",
                            "body": chunk,
                            "more_body": True,
                        },
                    )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b"",
                        "more_body": False,
                    },
                )
        except (
            _Unavailable,
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ) as error:
            if started:
                raise
            status = (
                413
                if overflow
                else (
                    error.status
                    if isinstance(error, _Unavailable)
                    else (
                        504 if isinstance(error, asyncio.TimeoutError) else 502
                    )
                )
            )
            await Response(status_code=status)(
                request.scope,
                request.receive,
                send,
            )
        finally:
            if forward is not None:
                await self._finish_forward(forward)

    async def forward_websocket(self, websocket):
        forward = None
        try:
            forward = self._select(websocket, "WEBSOCKET")
            if forward.reference.endpoint.protocol not in {"ws", "http+ws"}:
                raise _Unavailable()
            async with asyncio.timeout(self.limits.connect_timeout):
                upstream = await self._session().ws_connect(
                    self._url(websocket, forward, websocket=True),
                    headers=self._request_headers(
                        websocket,
                        forward,
                        websocket=True,
                    ),
                    protocols=websocket.scope.get("subprotocols", ()),
                    # aiohttp rejects projected_size >= max_msg_size. This
                    # exclusive parser bound implements our inclusive limit.
                    max_msg_size=self.limits.ws_frame_bytes + 1,
                    autoclose=False,
                    timeout=self.limits.shutdown_timeout,
                    receive_timeout=None,
                )
            forward.upstream = upstream
            if not self._current(forward.binding, forward.reference):
                raise _Unavailable()
            forward.websocket = websocket
            headers = _headers(upstream._response.raw_headers, websocket=True)
            await websocket.accept(
                subprotocol=upstream.protocol,
                headers=headers,
            )
            forward.pumps = (
                asyncio.create_task(self._to_child(forward)),
                asyncio.create_task(self._from_child(forward)),
            )
            done, _ = await asyncio.wait(
                forward.pumps,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                task.result()
        except (
            _Unavailable,
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ) as error:
            if websocket.application_state is WebSocketState.CONNECTING:
                status = (
                    error.status
                    if isinstance(
                        error,
                        (_Unavailable, aiohttp.WSServerHandshakeError),
                    )
                    else 502
                )
                if "websocket.http.response" in websocket.scope.get(
                    "extensions",
                    {},
                ):
                    response = Response(status_code=status)
                    if (
                        isinstance(error, aiohttp.WSServerHandshakeError)
                        and error.headers is not None
                    ):
                        response.raw_headers = _headers(
                            [
                                (key.encode("latin1"), value.encode("latin1"))
                                for key, value in error.headers.items()
                                if key.lower() != "content-length"
                            ],
                            websocket=True,
                        ) + [(b"content-length", b"0")]
                    await websocket.send_denial_response(response)
                else:
                    await websocket.close(
                        code=1013,
                        reason="Channel ingress unavailable",
                    )
        finally:
            if forward is not None:
                await self._finish_forward(forward)

    async def _to_child(self, forward):
        while True:
            message = await forward.websocket.receive()
            if message["type"] == "websocket.disconnect":
                forward.close_code = self._close_code(
                    message.get("code", 1000),
                )
                forward.close_reason = message.get("reason", "")
                return
            if not self._current(forward.binding, forward.reference):
                return
            data = message.get("text")
            binary = data is None
            data = message.get("bytes", b"") if binary else data
            if (
                len(data if binary else data.encode("utf-8"))
                > self.limits.ws_frame_bytes
            ):
                forward.close_code, forward.close_reason = (
                    1013,
                    "Ingress frame limit",
                )
                return
            if binary:
                await forward.upstream.send_bytes(data)
            else:
                await forward.upstream.send_str(data)

    async def _from_child(self, forward):
        while True:
            message = await forward.upstream.receive()
            if not self._current(forward.binding, forward.reference):
                return
            if message.type in {
                aiohttp.WSMsgType.TEXT,
                aiohttp.WSMsgType.BINARY,
            }:
                size = len(
                    message.data.encode("utf-8")
                    if message.type is aiohttp.WSMsgType.TEXT
                    else message.data,
                )
                if size > self.limits.ws_frame_bytes:
                    forward.close_code, forward.close_reason = (
                        1013,
                        "Ingress frame limit",
                    )
                    return
            if message.type is aiohttp.WSMsgType.TEXT:
                await forward.websocket.send_text(message.data)
            elif message.type is aiohttp.WSMsgType.BINARY:
                await forward.websocket.send_bytes(message.data)
            elif message.type in {
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
            }:
                forward.close_code = self._close_code(
                    forward.upstream.close_code or message.data or 1000,
                )
                forward.close_reason = message.extra or ""
                return
            elif message.type is aiohttp.WSMsgType.ERROR:
                forward.close_code = (
                    1013
                    if getattr(message.data, "code", None) == 1009
                    else 1011
                )
                forward.close_reason = "Channel ingress transport failed"
                return

    @staticmethod
    def _close_code(code):
        return (
            code
            if isinstance(code, int)
            and 1000 <= code < 5000
            and code not in {1004, 1005, 1006, 1015}
            else 1011
        )

    async def _cleanup(self, forward):
        for task in forward.pumps:
            if not task.done():
                task.cancel()
        reason = forward.close_reason.encode("utf-8")[:123].decode(
            "utf-8",
            errors="ignore",
        )
        upstream = forward.upstream
        closers = []
        if isinstance(upstream, aiohttp.ClientWebSocketResponse):
            closers.append(
                upstream.close(
                    code=forward.close_code,
                    message=reason.encode("utf-8"),
                ),
            )
        elif upstream is not None:
            upstream.close()
            closers.append(upstream.wait_for_close())
        websocket = forward.websocket
        if (
            websocket is not None
            and websocket.application_state is WebSocketState.CONNECTED
            and websocket.client_state is WebSocketState.CONNECTED
        ):
            closers.append(
                websocket.close(code=forward.close_code, reason=reason),
            )
        forward.closers = tuple(
            asyncio.create_task(close) for close in closers
        )
        results = await asyncio.gather(
            *forward.closers,
            return_exceptions=True,
        )
        if forward.pumps:
            await asyncio.gather(*forward.pumps, return_exceptions=True)
        if any(isinstance(result, BaseException) for result in results):
            raise RuntimeError("CHANNEL_INGRESS_CONNECTION_CLOSE_FAILED")

    async def _finish_forward(self, forward):
        if (
            forward.cleanup is None
            or forward.cleanup.done()
            and (
                forward.cleanup.cancelled()
                or forward.cleanup.exception() is not None
            )
        ):
            forward.cleanup = asyncio.create_task(self._cleanup(forward))
        await asyncio.shield(forward.cleanup)
        forward.binding.forwards.discard(forward)

    async def drain(self, endpoint_service, *, timeout=None):
        """Fence synchronously, then await exact opening/pump/cleanup tasks."""
        if endpoint_service is not None:
            self.fence_endpoint(endpoint_service)
        records = [
            forward
            for binding in (*self._bindings.values(), *self._retired)
            if endpoint_service is None or binding.service is endpoint_service
            for forward in binding.forwards
        ]
        for forward in records:
            if not forward.task.done() and not forward.task.cancelling():
                forward.task.cancel()
        tasks = {
            forward.task for forward in records if not forward.task.done()
        }
        for forward in records:
            if forward.task.done():
                if forward.draining is None or forward.draining.done():
                    forward.draining = asyncio.create_task(
                        self._finish_forward(forward),
                    )
                tasks.add(forward.draining)
        if tasks:
            done, pending = await asyncio.wait(
                tasks,
                timeout=(
                    self.limits.shutdown_timeout
                    if timeout is None
                    else timeout
                ),
            )
            failed = any(
                not task.cancelled() and task.exception() is not None
                for task in done
            )
            if pending or failed:
                return ("CHANNEL_INGRESS_CLEANUP_PENDING",)
        self._sweep()
        return (
            ("CHANNEL_INGRESS_CLEANUP_PENDING",)
            if any(
                binding.forwards
                for binding in self._retired
                if endpoint_service is None
                or binding.service is endpoint_service
            )
            else ()
        )

    async def aclose(self):
        self._closed = True
        for binding in tuple(self._bindings.values()):
            self._fence(binding)
        if self._watcher is not None:
            self._watcher.cancel()
            await asyncio.gather(self._watcher, return_exceptions=True)
            self._watcher = None
        if await self.drain(None):
            raise RuntimeError("CHANNEL_INGRESS_CLEANUP_PENDING")
        if self._client is not None:
            await self._client.close()
            self._client = None
        self._stopped = True
