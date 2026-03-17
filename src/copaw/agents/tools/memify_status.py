# -*- coding: utf-8 -*-
"""Tool to query memify enrichment job status."""

from __future__ import annotations

import json

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config import load_config
from ...constant import WORKING_DIR
from ...knowledge.graph_ops import GraphOpsManager


async def memify_status(job_id: str) -> ToolResponse:
    """Get memify job status by job id."""
    normalized_job_id = (job_id or "").strip()
    if not normalized_job_id:
        return ToolResponse(
            content=[TextBlock(type="text", text="Error: job_id cannot be empty.")],
        )

    config = load_config()
    if not getattr(config, "knowledge", None) or not config.knowledge.enabled:
        return ToolResponse(
            content=[TextBlock(type="text", text="Error: knowledge is disabled in configuration.")],
        )
    if not bool(getattr(config.agents.running, "knowledge_enabled", True)):
        return ToolResponse(
            content=[TextBlock(type="text", text="Error: knowledge is disabled in agent runtime configuration.")],
        )
    if not bool(getattr(config.knowledge, "memify_enabled", False)):
        return ToolResponse(
            content=[TextBlock(type="text", text="Error: memify is disabled in configuration.")],
        )

    try:
        manager = GraphOpsManager(WORKING_DIR)
        result = manager.get_memify_status(normalized_job_id)
        if result is None:
            return ToolResponse(
                content=[TextBlock(type="text", text="Error: memify job not found.")],
            )
        return ToolResponse(
            content=[TextBlock(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))],
        )
    except Exception as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error: memify status failed due to\n{e}")],
        )