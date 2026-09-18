# -*- coding: utf-8 -*-
"""Name-collision messages that name the occupant when stamped."""

from __future__ import annotations


def occupancy_conflict(
    kind: str,
    name: str,
    owner_plugin_id: str = "",
) -> str:
    """Describe a name collision, naming the occupant when known."""
    if owner_plugin_id:
        return (
            f"{kind} {name!r} already registered "
            f"by plugin '{owner_plugin_id}'"
        )
    return f"{kind} {name!r} 已被一个未标注归属的贡献占用"
