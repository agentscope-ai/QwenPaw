# -*- coding: utf-8 -*-
"""Build owner-scoped runtime sessions through the raw ControlLink port."""

from __future__ import annotations

from typing import Any

from ..sdk.contracts import Owner
from .ownership import Session


async def build_session(
    link: Any,
    *,
    context: str,
    owner: Owner,
    variant: str,
    identity: str = "guest",
    launch: dict[str, Any] | None = None,
    user_data_dir: str | None = None,
) -> Session:
    """Open a provider session, create its first page, and return its facts."""
    launch = launch or {}
    raw = await link.request(
        "open_session",
        {
            "workspace_id": owner.workspace_id,
            "session_id": owner.session_id,
            "context": context,
            "user_data_dir": user_data_dir or launch.get("user_data_dir"),
            "headless": launch.get("headless"),
            "engine": launch.get("engine"),
            "executable_path": launch.get("executable_path"),
            "channel": launch.get("channel"),
            "args": launch.get("args", []),
            "viewport": launch.get("viewport"),
            "proxy": launch.get("proxy"),
            "backend": launch.get("backend"),
            "cdp_url": launch.get("cdp_url"),
            "cdp_port": launch.get("cdp_port"),
            "remote_debugging_port": launch.get("remote_debugging_port"),
        },
    )
    headless = raw.get("headless")
    if headless is None:
        headless = bool(launch.get("headless", False))
    return Session(
        owner=owner,
        variant=variant,
        context=context,
        identity=identity,
        headless=bool(headless),
    )
