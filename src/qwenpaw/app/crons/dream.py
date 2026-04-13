# -*- coding: utf-8 -*-
"""
Dream-based memory optimization: run agent with MEMORY.md optimization task at interval.
Similar to heartbeat but for memory optimization through dreaming.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from ...config.config import load_agent_config

logger = logging.getLogger(__name__)


def _get_dream_prompt(language: str = "zh") -> str:
    """Get the dream prompt based on language."""
    prompts = {
        "zh": (
            "现在进入梦境状态，对长期记忆进行优化整理。请读取今日日志与现有长期记忆，"
            "在梦境中提炼高价值增量信息并去重合并，最终覆写至 `MEMORY.md`，"
            "确保长期记忆文件保持最新、精简、无冗余。\n\n【梦境优化原则】\n"
            "1. 极简去冗：严禁记录流水账、Bug修复细节或单次任务。"
            "仅保留“核心业务决策”、“确认的用户偏好”与“高价值可复用经验”。\n"
            "2. 状态覆写：若发现状态变更（如技术栈更改、配置更新），"
            "必须用新状态替换旧状态，严禁新旧矛盾信息并存。\n"
            "3. 归纳整合：主动将零碎的相似规则提炼、合并为通用性强的独立条目。"
            "\n4. 废弃剔除：主动删除已被证伪的假设或不再适用的陈旧条目。\n\n"
            "【梦境执行步骤】\n步骤 1 [加载]：调用 `read` 工具，"
            "读取根目录下的 `MEMORY.md` 以及当天的日志文件 `memory/YYYY-MM-DD.md`。\n"
            "步骤 2 [梦境提纯]：在梦境中对比新旧内容，严格按照【梦境优化原则】进行去重、替换、剔除和合并，"
            "生成一份全新的记忆内容。\n步骤 3 [落盘]：调用 `write` 或 `edit` 工具，"
            "将整理后全新的 Markdown 内容覆盖写入到 `MEMORY.md` 中（请保持清晰的层级与列表结构）。\n"
            "步骤 4 [苏醒汇报]：从梦境中苏醒后，在对话中向我简短汇报：1) 新增/沉淀了哪些核心记忆；2) 修正/删除了哪些过期内容。"
        ),
        "en": (
            "Enter dream state for memory optimization. Please act as a 'Dream "
            "Memory Organizer', read today's logs and existing long-term memory, "
            "extract high-value incremental information in your dream state, "
            "deduplicate and merge, and ultimately overwrite `MEMORY.md`. Ensure "
            "the long-term memory file remains up-to-date, concise, and "
            "non-redundant.\n\n[Dream Optimization Principles]\n1. Extreme "
            "Minimalism: Strictly forbid recording daily routines, "
            "specific bug-fix details, or one-off tasks. Retain ONLY 'core"
            " business decisions', 'confirmed user preferences', and "
            "'high-value reusable experiences'.\n2. State Overwrite: If a"
            " state change is detected (e.g., tech stack changes, config "
            "updates), you MUST replace the old state with the new one. "
            "Contradictory old and new information must not coexist.\n3. "
            "Inductive Consolidation: Proactively distill and merge "
            "fragmented, similar rules into highly universal, independent"
            " entries.\n4. Deprecation: Proactively delete hypotheses "
            "that have been proven false or outdated entries that no "
            "longer apply.\n\n[Dream Execution Steps]\nStep 1 [Load]: Invoke "
            "the `read` tool to read `MEMORY.md` in the root directory "
            "and today's log file `memory/YYYY-MM-DD.md`.\nStep 2 "
            "[Dream Purification]: Compare the old and new content in your "
            "dream state. Strictly follow the [Dream Optimization Principles] "
            "to deduplicate, replace, remove, and merge, generating "
            "entirely new memory content.\nStep 3 [Save]: Invoke the "
            "`write` or `edit` tool to overwrite the newly organized "
            "Markdown content into `MEMORY.md` (maintain clear "
            "hierarchy and list structures).\nStep 4 [Awake Report]: After "
            "waking from your dream, briefly report to me in the chat: "
            "1) What core memories were newly added/consolidated; "
            "2) What outdated content was corrected/deleted."
        ),
    }
    return prompts.get(language, prompts["en"])


# pylint: disable=unused-argument
async def run_dream_once(
    *,
    runner: Any,
    channel_manager: Any,
    agent_id: Optional[str] = None,
    workspace_dir: Optional[Path] = None,
) -> None:
    """
    Run one dream-based memory optimization: execute dream task as
    agent query.

    Args:
        runner: Agent runner instance
        channel_manager: Channel manager instance
        agent_id: Agent ID for loading config and determining language
        workspace_dir: Workspace directory for potential future use
    """
    logger.info("running dream-based memory optimization")
    # Determine language based on agent config
    language = "zh"
    if agent_id:
        try:
            agent_config = load_agent_config(agent_id)
            language = getattr(agent_config, "language", "zh")
        except Exception:
            language = "zh"

    # Build the dream prompt
    query_text = _get_dream_prompt(language)

    if not query_text.strip():
        logger.debug("dream optimization skipped: empty query")
        return

    # Build request: single user message with query text
    req: Dict[str, Any] = {
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": query_text}],
            },
        ],
        "session_id": "main",
        "user_id": "main",
    }

    # For dream optimization, we typically don't dispatch to channels
    # Just run the agent task silently
    async def _run_only() -> None:
        async for _ in runner.stream_query(req):
            pass

    try:
        await asyncio.wait_for(_run_only(), timeout=300)  # 5 minutes timeout
        logger.info("dream-based memory optimization completed successfully")
    except asyncio.TimeoutError:
        logger.warning("dream-based memory optimization timed out")
    except Exception as e:
        logger.error("dream-based memory optimization failed: %s", repr(e))
        raise