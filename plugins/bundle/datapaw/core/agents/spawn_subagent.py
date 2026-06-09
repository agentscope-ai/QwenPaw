# -*- coding: utf-8 -*-
"""In-process ``spawn_subagent`` tool for DataPaw parallel sub-agent execution.

Creates a lightweight ``ReActAgent`` inside the same process, sharing the
main agent's ``msg_queue`` for streaming output.  Multiple invocations in
a single reasoning round run concurrently via ``asyncio.gather`` (requires
``parallel_tool_calls=True`` on the main agent).

The tool **does not accept ``node_id``** — the current ``in_progress``
node is read automatically from ``RuntimeStateManager``.  Sub-agents are
unaware of the DAG; they only see their task and context.

Message routing: each concurrent ``spawn_subagent`` call gets a unique
``tool_call_id`` from the framework, used downstream by
``adapt_agentscope_message_stream`` and the frontend to separate streams.
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
import uuid
from typing import (
    Any,
    AsyncGenerator,
    Callable,
    Dict,
    List,
    Optional,
    TYPE_CHECKING,
)

from agentscope.agent import ReActAgent
from agentscope.message import Msg, TextBlock
from agentscope.tool import Toolkit, ToolResponse

if TYPE_CHECKING:
    from ..orchestration.state import RuntimeStateManager

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 300
MAX_ITERS = 15
MAX_CONCURRENT = 4
MAX_TOTAL_SPAWNS = 20


def _build_sub_prompt(
    task: str,
    context: str,
    upstream_outputs: Dict[str, str],
) -> str:
    upstream_section = "\n".join(
        f"- {nid}: {out}" for nid, out in upstream_outputs.items()
    ) if upstream_outputs else "无（根节点）"

    return (
        "你是一个任务执行器。精确完成指定任务。\n\n"
        f"## 你的任务\n{task}\n\n"
        f"## 上下文\n{context or '无额外上下文。'}\n\n"
        f"## 上游信息\n{upstream_section}\n\n"
        "## 规则\n"
        "- 完整执行任务\n"
        "- 遇到无法解决的错误时描述问题并停止\n\n"
        "## 输出要求\n"
        "任务完成后，你的最终回答必须是结构化摘要，格式：\n"
        "- **结论**：说明任务结果（做了什么、数据概况、关键发现）\n"
        "- **产出文件**：列出所有生成的文件路径\n"
        "- **异常**：如有问题或部分失败，在此说明；无异常则省略\n"
        "不要输出中间过程的详细日志。\n"
    )


def _should_stream(msg: Msg) -> bool:
    """Thinking / assistant text streams immediately; tool msgs are batched."""
    return msg.role == "assistant"


def _is_tool_call(msg: Msg) -> bool:
    """Check if the message contains a tool_use block."""
    if not hasattr(msg, "content") or not isinstance(msg.content, list):
        return False
    return any(
        isinstance(block, dict) and block.get("type") == "tool_use"
        for block in msg.content
    )


def _extract_text(msg: Msg) -> str:
    parts: list[str] = []
    if msg.role == "assistant":
        thought = getattr(msg, "thought", None)
        if thought:
            parts.append(str(thought))
        content = msg.content
        if isinstance(content, str) and content:
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "thinking" and block.get("text"):
                        parts.append(str(block["text"]))
                    elif block.get("type") == "text" and block.get("text"):
                        parts.append(str(block["text"]))
                elif isinstance(block, str) and block:
                    parts.append(block)
    elif msg.role == "system":
        content = msg.content
        if isinstance(content, str) and content:
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    output = block.get("output")
                    if isinstance(output, list):
                        for o in output:
                            if isinstance(o, dict) and o.get("text"):
                                parts.append(str(o["text"]))
                    elif isinstance(output, str) and output:
                        parts.append(output)
                    elif block.get("type") == "text" and block.get("text"):
                        parts.append(str(block["text"]))
    return "\n".join(parts)


def _extract_tool_call_info(msg: Msg) -> dict:
    """Extract tool_use block info from an assistant message."""
    if isinstance(msg.content, list):
        for block in msg.content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                return {
                    "name": block.get("name", "tool"),
                    "input": block.get("input", {}),
                }
    return {"name": "tool", "input": {}}


SUPPORTED_ROLES = ("data_fetcher",)


def make_spawn_subagent_fn(
    *,
    runtime_state: "RuntimeStateManager",
    get_model_and_formatter: Callable,
    get_tools_for_role: Callable[[str], List[Any]],
    get_skill_dirs_for_role: Callable[[str], List[str]],
) -> Callable[..., AsyncGenerator[ToolResponse, None]]:
    """Build the ``spawn_subagent`` closure capturing runtime dependencies.

    Args:
        runtime_state: The ``RuntimeStateManager`` (``plan_notebook``).
        get_model_and_formatter: A callable returning ``(model, formatter)``.
        get_tools_for_role: A callable that takes a role name and returns
            the list of tool functions for that role.
        get_skill_dirs_for_role: A callable that takes a role name and returns
            the list of skill directory paths for that role.
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    spawn_count = 0

    async def spawn_subagent(
        task: str,
        role: str = "data_fetcher",
        context: str = "",
    ) -> AsyncGenerator[ToolResponse, None]:
        """Spawn an in-process sub-agent to execute a task.

        Multiple calls in a single reasoning round run concurrently.
        Does not change DAG node state — call finish_subtask separately.
        Automatically associates with the current in_progress node.

        Args:
            task: The specific task instruction for the sub-agent.
            role: The sub-agent role, determining its available tools.
                Currently supported: 'data_fetcher'.
            context: Optional context (upstream results, constraints, etc.).

        Yields:
            ToolResponse: Streaming output from the sub-agent.
        """
        nonlocal spawn_count

        if spawn_count >= MAX_TOTAL_SPAWNS:
            yield ToolResponse(
                content=[TextBlock(
                    type="text",
                    text=f"已达 spawn 上限 ({MAX_TOTAL_SPAWNS})",
                )],
                is_last=True,
            )
            return

        if role not in SUPPORTED_ROLES:
            yield ToolResponse(
                content=[TextBlock(
                    type="text",
                    text=(
                        f"不支持的 role: '{role}'。"
                        f"当前支持: {SUPPORTED_ROLES}"
                    ),
                )],
                is_last=True,
            )
            return

        async with semaphore:
            spawn_count += 1

            current_node = runtime_state.get_current_in_progress_node()
            node_id = current_node.node_id if current_node else None
            upstream_outputs = (
                runtime_state.get_upstream_outputs(node_id)
                if node_id else {}
            )

            try:
                model, formatter = get_model_and_formatter()
            except Exception as exc:
                logger.warning(
                    "spawn_subagent: failed to create model: %s",
                    exc,
                    exc_info=True,
                )
                yield ToolResponse(
                    content=[TextBlock(
                        type="text",
                        text=f"Sub-agent 模型创建失败: {exc}",
                    )],
                    is_last=True,
                )
                return

            sub_toolkit = Toolkit()
            for tool_fn in get_tools_for_role(role):
                try:
                    sub_toolkit.register_tool_function(
                        tool_fn,
                        namesake_strategy="skip",
                    )
                except Exception:
                    logger.debug(
                        "spawn_subagent: skipping tool %r",
                        getattr(tool_fn, "__name__", repr(tool_fn)),
                        exc_info=True,
                    )

            for skill_dir in get_skill_dirs_for_role(role):
                try:
                    sub_toolkit.register_agent_skill(skill_dir)
                except Exception:
                    logger.debug(
                        "spawn_subagent: skipping skill %r",
                        skill_dir,
                        exc_info=True,
                    )

            sys_prompt = _build_sub_prompt(task, context, upstream_outputs)
            skill_prompt = sub_toolkit.get_agent_skill_prompt()
            if skill_prompt:
                sys_prompt = sys_prompt + "\n" + skill_prompt

            agent_name = f"subagent-{role}-{node_id or 'free'}-{uuid.uuid4().hex[:4]}"
            sub_agent = ReActAgent(
                name=agent_name,
                model=model,
                formatter=formatter,
                sys_prompt=sys_prompt,
                toolkit=sub_toolkit,
                max_iters=MAX_ITERS,
                parallel_tool_calls=False,
            )

            task_msg = Msg("user", content=task, role="user")

            try:
                _deadline = asyncio.get_event_loop().time() + TIMEOUT_SECONDS
                sub_queue: asyncio.Queue = asyncio.Queue()
                sub_agent.set_msg_queue_enabled(True, sub_queue)
                reply_task = asyncio.create_task(sub_agent(task_msg))

                # Accumulate complete execution log for trace
                trace_log: list[str] = []

                while True:
                    remaining = _deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        reply_task.cancel()
                        raise asyncio.TimeoutError()

                    try:
                        queue_item = await asyncio.wait_for(
                            sub_queue.get(),
                            timeout=min(1.0, remaining),
                        )
                    except asyncio.TimeoutError:
                        if reply_task.done():
                            break
                        continue

                    # AgentBase.print puts (msg, last, speech) 3-tuples
                    msg, is_last = queue_item[0], queue_item[1]

                    if _should_stream(msg) and not _is_tool_call(msg):
                        # thinking / text → 流式传回
                        text = _extract_text(msg)
                        if text:
                            yield ToolResponse(
                                content=[TextBlock(
                                    type="text", text=text,
                                )],
                                stream=True,
                                is_last=False,
                            )
                            if is_last:
                                trace_log.append(text)
                    elif (
                        msg.role == "assistant" and _is_tool_call(msg)
                    ):
                        # tool_call → 整块输出（含 input）
                        info = _extract_tool_call_info(msg)
                        try:
                            input_str = _json.dumps(
                                info["input"], ensure_ascii=False,
                            )
                        except (TypeError, ValueError):
                            input_str = str(info["input"])
                        tool_call_text = (
                            f"[tool_call] {info['name']}({input_str})"
                        )
                        yield ToolResponse(
                            content=[TextBlock(
                                type="text",
                                text=tool_call_text,
                            )],
                            metadata={
                                "type": "tool_call",
                                "tool_name": info["name"],
                                "tool_input": info["input"],
                            },
                            stream=True,
                            is_last=False,
                        )
                        trace_log.append(tool_call_text)
                    elif msg.role == "system":
                        # tool_result → 整块输出
                        text = _extract_text(msg)
                        if text:
                            yield ToolResponse(
                                content=[TextBlock(
                                    type="text", text=text,
                                )],
                                metadata={"type": "tool_result"},
                                stream=True,
                                is_last=False,
                            )
                            trace_log.append(f"[tool_result] {text}")

                    if reply_task.done() and sub_queue.empty():
                        break

                result_msg = await reply_task

            except asyncio.TimeoutError:
                yield ToolResponse(
                    content=[TextBlock(
                        type="text",
                        text=f"Sub-agent 超时（{TIMEOUT_SECONDS}s）",
                    )],
                    is_last=True,
                )
                return
            except Exception as exc:
                logger.warning(
                    "spawn_subagent: sub-agent execution failed: %s",
                    exc,
                    exc_info=True,
                )
                yield ToolResponse(
                    content=[TextBlock(
                        type="text",
                        text=f"Sub-agent 异常: {exc}",
                    )],
                    is_last=True,
                )
                return

            # Final frame: sub-agent's structured summary (from reply())
            summary = (
                _extract_text(result_msg) if result_msg else "(no output)"
            )
            yield ToolResponse(
                content=[TextBlock(type="text", text=summary)],
                is_last=True,
            )

    return spawn_subagent
