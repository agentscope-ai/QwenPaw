# -*- coding: utf-8 -*-
"""OpenSandbox MCP launcher with server-proxy support.

The official ``opensandbox-mcp`` CLI currently does not expose the SDK
``ConnectionConfig.use_server_proxy`` option. This launcher keeps all MCP tools
official by delegating to ``opensandbox_mcp.create_server`` and only fills the
missing connection configuration.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from opensandbox.config import ConnectionConfig
import opensandbox_mcp.server as opensandbox_mcp_server

from security_center_audit import (
    AuditConfig,
    SecurityCenterAuditReporter,
    install_audit_hook,
)

_RECOMMENDED_SANDBOX_IMAGE = "docker.io/library/python:3.10-alpine"
_COMPATIBLE_SANDBOX_IMAGES = (
    "docker.io/library/python:3.10-slim",
    "docker.io/opensandbox/execd:v1.0.16",
)
_SUPPORTED_SANDBOX_IMAGES = (
    _RECOMMENDED_SANDBOX_IMAGE,
) + _COMPATIBLE_SANDBOX_IMAGES
_UNSUPPORTED_IMAGE_MESSAGE = (
    f'not support image, pls use "{_RECOMMENDED_SANDBOX_IMAGE}" '
    "instead."
)
_COMMAND_RUN_PREFERENCE_DESCRIPTION = (
    "Preferred tool for executing shell/system commands when OpenSandbox MCP "
    "is enabled. Use this instead of QwenPaw's execute_shell_command whenever "
    "possible so commands run inside an isolated sandbox."
)
_DEFAULT_SANDBOX_TIMEOUT_SECONDS = 300.0
_DEFAULT_SANDBOX_IDLE_TIMEOUT_SECONDS = 30.0
_DEFAULT_SANDBOX_IDLE_SCAN_INTERVAL_SECONDS = 5.0
_MANAGED_METADATA_KEY = "qwenpaw_managed"
_AGENT_METADATA_KEY = "qwenpaw_agent_id"
_LAUNCHER_METADATA_KEY = "qwenpaw_launcher_instance_id"
_TERMINAL_SANDBOX_STATES = {"terminated", "stopping", "failed", "unknown"}

logger = logging.getLogger(__name__)


def _env_bool(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(
        f"{name} must be one of true/false, 1/0, yes/no, or on/off",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OpenSandbox MCP launcher for QwenPaw.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="Transport to use.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="OpenSandbox API key (overrides OPEN_SANDBOX_API_KEY).",
    )
    parser.add_argument(
        "--domain",
        default=None,
        help="OpenSandbox API domain (overrides OPEN_SANDBOX_DOMAIN).",
    )
    parser.add_argument(
        "--protocol",
        choices=("http", "https"),
        default="http",
        help="Protocol to use for API requests.",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=30,
        help="HTTP request timeout in seconds.",
    )
    parser.add_argument(
        "--sandbox-default-timeout-seconds",
        type=float,
        default=_DEFAULT_SANDBOX_TIMEOUT_SECONDS,
        help=(
            "Default sandbox_create timeout_seconds when the caller omits it. "
            "This is the sandbox absolute lifetime in seconds."
        ),
    )
    parser.add_argument(
        "--sandbox-idle-timeout-seconds",
        type=float,
        default=_DEFAULT_SANDBOX_IDLE_TIMEOUT_SECONDS,
        help=(
            "Kill QwenPaw-managed sandboxes after this many seconds without "
            "a new command_run call. Set <=0 to disable idle cleanup."
        ),
    )
    parser.add_argument(
        "--sandbox-idle-scan-interval-seconds",
        type=float,
        default=_DEFAULT_SANDBOX_IDLE_SCAN_INTERVAL_SECONDS,
        help="Interval in seconds between idle sandbox cleanup scans.",
    )
    audit_group = parser.add_mutually_exclusive_group()
    audit_group.add_argument(
        "--audit-enabled",
        action="store_true",
        default=False,
        help=(
            "Report OpenSandbox MCP tool-call audit events to Security "
            "Center."
        ),
    )
    audit_group.add_argument(
        "--audit-disabled",
        action="store_false",
        dest="audit_enabled",
        default=False,
        help="Disable Security Center audit reporting.",
    )
    parser.add_argument(
        "--security-center-url",
        default="http://127.0.0.1:8091",
        help="Security Center base URL or complete V1 event intake URL.",
    )
    parser.add_argument(
        "--audit-agent-id",
        default="unknown",
        help="Agent identifier included in OpenSandbox audit events.",
    )
    parser.add_argument(
        "--audit-timeout-seconds",
        type=float,
        default=2.0,
        help="Security Center audit HTTP timeout in seconds.",
    )
    proxy_group = parser.add_mutually_exclusive_group()
    proxy_group.add_argument(
        "--use-server-proxy",
        action="store_true",
        default=None,
        help=(
            "Use opensandbox-server as proxy for sandbox execd/endpoint "
            "requests."
        ),
    )
    proxy_group.add_argument(
        "--no-use-server-proxy",
        action="store_false",
        dest="use_server_proxy",
        help=(
            "Disable opensandbox-server proxy for sandbox data-plane "
            "requests."
        ),
    )
    return parser


def _sandbox_image_ref(image: object) -> str | None:
    """Extract the image reference from SDK image inputs."""
    if image is None:
        return None
    if isinstance(image, str):
        return image.strip()
    image_ref = getattr(image, "image", None) or getattr(image, "uri", None)
    if image_ref is None:
        return None
    return str(image_ref).strip()


def _resolve_sandbox_image(image: object) -> object:
    """Return a supported sandbox workload image before provisioning."""
    image_ref = _sandbox_image_ref(image)
    if image_ref is None:
        return _RECOMMENDED_SANDBOX_IMAGE
    if image_ref not in _SUPPORTED_SANDBOX_IMAGES:
        raise ValueError(_UNSUPPORTED_IMAGE_MESSAGE)
    return image


def _install_image_allowlist_guard() -> None:
    """Guard official sandbox_create without forking official MCP tools."""
    sandbox_cls = getattr(opensandbox_mcp_server, "Sandbox", None)
    if sandbox_cls is None:
        return
    if getattr(sandbox_cls, "_qwenpaw_image_allowlist_guard", False):
        return

    original_create = getattr(sandbox_cls, "create", None)
    if not callable(original_create):
        return

    async def guarded_create(
        image: object | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return await original_create(
            _resolve_sandbox_image(image),
            *args,
            **kwargs,
        )

    setattr(sandbox_cls, "create", guarded_create)
    setattr(sandbox_cls, "_qwenpaw_image_allowlist_guard", True)


def _jsonable(value: Any) -> Any:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _find_nested_value(
    value: Any,
    keys: set[str],
    depth: int = 0,
) -> Any:
    if depth >= 5:
        return None
    normalized = _jsonable(value)
    if isinstance(normalized, Mapping):
        for key, item in normalized.items():
            if str(key) in keys and item is not None:
                return item
        for item in normalized.values():
            found = _find_nested_value(item, keys, depth + 1)
            if found is not None:
                return found
    elif isinstance(normalized, list):
        for item in normalized:
            found = _find_nested_value(item, keys, depth + 1)
            if found is not None:
                return found
    return None


def _sandbox_id_from_result(value: Any) -> str | None:
    sandbox_id = _find_nested_value(value, {"sandbox_id", "sandboxId", "id"})
    if sandbox_id is None:
        return None
    return str(sandbox_id)


def _sandbox_items(value: Any) -> list[Any]:
    normalized = _jsonable(value)
    if isinstance(normalized, list):
        return normalized
    if not isinstance(normalized, Mapping):
        return []
    for key in ("sandbox_infos", "sandboxInfos", "items", "sandboxes", "data"):
        items = normalized.get(key)
        if isinstance(items, list):
            return items
    return []


def _has_next_page(value: Any) -> bool:
    normalized = _jsonable(value)
    if not isinstance(normalized, Mapping):
        return False
    pagination = normalized.get("pagination")
    if not isinstance(pagination, Mapping):
        return False
    return bool(
        pagination.get("has_next_page")
        or pagination.get("hasNextPage")
        or pagination.get("has_next"),
    )


def _sandbox_state(item: Any) -> str:
    normalized = _jsonable(item)
    if not isinstance(normalized, Mapping):
        return ""
    status = normalized.get("status")
    if isinstance(status, Mapping):
        return str(status.get("state") or "").strip().lower()
    return str(normalized.get("state") or "").strip().lower()


def _sandbox_metadata(item: Any) -> dict[str, str]:
    normalized = _jsonable(item)
    if not isinstance(normalized, Mapping):
        return {}
    metadata = normalized.get("metadata")
    if not isinstance(metadata, Mapping):
        return {}
    return {str(key): str(value) for key, value in metadata.items()}


@dataclass
class SandboxLifecycleConfig:
    default_timeout_seconds: float = _DEFAULT_SANDBOX_TIMEOUT_SECONDS
    idle_timeout_seconds: float = _DEFAULT_SANDBOX_IDLE_TIMEOUT_SECONDS
    idle_scan_interval_seconds: float = (
        _DEFAULT_SANDBOX_IDLE_SCAN_INTERVAL_SECONDS
    )
    agent_id: str = "unknown"


@dataclass
class _TrackedSandbox:
    last_command_at: float
    active_commands: int = 0


@dataclass
class SandboxLifecycleManager:
    """Apply QwenPaw sandbox TTL defaults and idle cleanup policy."""

    tool_manager: Any
    original_call_tool: Any
    config: SandboxLifecycleConfig
    launcher_instance_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _tracked: dict[str, _TrackedSandbox] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _janitor_task: asyncio.Task | None = None

    def managed_metadata(self) -> dict[str, str]:
        return {
            _MANAGED_METADATA_KEY: "true",
            _AGENT_METADATA_KEY: self.config.agent_id or "unknown",
            _LAUNCHER_METADATA_KEY: self.launcher_instance_id,
        }

    def prepare_arguments(
        self,
        name: str,
        arguments: dict[str, Any] | None,
    ) -> dict[str, Any]:
        prepared = dict(arguments or {})
        if name != "sandbox_create":
            return prepared

        if prepared.get("timeout_seconds") is None:
            prepared["timeout_seconds"] = self.config.default_timeout_seconds

        metadata = prepared.get("metadata")
        if isinstance(metadata, Mapping):
            merged_metadata = {
                str(key): str(value) for key, value in metadata.items()
            }
        else:
            merged_metadata = {}
        for key, value in self.managed_metadata().items():
            merged_metadata.setdefault(key, value)
        prepared["metadata"] = merged_metadata
        return prepared

    async def record_tool_start(
        self,
        name: str,
        arguments: Mapping[str, Any],
    ) -> None:
        sandbox_id = arguments.get("sandbox_id")
        if sandbox_id is None or name != "command_run":
            return
        now = time.monotonic()
        async with self._lock:
            tracked = self._tracked.setdefault(
                str(sandbox_id),
                _TrackedSandbox(last_command_at=now),
            )
            tracked.last_command_at = now
            tracked.active_commands += 1

    async def record_tool_finish(
        self,
        name: str,
        arguments: Mapping[str, Any],
        result: Any = None,
    ) -> None:
        now = time.monotonic()
        if name in {"sandbox_create", "sandbox_connect"}:
            sandbox_id = _sandbox_id_from_result(result)
            if sandbox_id is not None:
                async with self._lock:
                    self._tracked.setdefault(
                        sandbox_id,
                        _TrackedSandbox(last_command_at=now),
                    )
            return

        sandbox_id = arguments.get("sandbox_id")
        if sandbox_id is None:
            return
        sandbox_id = str(sandbox_id)
        async with self._lock:
            if name == "sandbox_kill":
                self._tracked.pop(sandbox_id, None)
                return
            if name == "command_run":
                tracked = self._tracked.setdefault(
                    sandbox_id,
                    _TrackedSandbox(last_command_at=now),
                )
                tracked.last_command_at = now
                tracked.active_commands = max(0, tracked.active_commands - 1)

    async def _list_sandboxes(self) -> list[Any]:
        results: list[Any] = []
        page = 1
        while True:
            result = await self.original_call_tool(
                "sandbox_list",
                {
                    "filter": {
                        "page": page,
                        "page_size": 100,
                    },
                },
            )
            results.extend(_sandbox_items(result))
            if not _has_next_page(result):
                break
            page += 1
            if page > 100:
                logger.warning(
                    "OpenSandbox idle cleanup stopped after 100 pages",
                )
                break
        return results

    def _is_managed_item(self, item: Any) -> bool:
        metadata = _sandbox_metadata(item)
        return (
            metadata.get(_MANAGED_METADATA_KEY) == "true"
            and metadata.get(_AGENT_METADATA_KEY)
            == (self.config.agent_id or "unknown")
        )

    async def cleanup_once(self) -> None:
        if self.config.idle_timeout_seconds <= 0:
            return

        now = time.monotonic()
        live_ids: set[str] = set()
        terminal_ids: set[str] = set()
        async with self._lock:
            tracked_ids = set(self._tracked)

        try:
            items = await self._list_sandboxes()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("OpenSandbox idle sandbox list failed: %s", exc)
            return

        for item in items:
            sandbox_id = _sandbox_id_from_result(item)
            if sandbox_id is None:
                continue
            state = _sandbox_state(item)
            if state in _TERMINAL_SANDBOX_STATES:
                terminal_ids.add(sandbox_id)
                continue
            if self._is_managed_item(item) or sandbox_id in tracked_ids:
                live_ids.add(sandbox_id)

        async with self._lock:
            for sandbox_id in live_ids:
                self._tracked.setdefault(
                    sandbox_id,
                    _TrackedSandbox(last_command_at=now),
                )
            for sandbox_id in terminal_ids:
                self._tracked.pop(sandbox_id, None)

            candidates = [
                sandbox_id
                for sandbox_id, tracked in self._tracked.items()
                if sandbox_id in live_ids
                and tracked.active_commands <= 0
                and now - tracked.last_command_at
                >= self.config.idle_timeout_seconds
            ]

        for sandbox_id in candidates:
            try:
                await self.original_call_tool(
                    "sandbox_kill",
                    {"sandbox_id": sandbox_id},
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "OpenSandbox idle cleanup failed for %s: %s",
                    sandbox_id,
                    exc,
                )
                continue
            async with self._lock:
                self._tracked.pop(sandbox_id, None)
            logger.info(
                "OpenSandbox idle cleanup killed sandbox %s after %.1fs",
                sandbox_id,
                self.config.idle_timeout_seconds,
            )

    def ensure_janitor_running(self) -> None:
        if self.config.idle_timeout_seconds <= 0:
            return
        if self._janitor_task is not None and not self._janitor_task.done():
            return

        async def janitor() -> None:
            interval = max(1.0, self.config.idle_scan_interval_seconds)
            while True:
                await asyncio.sleep(interval)
                await self.cleanup_once()

        self._janitor_task = asyncio.create_task(janitor())


def install_sandbox_lifecycle_hook(
    mcp: Any,
    config: SandboxLifecycleConfig,
) -> SandboxLifecycleManager:
    tool_manager = getattr(mcp, "_tool_manager", None)
    original_call_tool = getattr(tool_manager, "call_tool", None)
    if not callable(original_call_tool):
        raise RuntimeError("OpenSandbox MCP tool manager is unavailable")
    existing_manager = getattr(tool_manager, "_qwenpaw_sandbox_lifecycle", None)
    if isinstance(existing_manager, SandboxLifecycleManager):
        return existing_manager

    manager = SandboxLifecycleManager(
        tool_manager=tool_manager,
        original_call_tool=original_call_tool,
        config=config,
    )

    async def lifecycle_call_tool(
        name: str,
        arguments: dict[str, Any] | None = None,
        context: Any = None,
        convert_result: bool = False,
    ) -> Any:
        manager.ensure_janitor_running()
        prepared_arguments = manager.prepare_arguments(name, arguments)
        await manager.record_tool_start(name, prepared_arguments)
        try:
            result = await original_call_tool(
                name,
                prepared_arguments,
                context=context,
                convert_result=convert_result,
            )
        finally:
            if name == "command_run":
                await manager.record_tool_finish(name, prepared_arguments)
        if name != "command_run":
            await manager.record_tool_finish(
                name,
                prepared_arguments,
                result=result,
            )
        return result

    setattr(tool_manager, "call_tool", lifecycle_call_tool)
    setattr(tool_manager, "_qwenpaw_sandbox_lifecycle", manager)
    return manager


def _annotate_sandbox_create_defaults(
    mcp: Any,
    default_timeout_seconds: float,
) -> None:
    """Expose the image allowlist and lifecycle defaults in tool schema."""
    tool_manager = getattr(mcp, "_tool_manager", None)
    get_tool = getattr(tool_manager, "get_tool", None)
    if not callable(get_tool):
        return
    tool = get_tool("sandbox_create")
    if tool is None:
        return

    guard_description = (
        f'Recommended and default image: "{_RECOMMENDED_SANDBOX_IMAGE}". '
        f"Only supported images: {', '.join(_SUPPORTED_SANDBOX_IMAGES)}. "
        f"Other images return: {_UNSUPPORTED_IMAGE_MESSAGE}"
    )
    description = getattr(tool, "description", "") or ""
    if guard_description not in description:
        tool.description = f"{guard_description}\n\n{description}".strip()

    parameters = getattr(tool, "parameters", None)
    if not isinstance(parameters, dict):
        return
    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        return
    image_schema = properties.get("image")
    if isinstance(image_schema, dict):
        image_schema["enum"] = list(_SUPPORTED_SANDBOX_IMAGES)
        image_schema["default"] = _RECOMMENDED_SANDBOX_IMAGE
        image_schema["description"] = guard_description

    timeout_schema = properties.get("timeout_seconds")
    if isinstance(timeout_schema, dict):
        timeout_schema["default"] = default_timeout_seconds
        timeout_schema["description"] = (
            "Sandbox absolute lifetime in seconds. QwenPaw defaults this to "
            f"{default_timeout_seconds:g} seconds when omitted."
        )


def _annotate_command_run_preference(mcp: Any) -> None:
    """Tell agents to prefer command_run over host-shell execution."""
    tool_manager = getattr(mcp, "_tool_manager", None)
    get_tool = getattr(tool_manager, "get_tool", None)
    if not callable(get_tool):
        return
    tool = get_tool("command_run")
    if tool is None:
        return

    description = getattr(tool, "description", "") or ""
    if _COMMAND_RUN_PREFERENCE_DESCRIPTION not in description:
        tool.description = (
            f"{_COMMAND_RUN_PREFERENCE_DESCRIPTION}\n\n{description}"
        ).strip()


def _connection_config_from_args(args: argparse.Namespace) -> ConnectionConfig:
    config_values = {}
    if args.api_key:
        config_values["api_key"] = args.api_key
    if args.domain:
        config_values["domain"] = args.domain
    if args.protocol:
        config_values["protocol"] = args.protocol
    if args.request_timeout_seconds is not None:
        config_values["request_timeout"] = timedelta(
            seconds=args.request_timeout_seconds,
        )

    env_proxy = _env_bool("OPEN_SANDBOX_USE_SERVER_PROXY")
    use_server_proxy = (
        args.use_server_proxy
        if args.use_server_proxy is not None
        else env_proxy
    )
    if use_server_proxy is not None:
        config_values["use_server_proxy"] = use_server_proxy

    return ConnectionConfig(**config_values)


def _validate_lifecycle_args(args: argparse.Namespace) -> None:
    if args.sandbox_default_timeout_seconds <= 0:
        raise ValueError("--sandbox-default-timeout-seconds must be > 0")
    if args.sandbox_idle_scan_interval_seconds <= 0:
        raise ValueError("--sandbox-idle-scan-interval-seconds must be > 0")


def main() -> None:
    args = _build_parser().parse_args()
    _validate_lifecycle_args(args)
    connection_config = _connection_config_from_args(args)
    _install_image_allowlist_guard()
    mcp = opensandbox_mcp_server.create_server(
        connection_config=connection_config,
    )
    _annotate_sandbox_create_defaults(
        mcp,
        args.sandbox_default_timeout_seconds,
    )
    _annotate_command_run_preference(mcp)
    if args.audit_enabled:
        install_audit_hook(
            mcp,
            SecurityCenterAuditReporter(
                AuditConfig(
                    security_center_url=args.security_center_url,
                    agent_id=args.audit_agent_id,
                    timeout_seconds=args.audit_timeout_seconds,
                ),
            ),
        )
    install_sandbox_lifecycle_hook(
        mcp,
        SandboxLifecycleConfig(
            default_timeout_seconds=args.sandbox_default_timeout_seconds,
            idle_timeout_seconds=args.sandbox_idle_timeout_seconds,
            idle_scan_interval_seconds=args.sandbox_idle_scan_interval_seconds,
            agent_id=args.audit_agent_id,
        ),
    )

    if args.transport == "streamable-http":
        mcp.run(transport="streamable-http")
        return

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    mcp.run()


if __name__ == "__main__":
    main()
