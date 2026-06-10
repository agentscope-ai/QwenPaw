# -*- coding: utf-8 -*-
"""A2A call tool: send a message to a remote A2A Agent.

Supports resolution by alias (reading from per-agent a2a_config.json)
or by direct URL.  When using alias, auth config is automatically
applied from the stored registration.

The tool is an ``AsyncGenerator`` that yields intermediate
``ToolResponse(stream=True, is_last=False)`` chunks as SSE events
arrive from the remote agent, so the QwenPaw frontend can render
incremental progress in real time via the tool renderer.  The final
chunk carries ``is_last=True``.
"""

import json
import logging
from collections.abc import AsyncGenerator

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

logger = logging.getLogger("qwenpaw").getChild(
    __name__.replace("plugin_cloudpaw.", ""),
)


async def a2a_call(  # pylint: disable=too-many-branches,too-many-statements
    message: str,
    agent_alias: str = "",
    agent_url: str = "",
    context_id: str = "",
) -> AsyncGenerator[ToolResponse, None]:
    """向远程 A2A Agent 发送消息并获取响应。

    通过 ``agent_alias``（已注册的别名）或 ``agent_url``（URL）指定目标 Agent。
    使用别名时自动应用已注册的认证配置。

    Args:
        message:     发送给远程 Agent 的文本消息
        agent_alias: 已注册的远程 Agent 别名（优先使用，通过 a2a_list 查看可用别名）
        agent_url:   远程 A2A Agent 的基础 URL（alias 为空时使用）
        context_id:  可选，会话上下文 ID（多轮对话时传入上次返回的 contextId）

    Yields:
        ToolResponse: 远程 Agent 的流式响应，包含：
        - response_text: Agent 回复的文本内容（累积）
        - task_id: 任务 ID（如有）
        - context_id: 会话上下文 ID（用于多轮对话）
        - task_state: 任务最终状态
        - event_count: 收到的事件总数
    """
    from modules.a2a.client_manager import get_a2a_manager

    try:
        from modules.a2a.call_stream import (
            finish_stream,
            get_stream,
            start_stream,
        )

        stream_queue = get_stream()
        if stream_queue is None:
            stream_queue = start_stream()
        _has_call_stream = True
    except ImportError:
        stream_queue = None
        _has_call_stream = False

    manager = get_a2a_manager()
    resolved_url = agent_url
    auth_type = ""
    auth_token = ""

    def _error_response(error_msg: str) -> ToolResponse:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=json.dumps(
                        {"error": error_msg, "task_state": "error"},
                        ensure_ascii=False,
                    ),
                ),
            ],
            stream=True,
            is_last=True,
        )

    if agent_alias:
        from .a2a_config_helper import resolve_agent_by_alias

        reg = resolve_agent_by_alias(agent_alias)
        if not reg:
            if _has_call_stream:
                finish_stream()
            yield _error_response(
                f"未找到别名为 '{agent_alias}' 的已注册 A2A Agent。"
                f"请先通过 a2a_list 查看可用的 Agent。",
            )
            return
        resolved_url = reg["url"]
        auth_type = reg.get("auth_type", "")
        auth_token = reg.get("auth_token", "")
        gateway_config = reg.get("gateway_config")

        card_info = await manager.get_card_info(resolved_url)
        if not card_info or card_info.get("status") != "connected":
            try:
                await manager.connect(
                    agent_url=resolved_url,
                    auth_type=auth_type,
                    auth_token=auth_token,
                    gateway_config=gateway_config,
                )
            except Exception as e:
                if _has_call_stream:
                    finish_stream()
                yield _error_response(
                    f"连接 '{agent_alias}' ({resolved_url}) 失败: {e}",
                )
                return

    if not resolved_url:
        if _has_call_stream:
            finish_stream()
        yield _error_response("必须提供 agent_alias 或 agent_url 之一。")
        return

    events: list[dict] = []
    try:
        logger.info(
            "A2A call started: alias=%s, url=%s, message=%s",
            agent_alias or "(direct)",
            resolved_url,
            message[:100],
        )

        tracker = _StepTracker()
        last_snapshot = ""

        async for event in manager.send_message(
            agent_url=resolved_url,
            message=message,
            context_id=context_id,
            streaming=True,
        ):
            events.append(event)
            tracker.process(event)
            snapshot = json.dumps(
                tracker.snapshot(),
                ensure_ascii=False,
            )
            if snapshot != last_snapshot:
                last_snapshot = snapshot
                payload = {
                    "steps": tracker.snapshot(),
                    "task_state": "working",
                    "event_count": len(events),
                }
                if stream_queue is not None:
                    _push(stream_queue, payload)
                yield ToolResponse(
                    content=[
                        TextBlock(
                            type="text",
                            text=json.dumps(payload, ensure_ascii=False),
                        ),
                    ],
                    stream=True,
                    is_last=False,
                )

        result = _build_result(events, context_id)
        result["steps"] = tracker.snapshot()
        logger.info(
            "A2A call completed: events=%d, state=%s, text_len=%d",
            len(events),
            result.get("task_state"),
            len(result.get("response_text", "")),
        )

        if stream_queue is not None:
            _push(stream_queue, {**result, "final": True})

    except Exception as e:
        logger.exception("A2A call failed: %s — %s", resolved_url, e)
        result = {
            "response_text": "",
            "error": str(e),
            "task_id": "",
            "context_id": context_id,
            "task_state": "error",
            "event_count": len(events),
        }
        if stream_queue is not None:
            _push(stream_queue, {**result, "final": True})

    finally:
        if _has_call_stream:
            finish_stream()

    yield ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(result, ensure_ascii=False),
            ),
        ],
        stream=True,
        is_last=True,
    )


