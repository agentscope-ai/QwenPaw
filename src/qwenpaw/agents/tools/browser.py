# -*- coding: utf-8 -*-
"""QwenPaw builtin tool binding for the unified Browser SDK."""

from __future__ import annotations

from pathlib import Path

from agentscope.tool import ToolChunk

from ...runtime.tool_registry import tool_descriptor

from ...browser.tool_entrypoint import (
    _BROWSER_TOOL_DESCRIPTION,
    run_browser_tool,
)


@tool_descriptor(
    name="browser",
    enabled_by_default=True,
    async_execution=True,
    description=_BROWSER_TOOL_DESCRIPTION,
    tool_type="network",
    policy_name="Browser",
    default_policy="allow",
    policy_reason="Allow all browser access",
    ui_description="Browser automation and web interaction",
    ui_icon="🌐",
    bound_skills=("browser",),
    bound_skills_root=str(Path(__file__).resolve().parent.parent / "skills"),
)
async def browser(code: str) -> ToolChunk:
    """Run Browser SDK code in the caller's session-scoped kernel."""
    return await run_browser_tool(code)
