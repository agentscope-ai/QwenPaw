# -*- coding: utf-8 -*-
"""One SDK source owns one MCP transport and its discovery cache."""

import time
from collections.abc import Mapping

import httpx

from qwenpaw.plugins.drivers import DriverCapabilitySpec

from .bindings import implicit_auth_headers, resolve_binding
from .credentials import CredentialResolver
from .mcp_stateful_client import HttpStatefulClient, StdIOStatefulClient
from .mcp_streamable_http import HttpAutoClient
from .results import call_result, plain

_CAPABILITY_CACHE_TTL_SECONDS = 10.0


class _CredentialAuth(httpx.Auth):
    """Refresh declared credentials on requests without replacing sessions."""

    def __init__(self, context, resolver, binding, headers):
        self.context, self.resolver, self.binding = context, resolver, binding
        self._header_names = set(headers)

    async def async_auth_flow(self, request):
        credentials = await self.resolver.resolve(self.context)
        headers = resolve_binding(self.binding, credentials)
        headers.update(implicit_auth_headers(credentials, headers))
        for key in self._header_names:
            request.headers.pop(key, None)
        request.headers.update(headers)
        self._header_names.update(headers)
        yield request


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
        self.credentials = credentials or CredentialResolver()
        self._client = None
        self._capability_cache = None

    async def open(self):
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
                    **resolve_binding(endpoint.get("env") or {}, credentials),
                },
                cwd=endpoint.get("cwd") or None,
            )
        else:
            headers = resolve_binding(
                endpoint.get("headers") or {},
                credentials,
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
                auth=_CredentialAuth(
                    self.context,
                    self.credentials,
                    endpoint.get("headers") or {},
                    headers,
                ),
                **connect_kwargs,
            )
        # The host installs this connection's close owner before entering open.
        await self._client.connect(**connect_kwargs)

    async def discover(self, request):
        request.check_cancelled()
        now = time.monotonic()
        if self._capability_cache is not None:
            timestamp, specs = self._capability_cache
            if now - timestamp <= _CAPABILITY_CACHE_TTL_SECONDS:
                return specs
        tools = await self._client.list_tools()
        specs = []
        for tool in tools:
            raw = plain(getattr(tool, "_tool", tool))
            name = str(raw["name"])
            prefix = f"mcp__{self.source.source_id}__"
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
        result = tuple(specs)
        self._capability_cache = (now, result)
        return result

    async def invoke(self, name, arguments, request):
        request.check_cancelled()
        return call_result(
            await self._client.call_tool(name, plain(arguments)),
        )

    async def close(self):
        self._capability_cache = None
        if self._client is not None:
            client = self._client
            close_owned = getattr(client, "close_owned", None)
            if close_owned is not None:
                await close_owned()
            else:
                await client.close(ignore_errors=False)
            self._client = None
