# -*- coding: utf-8 -*-
"""Tool to trigger memify enrichment jobs."""

from __future__ import annotations

import json

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config import load_config
from ...constant import WORKING_DIR
from ...knowledge.graph_ops import GraphOpsManager

_PIPELINE_WHITELIST = {
    "default",
    "coding_rules",
    "triplet_embeddings",
    "session_persistence",
    "entity_consolidation",
}


async def memify_run(
    pipeline_type: str = "default",
    dataset_scope: list[str] | None = None,
    idempotency_key: str = "",
    dry_run: bool = False,
) -> ToolResponse:
    """Trigger a memify enrichment job.

    Args:
        pipeline_type: Pipeline type, defaults to "default".
        dataset_scope: Optional dataset names/ids.
        idempotency_key: Optional key to deduplicate repeated requests.
        dry_run: Whether to run in dry-run mode.
    """
    config = load_config()
    if not getattr(config, "knowledge", None) or not config.knowledge.enabled:
        return ToolResponse(
            content=[TextBlock(type="text", text="Error: knowledge is disabled in configuration.")],
        )
    running = getattr(getattr(config, "agents", None), "running", None)
    if not bool(getattr(running, "knowledge_enabled", True)):
        return ToolResponse(
            content=[TextBlock(type="text", text="Error: knowledge is disabled in agent runtime configuration.")],
        )
    if not bool(getattr(config.knowledge, "memify_enabled", False)):
        return ToolResponse(
            content=[TextBlock(type="text", text="Error: memify is disabled in configuration.")],
        )

    pipeline = (pipeline_type or "default").strip().lower()
    if pipeline not in _PIPELINE_WHITELIST:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="Error: pipeline_type is invalid or not allowed.",
                )
            ],
        )

    try:
        manager = GraphOpsManager(WORKING_DIR)
        result = manager.run_memify(
            config=config.knowledge,
            pipeline_type=pipeline,
            dataset_scope=dataset_scope,
            idempotency_key=(idempotency_key or "").strip(),
            dry_run=bool(dry_run),
        )
        return ToolResponse(
            content=[TextBlock(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))],
        )
    except Exception as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error: memify run failed due to\n{e}")],
        )