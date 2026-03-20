# -*- coding: utf-8 -*-
"""Tool-guard mixin for CoPawAgent.

Provides ``_acting`` and ``_reasoning`` overrides that intercept
sensitive tool calls before execution, implementing the deny /
guard / approve flow.

Separated from ``react_agent.py`` to keep the main agent class
focused on lifecycle management.
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
import uuid as _uuid
from typing import Any, Literal

from agentscope.message import Msg

from ..security.tool_guard.models import TOOL_GUARD_DENIED_MARK

logger = logging.getLogger(__name__)


class ToolGuardMixin:
    """Mixin that adds tool-guard interception to a ReActAgent.

    At runtime this class is always combined with
    ``agentscope.agent.ReActAgent`` via MRO, so ``super()._acting``
    and ``super()._reasoning`` resolve to the concrete agent methods.
    """

    # ------------------------------------------------------------------
    # Lazy initialisation
    # ------------------------------------------------------------------

    def _init_tool_guard(self) -> None:
        """Lazy-init tool-guard components (called once)."""
        from copaw.security.tool_guard.engine import get_guard_engine
        from copaw.app.approvals import get_approval_service

        self._tool_guard_engine = get_guard_engine()
        self._tool_guard_approval_service = get_approval_service()
        self._tool_guard_pending_info: dict | None = None
        self._tool_guard_lock = asyncio.Lock()

    def _ensure_tool_guard(self) -> None:
        if not hasattr(self, "_tool_guard_engine"):
            self._init_tool_guard()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _should_require_approval(self) -> bool:
        """``True`` when a ``session_id`` is available for approval."""
        return bool(self._request_context.get("session_id"))

    def _last_tool_response_is_denied(self) -> bool:
        """Check if the last message is a guard-denied tool result."""
        if not self.memory.content:
            return False
        msg, marks = self.memory.content[-1]
        return TOOL_GUARD_DENIED_MARK in marks and msg.role == "system"

    def _extract_sibling_tool_calls(self) -> list[dict[str, Any]]:
        """Extract all tool_use blocks from the last assistant message."""
        for msg, _ in reversed(self.memory.content):
            if msg.role == "assistant":
                return [
                    {
                        "id": b.get("id", ""),
                        "name": b.get("name", ""),
                        "input": b.get("input", {}),
                    }
                    for b in msg.get_content_blocks("tool_use")
                ]
        return []

    def _tool_result_exists_in_memory(self, tool_use_id: str) -> bool:
        """``True`` when a non-denied tool_result for *tool_use_id* exists."""
        for msg, marks in self.memory.content:
            if msg.role != "system" or TOOL_GUARD_DENIED_MARK in marks:
                continue
            for block in msg.get_content_blocks("tool_result"):
                if block.get("id") == tool_use_id:
                    return True
        return False

    def _pop_forced_tool_call(self) -> dict[str, Any] | None:
        """Pop and validate a forced tool call injected by the runner."""
        raw = self._request_context.pop("forced_tool_call_json", "")
        if not raw:
            return None

        try:
            tool_call = _json.loads(str(raw))
        except Exception:
            logger.warning(
                "Tool guard: invalid forced tool call payload",
                exc_info=True,
            )
            return None

        if not isinstance(tool_call, dict):
            logger.warning(
                "Tool guard: forced tool call payload is not a dict",
            )
            return None

        tool_name = tool_call.get("name")
        if not isinstance(tool_name, str) or not tool_name:
            logger.warning(
                "Tool guard: forced tool call missing valid name",
            )
            return None

        tool_input = tool_call.get("input", {})
        if not isinstance(tool_input, dict):
            logger.warning(
                "Tool guard: forced tool call input is not a dict",
            )
            return None

        tool_id = tool_call.get("id")
        if not isinstance(tool_id, str) or not tool_id:
            tool_id = f"approved-{_uuid.uuid4().hex[:12]}"

        siblings = tool_call.pop("_sibling_tool_calls", None)
        remaining = tool_call.pop("_remaining_queue", None)

        if remaining is not None and isinstance(remaining, list):
            self._tool_guard_replay_queue = remaining
        elif siblings is not None and isinstance(siblings, list):
            found = False
            queue: list[dict[str, Any]] = []
            for s in siblings:
                if not found and s.get("id") == tool_id:
                    found = True
                    continue
                if found:
                    queue.append(s)
            self._tool_guard_replay_queue = queue
        else:
            self._tool_guard_replay_queue = []

        return {
            "id": tool_id,
            "name": tool_name,
            "input": tool_input,
        }

    async def _get_pending_info_for_display(self) -> dict[str, Any]:
        """Return pending tool info aligned with approval queue head."""
        fallback = getattr(self, "_tool_guard_pending_info", None) or {}
        session_id = str(self._request_context.get("session_id") or "")
        if not session_id:
            return fallback

        try:
            pending = await self._tool_guard_approval_service.get_pending_by_session(
                session_id,
            )
        except Exception:
            logger.warning(
                "Tool guard: failed to read pending queue head",
                exc_info=True,
            )
            return fallback

        if pending is None:
            return fallback

        tool_input: dict[str, Any] = {}
        extra = pending.extra if isinstance(pending.extra, dict) else {}
        tool_call = extra.get("tool_call") if isinstance(extra, dict) else {}
        if isinstance(tool_call, dict) and isinstance(
            tool_call.get("input"),
            dict,
        ):
            tool_input = tool_call["input"]

        return {
            "tool_name": pending.tool_name or fallback.get("tool_name", "unknown"),
            "tool_input": tool_input or fallback.get("tool_input", {}),
        }

    @staticmethod
    def _extract_tool_result_text(memory_content: list) -> str:
        """Read the tool result text from the last system message."""
        if not memory_content:
            return ""
        last_msg, _ = memory_content[-1]
        if last_msg.role != "system":
            return ""
        for block in (last_msg.content or []):
            if not isinstance(block, dict):
                block = dict(block)
            if block.get("type") == "tool_result":
                output = block.get("output", "")
                if isinstance(output, list):
                    parts = [
                        item.get("text", "")
                        for item in output
                        if isinstance(item, dict)
                    ]
                    return "\n".join(p for p in parts if p)
                if isinstance(output, str):
                    return output
        return ""

    async def _cleanup_tool_guard_denied_messages(
        self,
        include_denial_response: bool = True,
    ) -> None:
        """Remove tool-guard denied messages from memory.

        Finds messages marked with ``TOOL_GUARD_DENIED_MARK`` and
        removes them.  When *include_denial_response* is ``True``,
        also removes the assistant message immediately following the
        last marked message (the LLM's denial explanation).
        """
        ids_to_delete: list[str] = []
        last_marked_idx = -1

        for i, (msg, marks) in enumerate(self.memory.content):
            if TOOL_GUARD_DENIED_MARK in marks:
                ids_to_delete.append(msg.id)
                last_marked_idx = i

        if (
            include_denial_response
            and last_marked_idx >= 0
            and last_marked_idx + 1 < len(self.memory.content)
        ):
            next_msg, _ = self.memory.content[last_marked_idx + 1]
            if next_msg.role == "assistant":
                ids_to_delete.append(next_msg.id)

        if ids_to_delete:
            removed = await self.memory.delete(ids_to_delete)
            logger.info(
                "Tool guard: cleaned up %d denied message(s)",
                removed,
            )

    # ------------------------------------------------------------------
    # _acting override
    # ------------------------------------------------------------------

    async def _acting(self, tool_call) -> dict | None:  # noqa: C901
        """Intercept sensitive tool calls before execution.

        1. If tool is in *denied_tools*, auto-deny unconditionally.
        2. Check for a one-shot pre-approval.
        3. If tool is in the guarded scope, run ToolGuardEngine.
        4. If findings exist, enter the approval flow.
        5. Otherwise, delegate to ``super()._acting``.

        The guard decision block is serialised via ``_tool_guard_lock``
        so that ``parallel_tool_calls=True`` does not cause state races
        on shared mixin attributes.  Non-guarded tool execution runs
        outside the lock for true parallelism.
        """
        self._ensure_tool_guard()

        async with self._tool_guard_lock:
            engine = self._tool_guard_engine
            tool_name: str = tool_call.get("name", "")
            tool_input: dict = tool_call.get("input", {})

            try:
                if tool_name and engine.enabled:
                    if engine.is_denied(tool_name):
                        logger.warning(
                            "Tool guard: tool '%s' is in the denied "
                            "set, auto-denying",
                            tool_name,
                        )
                        result = engine.guard(tool_name, tool_input)
                        return await self._acting_auto_denied(
                            tool_call,
                            tool_name,
                            result,
                        )

                    if engine.is_guarded(tool_name):
                        session_id = str(
                            self._request_context.get("session_id") or "",
                        )
                        if session_id:
                            svc = self._tool_guard_approval_service
                            consumed = await svc.consume_approval(
                                session_id,
                                tool_name,
                                tool_params=tool_input,
                            )
                            if consumed:
                                logger.info(
                                    "Tool guard: pre-approved '%s' "
                                    "(session %s), skipping",
                                    tool_name,
                                    session_id[:8],
                                )
                                self._tool_guard_pending_info = None
                                cleanup = (
                                    self._cleanup_tool_guard_denied_messages
                                )
                                await cleanup(
                                    include_denial_response=True,
                                )
                                result = await super()._acting(  # type: ignore[misc]
                                    tool_call,
                                )
                                if getattr(
                                    self,
                                    "_tool_guard_forced_replay_active",
                                    False,
                                ):
                                    self._tool_guard_forced_replay_active = (
                                        False
                                    )
                                    self._tool_guard_replay_done = {
                                        "tool_name": tool_name,
                                        "tool_input": tool_input,
                                        "remaining_queue": getattr(
                                            self,
                                            "_tool_guard_replay_queue",
                                            [],
                                        ),
                                    }
                                return result

                        result = engine.guard(tool_name, tool_input)
                        if result is not None and result.findings:
                            from copaw.security.tool_guard.utils import (
                                log_findings,
                            )

                            log_findings(tool_name, result)

                            if self._should_require_approval():
                                return await self._acting_with_approval(
                                    tool_call,
                                    tool_name,
                                    result,
                                )
            except Exception as exc:
                logger.warning(
                    "Tool guard check error (non-blocking): %s",
                    exc,
                    exc_info=True,
                )

        return await super()._acting(tool_call)  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Denied / Approval responses
    # ------------------------------------------------------------------

    async def _acting_auto_denied(
        self,
        tool_call: dict[str, Any],
        tool_name: str,
        guard_result=None,
    ) -> dict | None:
        """Auto-deny a tool call without offering approval."""
        from agentscope.message import ToolResultBlock
        from copaw.security.tool_guard.approval import (
            format_findings_summary,
        )

        if guard_result is not None and guard_result.findings:
            findings_text = format_findings_summary(guard_result)
            severity = guard_result.max_severity.value
            count = str(guard_result.findings_count)
        else:
            findings_text = "- Tool is in the denied list / 工具在禁止列表中"
            severity = "DENIED"
            count = "N/A"

        denied_text = (
            f"⛔ **Tool Blocked / 工具已拦截**\n\n"
            f"- Tool / 工具: `{tool_name}`\n"
            f"- Severity / 严重性: `{severity}`\n"
            f"- Findings / 发现: `{count}`\n\n"
            f"{findings_text}\n\n"
            f"This tool is blocked and cannot be approved.\n"
            f"该工具已被禁止，无法批准执行。"
        )

        tool_res_msg = Msg(
            "system",
            [
                ToolResultBlock(
                    type="tool_result",
                    id=tool_call["id"],
                    name=tool_name,
                    output=[
                        {"type": "text", "text": denied_text},
                    ],
                ),
            ],
            "system",
        )

        await self.print(tool_res_msg, True)
        await self.memory.add(tool_res_msg)
        return None

    async def _acting_with_approval(
        self,
        tool_call: dict[str, Any],
        tool_name: str,
        guard_result,
    ) -> dict | None:
        """Deny the tool call and record a pending approval."""
        from agentscope.message import ToolResultBlock
        from copaw.security.tool_guard.approval import (
            format_findings_summary,
        )

        channel = str(self._request_context.get("channel") or "")

        for msg, marks in reversed(self.memory.content):
            if msg.role == "assistant":
                if TOOL_GUARD_DENIED_MARK not in marks:
                    marks.append(TOOL_GUARD_DENIED_MARK)
                break

        extra: dict[str, Any] = {"tool_call": tool_call}

        replay_queue = getattr(self, "_tool_guard_replay_queue", None)
        if replay_queue is not None:
            extra["remaining_queue"] = list(replay_queue)
            self._tool_guard_replay_queue = None
        else:
            siblings = self._extract_sibling_tool_calls()
            if siblings:
                extra["sibling_tool_calls"] = siblings

        await self._tool_guard_approval_service.create_pending(
            session_id=str(
                self._request_context.get("session_id") or "",
            ),
            user_id=str(
                self._request_context.get("user_id") or "",
            ),
            channel=channel,
            tool_name=tool_name,
            result=guard_result,
            extra=extra,
        )

        self._tool_guard_pending_info = {
            "tool_name": tool_name,
            "tool_input": tool_call.get("input", {}),
        }

        findings_text = format_findings_summary(guard_result)
        denied_text = (
            f"⚠️ **Risk Detected / 检测到风险**\n\n"
            f"- Tool / 工具: `{tool_name}`\n"
            f"- Severity / 严重性: "
            f"`{guard_result.max_severity.value}`\n"
            f"- Findings / 发现: "
            f"`{guard_result.findings_count}`\n\n"
            f"{findings_text}\n\n"
            f"Type `/approve` to approve, "
            f"or send any message to deny.\n"
            f"输入 `/approve` 批准执行，或发送任意消息拒绝。"
        )

        tool_res_msg = Msg(
            "system",
            [
                ToolResultBlock(
                    type="tool_result",
                    id=tool_call["id"],
                    name=tool_name,
                    output=[
                        {"type": "text", "text": denied_text},
                    ],
                ),
            ],
            "system",
        )

        await self.print(tool_res_msg, True)
        await self.memory.add(
            tool_res_msg,
            marks=TOOL_GUARD_DENIED_MARK,
        )
        return None

    # ------------------------------------------------------------------
    # _reasoning override (guard-aware)
    # ------------------------------------------------------------------

    async def _reasoning(  # noqa: C901
        self,
        tool_choice: (Literal["auto", "none", "required"] | None) = None,
    ) -> Msg:
        """Short-circuit reasoning when awaiting guard approval.

        After a forced approved replay completes its ``_acting`` cycle,
        this method either continues with the next queued sibling tool
        call (returning a ``tool_use`` message) or returns a text-only
        completion message so the ``ReActAgent.reply`` loop exits
        naturally.
        """
        replay_info = getattr(self, "_tool_guard_replay_done", None)
        if replay_info:
            self._tool_guard_replay_done = None
            tool_name = replay_info.get("tool_name", "unknown")
            tool_input = replay_info.get("tool_input", {})
            remaining_queue: list[dict[str, Any]] = list(
                replay_info.get("remaining_queue") or [],
            )

            params_text = _json.dumps(
                tool_input,
                ensure_ascii=False,
                indent=2,
            )
            result_text = self._extract_tool_result_text(
                self.memory.content,
            )
            result_preview = result_text[:500]
            if len(result_text) > 500:
                result_preview += "..."

            completion_text = (
                f"✅ **Approved tool executed / 已批准工具执行完成**\n\n"
                f"- Tool / 工具: `{tool_name}`\n"
                f"- Parameters / 参数:\n"
                f"```json\n{params_text}\n```\n"
                f"- Result / 结果:\n"
                f"```\n{result_preview}\n```"
            )

            filtered: list[dict[str, Any]] = []
            for tc in remaining_queue:
                tc_id = tc.get("id", "")
                if self._tool_result_exists_in_memory(tc_id):
                    continue
                filtered.append(tc)
            remaining_queue = filtered

            if remaining_queue:
                from agentscope.message import ToolUseBlock, TextBlock

                next_tc = remaining_queue[0]
                rest = remaining_queue[1:]
                self._tool_guard_replay_queue = rest

                next_id = next_tc.get("id") or (
                    f"queued-{_uuid.uuid4().hex[:12]}"
                )

                status = (
                    f"{completion_text}\n\n"
                    f"⏳ **{len(remaining_queue)} more tool call(s) "
                    f"remaining / 还有 {len(remaining_queue)} 个工具"
                    f"调用待执行**"
                )

                self._tool_guard_forced_replay_active = True
                msg = Msg(
                    self.name,
                    [
                        TextBlock(type="text", text=status),
                        ToolUseBlock(
                            type="tool_use",
                            id=next_id,
                            name=next_tc.get("name", "unknown"),
                            input=next_tc.get("input", {}),
                        ),
                    ],
                    "assistant",
                )
                await self.print(msg, True)
                await self.memory.add(msg)
                return msg

            msg = Msg(
                self.name,
                completion_text,
                "assistant",
            )
            await self.print(msg, True)
            await self.memory.add(msg)
            return msg

        forced_tool_call = self._pop_forced_tool_call()
        if forced_tool_call is not None:
            try:
                from agentscope.message import ToolUseBlock

                self._tool_guard_forced_replay_active = True
                msg = Msg(
                    self.name,
                    [
                        ToolUseBlock(
                            type="tool_use",
                            id=forced_tool_call["id"],
                            name=forced_tool_call["name"],
                            input=forced_tool_call["input"],
                        ),
                    ],
                    "assistant",
                )
                await self.print(msg, True)
                await self.memory.add(msg)
                return msg
            except Exception as exc:
                self._tool_guard_forced_replay_active = False
                logger.warning(
                    "Tool guard: forced tool replay failed, "
                    "falling back to normal reasoning: %s",
                    exc,
                    exc_info=True,
                )

        if self._last_tool_response_is_denied():
            pending = await self._get_pending_info_for_display()
            tool_name = pending.get("tool_name", "unknown")
            tool_input = pending.get("tool_input", {})

            params_text = _json.dumps(
                tool_input,
                ensure_ascii=False,
                indent=2,
            )
            msg = Msg(
                self.name,
                "⏳ Waiting for approval / 等待审批\n\n"
                f"- Tool / 工具: `{tool_name}`\n"
                f"- Parameters / 参数:\n"
                f"```json\n{params_text}\n```\n\n"
                "Type `/approve` to approve, "
                "or send any message to deny.\n"
                "输入 `/approve` 批准执行，"
                "或发送任意消息拒绝。",
                "assistant",
            )
            await self.print(msg, True)
            await self.memory.add(msg)
            return msg

        return await super()._reasoning(  # type: ignore[misc]
            tool_choice=tool_choice,
        )
