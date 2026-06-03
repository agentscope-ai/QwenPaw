# -*- coding: utf-8 -*-
"""OpenSandbox MCP launcher with server-proxy support.

The official ``opensandbox-mcp`` CLI currently does not expose the SDK
``ConnectionConfig.use_server_proxy`` option. This launcher keeps all MCP tools
official by delegating to ``opensandbox_mcp.create_server`` and only fills the
missing connection configuration.
"""

from __future__ import annotations

import argparse
import os
from datetime import timedelta
from typing import Any

from opensandbox.config import ConnectionConfig
import opensandbox_mcp.server as opensandbox_mcp_server

_ALLOWED_SANDBOX_IMAGE = "opensandbox/code-interpreter:v1.0.2"
_UNSUPPORTED_IMAGE_MESSAGE = (
    'not support image, pls use "opensandbox/code-interpreter:v1.0.2" '
    "instead."
)


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


def _validate_sandbox_image(image: object) -> None:
    """Reject unsupported sandbox workload images before provisioning."""
    image_ref = _sandbox_image_ref(image)
    if image_ref is None:
        return
    if image_ref != _ALLOWED_SANDBOX_IMAGE:
        raise ValueError(_UNSUPPORTED_IMAGE_MESSAGE)


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
        _validate_sandbox_image(image)
        return await original_create(image, *args, **kwargs)

    setattr(sandbox_cls, "create", guarded_create)
    setattr(sandbox_cls, "_qwenpaw_image_allowlist_guard", True)


def _annotate_image_allowlist(mcp: Any) -> None:
    """Expose the image allowlist in the official sandbox_create schema."""
    tool_manager = getattr(mcp, "_tool_manager", None)
    get_tool = getattr(tool_manager, "get_tool", None)
    if not callable(get_tool):
        return
    tool = get_tool("sandbox_create")
    if tool is None:
        return

    guard_description = (
        f'Only supported image: "{_ALLOWED_SANDBOX_IMAGE}". '
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
    if not isinstance(image_schema, dict):
        return
    image_schema["enum"] = [_ALLOWED_SANDBOX_IMAGE]
    image_schema["description"] = guard_description


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


def main() -> None:
    args = _build_parser().parse_args()
    connection_config = _connection_config_from_args(args)
    _install_image_allowlist_guard()
    mcp = opensandbox_mcp_server.create_server(
        connection_config=connection_config,
    )
    _annotate_image_allowlist(mcp)

    if args.transport == "streamable-http":
        mcp.run(transport="streamable-http")
        return

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    mcp.run()


if __name__ == "__main__":
    main()
