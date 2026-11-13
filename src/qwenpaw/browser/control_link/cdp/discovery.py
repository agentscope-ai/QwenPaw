# -*- coding: utf-8 -*-
"""Local endpoint discovery for debuggable CDP browsers."""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

import httpx

_DEFAULT_PORT_MIN = 9222
_DEFAULT_PORT_MAX = 9232
_TARGET_FIELDS = ("id", "type", "url", "title", "webSocketDebuggerUrl")


async def fetch_cdp_json(
    port: int,
    *,
    client: Any | None = None,
) -> list[Mapping[str, Any]] | None:
    try:
        if client is not None:
            response = await client.get(f"http://127.0.0.1:{port}/json")
            response.raise_for_status()
            payload = response.json()
        else:
            async with httpx.AsyncClient(timeout=0.3) as http_client:
                response = await http_client.get(
                    f"http://127.0.0.1:{port}/json",
                )
                response.raise_for_status()
                payload = response.json()
        return payload if isinstance(payload, list) else None
    # intentional boundary: CDP discovery treats an unreachable port as absent.
    except Exception:
        return None


def _ports(port: int, port_min: int, port_max: int) -> list[int]:
    if port:
        return [port]
    if port_min or port_max:
        start = port_min or port_max
        end = port_max or port_min
        return list(range(start, end + 1))
    return list(range(_DEFAULT_PORT_MIN, _DEFAULT_PORT_MAX + 1))


async def list_cdp_targets(
    port: int = 0,
    port_min: int = 0,
    port_max: int = 0,
    *,
    client: Any | None = None,
) -> dict[str, Any]:
    """Return normalized inspectable targets from local debugging ports."""
    ports = _ports(port, port_min, port_max)
    payloads = await asyncio.gather(
        *(fetch_cdp_json(candidate, client=client) for candidate in ports),
    )
    targets = [
        {
            "port": candidate,
            **{field: item.get(field, "") for field in _TARGET_FIELDS},
        }
        for candidate, payload in zip(ports, payloads)
        for item in (payload or [])
        if isinstance(item, Mapping)
    ]
    return {
        "ok": bool(targets),
        "targets": targets,
        "message": (
            "CDP targets found"
            if targets
            else "No local CDP endpoint found; start Chrome with "
            "--remote-debugging-port=N"
        ),
    }
