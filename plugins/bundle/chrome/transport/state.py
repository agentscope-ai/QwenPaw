# -*- coding: utf-8 -*-
"""Native Messaging bridge route state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class NMBridgeRouteState:
    """State shared by Chrome route module instances."""

    token: str | None = None
    ws_url: str = ""
    config_path: Path | None = None


_state = NMBridgeRouteState()


def get_nm_bridge_route_state() -> NMBridgeRouteState:
    """Return the process-wide Chrome route state."""
    return _state


__all__ = ["NMBridgeRouteState", "get_nm_bridge_route_state"]
