# -*- coding: utf-8 -*-
"""Lightweight validation for persisted MCP endpoint configuration."""

from ..contracts import DriverCard
from ..errors import DriverCardError


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