def _push(queue, data: dict) -> None:
    """Push data to the stream queue (non-blocking)."""
    try:
        queue.put_nowait(data)
    except Exception:
        pass


class _StepTracker:
    """Accumulates A2A SSE events into a structured list of UI steps.

    Step types:
    - thinking: LLM thinking tokens, accumulated into a single text block.
                Finalized (done=True) once a non-thinking event arrives.
    - tool_call: Remote agent tool invocation.
                 status cycles: running → done / error.
    - text: Agent response text (artifact / message).
    """

    def __init__(self) -> None:
        self._steps: list[dict] = []
        self._thinking_buf: list[str] = []
        self._active_tools: dict[str, int] = {}

    def process(  # pylint: disable=too-many-branches
        self,
        event: dict,
    ) -> None:
        ev_type = event.get("type", "")

        if ev_type == "status_update":
            su = event.get("statusUpdate", {})
            meta = su.get("metadata", {})
            msg_type = meta.get("message_type", "")

            if msg_type == "thinking":
                self._thinking_buf.append(meta.get("thinking", ""))
                self._ensure_thinking_step()
                return

            self._finalize_thinking()

            if msg_type == "tool_use":
                tool_id = meta.get("tool_use_id", "")
                name = meta.get("tool_name", "?")
                desc = (meta.get("tool_input") or {}).get("description", "")
                step = {
                    "type": "tool_call",
                    "name": name,
                    "status": "running",
                    "desc": desc,
                }
                self._steps.append(step)
                if tool_id:
                    self._active_tools[tool_id] = len(self._steps) - 1

            elif msg_type == "tool_result":
                tool_id = meta.get("tool_use_id", "")
                is_error = meta.get("is_error", False)
                idx = self._active_tools.pop(tool_id, None)
                if idx is not None and idx < len(self._steps):
                    self._steps[idx]["status"] = (
                        "error" if is_error else "done"
                    )
                else:
                    name = meta.get("tool_name", "?")
                    self._steps.append(
                        {
                            "type": "tool_call",
                            "name": name,
                            "status": "error" if is_error else "done",
                        },
                    )

            else:
                text = _extract_text_from_parts(
                    su.get("status", {}).get("message", {}).get("parts", []),
                )
                if text:
                    self._append_text(text)

        elif ev_type == "artifact_update":
            self._finalize_thinking()
            artifact = event.get("artifactUpdate", {}).get("artifact", {})
            text = _extract_text_from_parts(artifact.get("parts", []))
            if text:
                self._append_text(text)

        elif ev_type == "task":
            self._finalize_thinking()
            task_data = event.get("task", {})
            for artifact in task_data.get("artifacts", []):
                text = _extract_text_from_parts(artifact.get("parts", []))
                if text:
                    self._append_text(text)

        elif ev_type == "message":
            self._finalize_thinking()
            text = _extract_text_from_parts(
                event.get("message", {}).get("parts", []),
            )
            if text:
                self._append_text(text)

    def snapshot(self) -> list[dict]:
        steps = [s.copy() for s in self._steps]
        if self._thinking_buf:
            for s in steps:
                if s.get("type") == "thinking" and not s.get("done"):
                    s["text"] = "".join(self._thinking_buf)
                    break
        return steps

    def _ensure_thinking_step(self) -> None:
        if (
            not self._steps
            or self._steps[-1].get("type") != "thinking"
            or self._steps[-1].get("done")
        ):
            self._steps.append({"type": "thinking", "text": "", "done": False})

    def _finalize_thinking(self) -> None:
        if not self._thinking_buf:
            return
        text = "".join(self._thinking_buf)
        self._thinking_buf.clear()
        for s in reversed(self._steps):
            if s.get("type") == "thinking" and not s.get("done"):
                s["text"] = text
                s["done"] = True
                return

    def _append_text(self, text: str) -> None:
        if self._steps and self._steps[-1].get("type") == "text":
            self._steps[-1]["text"] += text
        else:
            self._steps.append({"type": "text", "text": text})


