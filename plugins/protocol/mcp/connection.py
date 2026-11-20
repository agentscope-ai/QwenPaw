# -*- coding: utf-8 -*-
"""One SDK source owns one MCP transport and its discovery cache."""

import asyncio
import time
from collections.abc import Mapping

import httpx

from qwenpaw.plugins.drivers import DriverCapabilitySpec

from .bindings import implicit_auth_headers, resolve_binding
from .credentials import CredentialResolver
from .diagnostics import MCPLogger
from .mcp_stateful_client import (
    HttpStatefulClient,
    StdIOStatefulClient,
    _discard_task_result,
    _restore_cancel,
    _wait_task_uncancelled,
)
from .mcp_streamable_http import HttpAutoClient
from .results import call_result, plain

_CAPABILITY_CACHE_TTL_SECONDS = 10.0


def _build_capabilities(tools, source_id):
    specs = []
    prefix = f"mcp__{source_id}__"
    for tool in tools:
        raw = plain(tool)
        name = str(raw["name"])
        if name.startswith(prefix):
            name = name[len(prefix) :]
        schema = raw.get("inputSchema", raw.get("input_schema")) or {}
        schema = dict(schema) if isinstance(schema, Mapping) else {}
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        schema.setdefault("required", [])
        specs.append(
            DriverCapabilitySpec(
                name=name,
                description=str(raw.get("description") or ""),
                input_schema=schema,
                output_schema=raw.get("outputSchema"),
                metadata={"mcp": raw},
            ),
        )
    return tuple(specs)


class _CredentialAuth(httpx.Auth):
    """Refresh declared credentials on requests without replacing sessions."""

    def __init__(self, context, resolver, binding, headers, logger):
        self.context, self.resolver, self.binding = context, resolver, binding
        self._logger = logger
        self._header_names = set(headers)
        self._snapshot = dict(headers)
        self._confirmed = False
        self._termination = None

    def prepare_termination(self, url, session_id):
        """Lease only this transport's existing session for its final DELETE."""
        if session_id:
            self._termination = (
                httpx.URL(url),
                session_id,
                dict(self._snapshot),
            )

    def finish_termination(self):
        self._termination = None
        self._snapshot.clear()
        self._confirmed = False

    async def async_auth_flow(self, request):
        target = self._termination
        terminating = (
            target is not None
            and request.method == "DELETE"
            and request.url == target[0]
            and request.headers.get("mcp-session-id") == target[1]
        )
        if terminating:
            # Transport identity belongs to the SDK, never to auth bindings.
            reserved = {"mcp-session-id", "mcp-protocol-version"}
            headers = {
                key: value
                for key, value in target[2].items()
                if key.lower() not in reserved
            }
            names = {
                key
                for key in self._header_names
                if key.lower() not in reserved
            }
        else:
            credentials = await self.resolver.resolve(self.context)
            headers = resolve_binding(
                self.binding,
                credentials,
                logger=self._logger,
            )
            headers.update(implicit_auth_headers(credentials, headers))
            names = self._header_names
            if not self._confirmed:
                self._snapshot = dict(headers)
        for key in names:
            request.headers.pop(key, None)
        request.headers.update(headers)
        self._header_names.update(headers)
        response = yield request
        if not terminating and 200 <= response.status_code < 300:
            self._snapshot = dict(headers)
            self._confirmed = True


def validate(source):
    endpoint = source.endpoint
    transport = str(endpoint.get("transport") or "stdio")
    if transport == "stdio":
        command = endpoint.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("MCP stdio endpoint.command must be non-empty")
        args = endpoint.get("args")
        if args is not None and (
            not isinstance(args, (list, tuple))
            or not all(isinstance(item, str) for item in args)
        ):
            raise ValueError("MCP endpoint.args must be a list of strings")
        cwd = endpoint.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise ValueError("MCP endpoint.cwd must be a string")
        return
    if transport not in {"sse", "streamable_http"}:
        raise ValueError(f"Unsupported MCP transport: {transport}")
    url = endpoint.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("MCP HTTP endpoint.url must be non-empty")


