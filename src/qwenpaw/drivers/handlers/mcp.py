# -*- coding: utf-8 -*-
"""MCP Driver handler."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from ..capabilities import (
    CapabilityExposure,
    DriverCapability,
    DriverInvocation,
    DriverInvocationResult,
    format_capability_id,
    parse_capability_id,
)
from ..constants import (
    CAPABILITY_KIND_TOOL,
    DRIVER_OPERATION_INVOKE,
    PRINCIPAL_SOURCE_CHANNEL,
    PRINCIPAL_SUBJECT_SESSION,
    PRINCIPAL_SUBJECT_USER,
    PROTOCOL_MCP,
    SUBJECT_UNKNOWN_USER,
)
from ..contracts import DriverCard, PolicyTarget
from ..credentials.bindings import (
    implicit_auth_headers,
    resolve_binding,
)
from .mcp_stateful_client import (
    HttpStatefulClient,
    StdIOStatefulClient,
)
from ..credentials.types import ResolvedCredential
from ..errors import (
    ApprovalRequiredError,
    DriverCardError,
    DriverPermissionDeniedError,
)
from ..handler import DriverHandler
from ..policy import PolicyContext

logger = logging.getLogger(__name__)
_CAPABILITY_CACHE_TTL_SECONDS = 10.0


class MCPDriverHandler(DriverHandler):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._client: Any | None = None
        self._capability_cache: tuple[
            float,
            list[DriverCapability],
        ] | None = None

    async def _setup(self) -> None:
        """Create and connect StdIOStatefulClient or HttpStatefulClient."""
        endpoint = self._card.endpoint
        transport = str(endpoint.get("transport") or "stdio")
        credentials = await self._resolve_credentials()

        if transport == "stdio":
            self._client = StdIOStatefulClient(
                name=self._card.name,
                command=str(endpoint.get("command") or ""),
                args=list(endpoint.get("args") or []),
                env=resolve_binding(
                    endpoint.get("env") or {},
                    credentials,
                ),
                cwd=endpoint.get("cwd") or None,
            )
        else:
            headers = resolve_binding(
                endpoint.get("headers") or {},
                credentials,
            )
            headers.update(implicit_auth_headers(credentials, headers))
            self._client = HttpStatefulClient(
                name=self._card.name,
                transport=transport,
                url=str(endpoint.get("url") or ""),
                headers=headers or None,
            )

        try:
            await self._client.connect()
        except asyncio.CancelledError:
            await self._client.close(ignore_errors=True)
            self._client = None
            raise
        except Exception:
            await self._client.close(ignore_errors=True)
            self._client = None
            raise

    async def _teardown(self) -> None:
        """Close connected MCP client if present."""
        self._capability_cache = None
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def _execute(
        self,
        credential: ResolvedCredential,
        context: PolicyContext,
        **kwargs: Any,
    ) -> Any:
        """Call MCP tool on underlying client."""
        del credential
        del context
        if self._client is None:
            raise RuntimeError(f"MCP driver '{self.name}' is not connected")
        return await self._client.call_tool(
            str(kwargs["tool_name"]),
            dict(kwargs.get("arguments") or {}),
        )

    async def list_tools(self) -> Any:
        """Delegate to underlying MCP client list_tools."""
        if self._client is None:
            raise RuntimeError(f"MCP driver '{self.name}' is not connected")
        return await self._client.list_tools()

    async def list_capabilities(
        self,
        request_context: dict[str, str] | None = None,
    ) -> list[DriverCapability]:
        """Expose MCP tools as protocol-neutral Driver capabilities."""
        del request_context
        now = time.monotonic()
        if self._capability_cache is not None:
            cached_at, cached = self._capability_cache
            if now - cached_at <= _CAPABILITY_CACHE_TTL_SECONDS:
                return list(cached)

        tools = await self.list_tools()
        capabilities = [
            _mcp_tool_to_capability(
                self.name,
                tool,
                display_name=str(self._card.config.get("display_name") or ""),
            )
            for tool in tools
        ]
        self._capability_cache = (now, capabilities)
        return list(capabilities)

    async def invoke_capability(
        self,
        invocation: DriverInvocation,
    ) -> DriverInvocationResult:
        """Invoke one MCP tool capability through Driver policy."""
        try:
            (
                protocol,
                driver_name,
                kind,
                action,
                tool_name,
            ) = parse_capability_id(
                invocation.capability_id,
            )
        except ValueError as exc:
            return DriverInvocationResult(
                ok=False,
                error_type="invalid_capability_id",
                message=str(exc),
            )
        if (
            protocol != PROTOCOL_MCP
            or driver_name != self.name
            or kind != CAPABILITY_KIND_TOOL
            or action != DRIVER_OPERATION_INVOKE
        ):
            return DriverInvocationResult(
                ok=False,
                error_type="unsupported_capability",
                message=(
                    f"Unsupported MCP capability: {invocation.capability_id}"
                ),
            )
        subjects = _subjects_from_context(invocation.request_context)
        subject = subjects[0]
        try:
            value = await self._guarded_execute(
                subject,
                operation=DRIVER_OPERATION_INVOKE,
                target=PolicyTarget(kind=CAPABILITY_KIND_TOOL, name=tool_name),
                request_context=invocation.request_context,
                subjects=subjects,
                tool_name=tool_name,
                arguments=dict(invocation.payload or {}),
            )
        except DriverPermissionDeniedError as exc:
            return DriverInvocationResult(
                ok=False,
                error_type="driver_policy_denied",
                message=exc.to_user_message(),
                metadata=exc.to_result(),
            )
        except ApprovalRequiredError as exc:
            return DriverInvocationResult(
                ok=False,
                error_type="driver_policy_approval_required",
                message=str(exc),
            )
        except Exception as exc:
            logger.warning(
                "MCP capability invocation failed for Driver '%s' "
                "tool '%s': %s",
                self.name,
                tool_name,
                exc,
                exc_info=True,
            )
            return DriverInvocationResult(
                ok=False,
                error_type="execution_error",
                message=str(exc),
                metadata={"driver_name": self.name, "tool_name": tool_name},
            )
        return DriverInvocationResult(ok=True, value=value)

    async def _guarded_execute(
        self,
        subject: str,
        operation: str = DRIVER_OPERATION_INVOKE,
        request_context: dict[str, str] | None = None,
        target: PolicyTarget | None = None,
        subjects: list[str] | tuple[str, ...] | None = None,
        **kwargs: Any,
    ) -> Any:
        """MCP request-response policy + credential scaffold."""
        context = await self._authorize_invocation(
            subject,
            operation=operation,
            target=target,
            request_context=request_context,
            subjects=subjects,
            extras=dict(kwargs),
        )
        credential = await self._credential_provider.resolve()
        return await self._execute(credential, context, **kwargs)


def validate_mcp_endpoint(card: DriverCard) -> None:
    """Validate MCP endpoint shape beyond generic DriverCard checks."""
    endpoint = card.endpoint
    transport = str(endpoint.get("transport") or "stdio")
    if transport == "stdio":
        command = endpoint.get("command")
        if not isinstance(command, str) or not command.strip():
            raise DriverCardError(
                f"DriverCard {card.name} stdio endpoint.command must be "
                "a non-empty string",
            )
        args = endpoint.get("args")
        if args is not None and (
            not isinstance(args, list)
            or not all(isinstance(item, str) for item in args)
        ):
            raise DriverCardError(
                f"DriverCard {card.name} endpoint.args must be a list "
                "of strings",
            )
        cwd = endpoint.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise DriverCardError(
                f"DriverCard {card.name} endpoint.cwd must be a string",
            )
        return

    if transport not in {"streamable_http", "sse"}:
        raise DriverCardError(
            f"DriverCard {card.name} has unsupported MCP transport: "
            f"{transport}",
        )
    url = endpoint.get("url")
    if not isinstance(url, str) or not url.strip():
        raise DriverCardError(
            f"DriverCard {card.name} HTTP MCP endpoint.url must be "
            "a non-empty string",
        )


def _subjects_from_context(request_context: dict[str, str]) -> tuple[str, ...]:
    subjects: list[str] = []

    def add(subject: str) -> None:
        if subject and subject not in subjects:
            subjects.append(subject)

    explicit = str(request_context.get("subject") or "").strip()
    if explicit:
        add(explicit)

    user_id = str(request_context.get("user_id") or "").strip()
    if user_id:
        add(_typed_subject(PRINCIPAL_SUBJECT_USER, user_id))

    session_id = str(request_context.get("session_id") or "").strip()
    if session_id:
        add(_typed_subject(PRINCIPAL_SUBJECT_SESSION, session_id))

    channel = str(request_context.get("channel") or "").strip()
    if channel:
        add(_typed_subject(PRINCIPAL_SOURCE_CHANNEL, channel))

    return tuple(subjects or (SUBJECT_UNKNOWN_USER,))


def _typed_subject(kind: str, value: str) -> str:
    if value.startswith(f"{kind}:"):
        return value
    return f"{kind}:{value}"


def _mcp_tool_to_capability(
    driver_name: str,
    tool: Any,
    *,
    display_name: str = "",
) -> DriverCapability:
    raw_tool = getattr(tool, "_tool", tool)
    name = str(getattr(raw_tool, "name", getattr(tool, "name", tool)))
    if name.startswith(f"mcp__{driver_name}__"):
        name = name[len(f"mcp__{driver_name}__") :]
    display_namespace = _tool_namespace_from_display_name(
        display_name,
        fallback=driver_name,
    )
    description = str(
        getattr(raw_tool, "description", getattr(tool, "description", ""))
        or "",
    )
    if display_namespace != driver_name and display_name:
        description = (
            f"{description}\n\n"
            f"MCP server display name: {display_name}. "
            f"Stable MCP client key: {driver_name}."
        ).strip()
    input_schema = (
        getattr(raw_tool, "inputSchema", None)
        or getattr(raw_tool, "input_schema", None)
        or getattr(tool, "input_schema", None)
        or {}
    )
    if not isinstance(input_schema, dict):
        input_schema = {}
    input_schema = dict(input_schema)
    input_schema.setdefault("type", "object")
    input_schema.setdefault("properties", {})
    input_schema.setdefault("required", [])
    return DriverCapability(
        # capability_id keeps the original MCP tool name (URL-encoded) so
        # invoke routing always resolves to the server-side name.
        capability_id=format_capability_id(
            PROTOCOL_MCP,
            driver_name,
            CAPABILITY_KIND_TOOL,
            DRIVER_OPERATION_INVOKE,
            name,
        ),
        driver_name=driver_name,
        protocol=PROTOCOL_MCP,
        kind=CAPABILITY_KIND_TOOL,
        action=DRIVER_OPERATION_INVOKE,
        name=name,
        description=description,
        input_schema=input_schema,
        # tool_name is sanitized to satisfy OpenAI's ^[a-zA-Z0-9_-]+$
        # constraint.
        exposure=CapabilityExposure(
            as_tool=True,
            namespace=display_namespace,
            tool_name=f"{display_namespace}__{_sanitize_tool_name(name)}",
        ),
        metadata={
            "driver_key": driver_name,
            "display_name": display_name or driver_name,
        },
    )


# _TOOL_NAME_SAFE_CHARS matches characters *outside* the allowed set (for
# replacement);
# _TOOL_NAME_ALLOWED matches a string composed *entirely* of allowed
# characters (for fast-path check).
_TOOL_NAME_SAFE_CHARS = re.compile(r"[^A-Za-z0-9_-]+")
_TOOL_NAME_ALLOWED = re.compile(r"[a-zA-Z0-9_-]+")


def _sanitize_tool_name(name: str) -> str:
    """Rewrite an MCP tool name to satisfy OpenAI's ``^[a-zA-Z0-9_-]+$``.

    Names that already match the pattern are returned unchanged.
    Characters outside the allowed set are replaced with ``_`` and leading/
    trailing underscores are stripped.  An empty result falls back to
    ``"tool"``.
    """
    if _TOOL_NAME_ALLOWED.fullmatch(name):
        return name
    return _TOOL_NAME_SAFE_CHARS.sub("_", name).strip("_") or "tool"


def _tool_namespace_from_display_name(
    display_name: str,
    *,
    fallback: str,
) -> str:
    namespace = _TOOL_NAME_SAFE_CHARS.sub("_", display_name.strip()).strip("_")
    return namespace or _sanitize_tool_name(fallback)
