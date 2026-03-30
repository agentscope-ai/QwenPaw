# -*- coding: utf-8 -*-
"""Sessions spawn tool compatibility shim.

`runtime="acp"` has moved to the chat external-agent flow.
"""
from typing import Literal, Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config import load_config

DEFAULT_ACP_TIMEOUT = 900


async def sessions_spawn(
    task: str,
    runtime: Literal["subagent", "acp"] = "acp",
    harness: str = "",
    mode: Literal["run", "session"] = "run",
    session_id: Optional[str] = None,
    cwd: Optional[str] = None,
    timeout: int = DEFAULT_ACP_TIMEOUT,
) -> ToolResponse:
    """Spawn a sub-agent or return an ACP migration hint.

    `runtime="acp"` is kept only as a compatibility surface so older prompts
    or tool calls fail with a clear migration message.
    """
    _ = task, mode, session_id, cwd, timeout

    config = load_config()
    if not hasattr(config, "acp") or not config.acp.enabled:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "Error: ACP is not enabled. "
                        "Set 'acp.enabled: true' in config."
                    ),
                ),
            ],
        )

    if runtime == "acp":
        harness_hint = f" ({harness})" if harness else ""
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "Error: ACP runtime is now handled by the "
                        "chat external-agent mode"
                        f"{harness_hint}. "
                        "Please choose OpenCode or Qwen Code from the "
                        "chat UI instead of "
                        "calling sessions_spawn(runtime='acp')."
                    ),
                ),
            ],
        )

    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text="Error: runtime='subagent' is not yet implemented.",
            ),
        ],
    )