class MCPConnection:
    def __init__(self, context, source, credentials=None):
        self.context, self.source = context, source
        self._logger = MCPLogger(context)
        self.credentials = credentials or CredentialResolver()
        self._client = None
        self._capability_cache = None
        self._discovery_lock = asyncio.Lock()
        self._discovery_token = object()

    async def open(self):
        self._discovery_token = object()
        self._capability_cache = None
        endpoint = self.source.endpoint
        transport = str(endpoint.get("transport") or "stdio")
        credentials = await self.credentials.resolve(self.context)
        connect_kwargs = {}
        if transport == "stdio":
            environment = await self.context.subprocess_environment()
            self._client = StdIOStatefulClient(
                name=self.source.source_id,
                command=str(endpoint.get("command") or ""),
                args=list(endpoint.get("args") or ()),
                env={
                    **environment,
                    **resolve_binding(
                        endpoint.get("env") or {},
                        credentials,
                        logger=self._logger,
                    ),
                },
                cwd=endpoint.get("cwd") or None,
                logger=self._logger,
            )
        else:
            headers = resolve_binding(
                endpoint.get("headers") or {},
                credentials,
                logger=self._logger,
            )
            headers.update(implicit_auth_headers(credentials, headers))
            if endpoint.get("http_timeout") is not None:
                connect_kwargs["timeout"] = float(endpoint["http_timeout"])
            client = (
                HttpAutoClient
                if transport == "streamable_http"
                else HttpStatefulClient
            )
            self._client = client(
                name=self.source.source_id,
                transport=transport,
                url=str(endpoint.get("url") or ""),
                headers=headers or None,
                logger=self._logger,
                auth=_CredentialAuth(
                    self.context,
                    self.credentials,
                    endpoint.get("headers") or {},
                    headers,
                    self._logger,
                ),
                **connect_kwargs,
            )
        # The host installs this connection's close owner before entering open.
        await self._client.connect(**connect_kwargs)

    async def discover(self, request):
        request.check_cancelled()
        cached = self._cached_capabilities()
        if cached is not None:
            return cached
        async with self._discovery_lock:
            request.check_cancelled()
            cached = self._cached_capabilities()
            if cached is not None:
                return cached
            client, token = self._client, self._discovery_token
            if token is None or client is None:
                raise RuntimeError("MCP connection is closed or closing")
            tools = await client.list_tools()
            request.check_cancelled()
            worker = asyncio.create_task(
                asyncio.to_thread(
                    _build_capabilities,
                    tools,
                    self.source.source_id,
                ),
            )
            # Retain refresh ownership until the pure worker actually finishes.
            cancelled = await _wait_task_uncancelled(worker)
            _restore_cancel(asyncio.current_task(), cancelled)
            if cancelled:
                _discard_task_result(worker)
                raise asyncio.CancelledError
            specs = worker.result()
            request.check_cancelled()
            if (
                self._client is not client
                or self._discovery_token is not token
            ):
                raise RuntimeError("MCP connection changed during discovery")
            self._capability_cache = (time.monotonic(), specs)
            return specs

    def _cached_capabilities(self):
        if self._capability_cache is not None:
            timestamp, specs = self._capability_cache
            if time.monotonic() - timestamp <= _CAPABILITY_CACHE_TTL_SECONDS:
                return specs
        return None

    async def invoke(self, name, arguments, request):
        request.check_cancelled()
        return call_result(
            await self._client.call_tool(name, plain(arguments)),
        )

    async def close(self):
        self._discovery_token = None
        self._capability_cache = None
        if self._client is not None:
            client = self._client
            close_owned = getattr(client, "close_owned", None)
            if close_owned is not None:
                await close_owned()
            else:
                await client.close(ignore_errors=False)
            self._client = None
