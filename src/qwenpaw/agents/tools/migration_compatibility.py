# -*- coding: utf-8 -*-
"""Private tools used by Mission migration compatibility work."""

from __future__ import annotations

import json
from typing import Any

from ...runtime.tool_registry import tool_descriptor


def _context() -> Any:
    from ...portability.adaptation_loop import get_active_adaptation_context

    return get_active_adaptation_context()


async def _invoke(method: str, *args: Any, **kwargs: Any) -> str:
    try:
        value = await getattr(_context(), method)(*args, **kwargs)
    except Exception as exc:  # pylint: disable=broad-except
        value = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return json.dumps(value, ensure_ascii=False, default=str)


_COMMON: dict[str, Any] = {
    "enabled_by_default": False,
    "tool_type": "internal",
    "default_policy": "allow",
    "display_to_user": False,
    "self_authorizing_request_opt_in": True,
}


def _compat_tool(name: str, description: str) -> Any:
    return tool_descriptor(name=name, description=description, **_COMMON)


@_compat_tool(
    "migration_compat_inspect",
    "Inspect one staged asset and current QwenPaw capabilities.",
)
async def migration_compat_inspect(asset_key: str) -> str:
    return await _invoke("inspect_asset", asset_key)


@_compat_tool(
    "migration_compat_read_file",
    "Read one staged asset file; paginate until has_more=false.",
)
async def migration_compat_read_file(
    asset_key: str,
    relative_path: str,
    start_line: int = 1,
    end_line: int = 240,
) -> str:
    return await _invoke(
        "read_file",
        asset_key,
        relative_path,
        start_line=start_line,
        end_line=end_line,
    )


@_compat_tool(
    "migration_compat_write_file",
    "Create or overwrite one text file inside a repair asset.",
)
async def migration_compat_write_file(
    asset_key: str,
    relative_path: str,
    content: str,
) -> str:
    return await _invoke("write_file", asset_key, relative_path, content)


@_compat_tool(
    "migration_compat_update",
    "Update one allowlisted MCP or scheduled-task field.",
)
async def migration_compat_update(
    asset_key: str,
    field: str,
    value_json: str,
) -> str:
    return await _invoke("update_asset", asset_key, field, value_json)


@_compat_tool(
    "migration_compat_finalize",
    "Run the final native test and promote the fully repaired asset on pass.",
)
async def migration_compat_finalize(
    asset_key: str,
    reason: str,
) -> str:
    return await _invoke("finalize_asset", asset_key, reason)