def _build_result(  # pylint: disable=too-many-branches,too-many-statements
    events: list[dict],
    initial_context_id: str,
) -> dict:
    """Build final result dict from all collected events."""
    artifact_texts: list[str] = []
    status_texts: list[str] = []
    final_task_id = ""
    final_context_id = initial_context_id
    final_state = ""

    for ev in events:
        ev_type = ev.get("type", "")

        if ev_type == "task":
            task_data = ev.get("task", {})
            if "id" in task_data:
                final_task_id = task_data["id"]
            if "contextId" in task_data:
                final_context_id = task_data["contextId"]
            status = task_data.get("status", {})
            if "state" in status:
                final_state = status["state"]
            msg = status.get("message", {})
            text = _extract_text_from_parts(msg.get("parts", []))
            if text:
                status_texts.append(text)
            for artifact in task_data.get("artifacts", []):
                text = _extract_text_from_parts(artifact.get("parts", []))
                if text:
                    artifact_texts.append(text)

        elif ev_type == "status_update":
            su = ev.get("statusUpdate", {})
            if "taskId" in su:
                final_task_id = su["taskId"]
            if "contextId" in su:
                final_context_id = su["contextId"]
            status = su.get("status", {})
            if "state" in status:
                final_state = status["state"]
            msg = status.get("message", {})
            text = _extract_text_from_parts(msg.get("parts", []))
            if text:
                status_texts.append(text)

        elif ev_type == "artifact_update":
            au = ev.get("artifactUpdate", {})
            if "taskId" in au:
                final_task_id = au["taskId"]
            if "contextId" in au:
                final_context_id = au["contextId"]
            artifact = au.get("artifact", {})
            text = _extract_text_from_parts(artifact.get("parts", []))
            if text:
                artifact_texts.append(text)

        elif ev_type == "message":
            msg = ev.get("message", {})
            text = _extract_text_from_parts(msg.get("parts", []))
            if text:
                artifact_texts.append(text)

    response_text = "".join(artifact_texts)
    if not response_text and status_texts:
        response_text = "\n".join(status_texts)
    if not response_text and final_state:
        response_text = f"[任务状态: {final_state}]"

    return {
        "response_text": response_text,
        "task_id": final_task_id,
        "context_id": final_context_id,
        "task_state": final_state,
        "event_count": len(events),
    }


def _extract_text_from_parts(parts: list) -> str:
    """Extract concatenated text from a list of A2A message parts."""
    texts = []
    for part in parts or []:
        if isinstance(part, dict) and "text" in part:
            texts.append(part["text"])
    return "".join(texts)
