# -*- coding: utf-8 -*-
"""Auto-poll middleware for mailbox and task board (low-noise P0).

Goals:
1) Protect main conversation (no imperative long injection text).
2) Collapse backlog by task/thread key, keep latest state.
3) Silence progress/general/done by default (unless urgent/blocker).
4) Use tail-note mode for non-urgent updates.
5) Recovery window emits one short notice (no history flood).
6) Urgent items deduplicated by key, sorted by priority.
7) Notice messages carry metadata so frontends can style as tail-notes.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from agentscope.message import Msg, TextBlock

logger = logging.getLogger(__name__)

# Base polling interval
_POLL_INTERVAL = 30
# Default agent on Feishu: poll slower to avoid interrupting chat
_FEISHU_DEFAULT_POLL_INTERVAL = 120
# If user just typed, skip injecting for this cooldown window
_FEISHU_DEFAULT_USER_GATE_SEC = 20
# Recovery reminder cooldown (emit once per window)
_RECOVERY_NOTICE_COOLDOWN_SEC = 300
# Suppress identical notice spam
_DUP_NOTICE_SUPPRESS_SEC = 120
# Cooldown after sending any notice (prevents rapid re-trigger)
_NOTICE_SEND_COOLDOWN_SEC = 60
# Max urgent items printed per round
_MAX_URGENT_LINES = 5
# Priority weight for sorting urgent items (lower = higher priority)
_URGENT_WEIGHT = {"blocker": 0, "blocked": 1, "urgent": 2, "high": 3, "default": 4}

# Low-signal kinds: silent by default
_DEFAULT_MUTED_KINDS = {"done", "progress", "general"}


class AutoPollMiddleware:
    """Pre-reasoning middleware that polls mailbox and task board."""

    def __init__(self, agent_id: str = "", workspace_dir: Optional[Path] = None):
        self._agent_id = agent_id
        self._workspace_dir = workspace_dir
        self._last_poll_time = 0.0

        # P0 anti-flood state
        self._poll_failed = False
        self._last_recovery_notice_at = 0.0
        self._last_notice_text = ""
        self._last_notice_at = 0.0

        # Followup buffer: items pending delivery at round-end
        self._followup_buffer: list[dict] = []

    def get_followup_summary(self) -> str:
        """Return a compact summary of pending followup items, then clear the buffer.

        Called by CoPawAgent.reply() after the round ends so followup messages
        are shown once the agent has finished responding — not mid-reasoning.
        Returns empty string if buffer is empty.
        """
        if not self._followup_buffer:
            return ""

        items = self._followup_buffer[:15]  # cap at 15
        self._followup_buffer.clear()

        lines: list[str] = [f"📋 **本轮结束后的待跟进通知** ({len(items)} 条)\n"]
        for item in items:
            kind = str(item.get("msg_kind", item.get("msg_type", "general"))).lower()
            kind_label = {
                "submit": "📤 submit",
                "review": "🔍 review",
                "rework": "🔧 rework",
            }.get(kind, f"📋 {kind}")
            from_agent = item.get("from_agent", "?")
            thread_id = item.get("thread_id") or item.get("task_id") or item.get("id", "-")
            content = str(item.get("content", "")).strip().splitlines()[0][:120]
            import time as _time
            ts = _time.strftime("%H:%M", _time.localtime(float(item.get("created_at", 0) or 0)))
            lines.append(f"- [{thread_id}] {kind_label} · {from_agent} @ {ts}: {content}")

        lines.append("\n输入 `/poll` 查看完整详情。")
        return "\n".join(lines)
        # Per-key last-notice timestamps to avoid rapid repeats of same item
        self._key_last_notice: dict[str, float] = {}

    async def __call__(self, agent, memory, request_context=None):
        """Poll unread mailbox and task updates, inject compact notice only."""
        now = time.time()
        request_context = request_context or {}

        agent_id = request_context.get("agent_id") or self._agent_id
        channel = str(request_context.get("channel") or "")

        poll_interval = _POLL_INTERVAL
        if channel == "feishu" and agent_id == "default":
            poll_interval = _FEISHU_DEFAULT_POLL_INTERVAL

        if now - self._last_poll_time < poll_interval:
            return
        self._last_poll_time = now

        ws_dir = self._workspace_dir
        if not agent_id or not ws_dir:
            return

        # P0 gate: default+feishu recent user input => skip this round
        if channel == "feishu" and agent_id == "default":
            try:
                last_user_input_ts = float(request_context.get("last_user_input_ts") or 0)
            except Exception:
                last_user_input_ts = 0.0
            if last_user_input_ts and (now - last_user_input_ts) <= _FEISHU_DEFAULT_USER_GATE_SEC:
                logger.info(
                    "AutoPoll gate: skip inject for default feishu; recent_user_gap_ms=%d",
                    int((now - last_user_input_ts) * 1000),
                )
                return

        try:
            urgent_lines, silent_count, followup_count, collapsed_count = self._collect_updates(agent_id, ws_dir)

            recovery_line = ""
            if self._poll_failed and (
                now - self._last_recovery_notice_at >= _RECOVERY_NOTICE_COOLDOWN_SEC
            ):
                recovery_line = "✅ 轮询已恢复;恢复期更新已折叠。"
                self._last_recovery_notice_at = now
            self._poll_failed = False

            notice_text = self._build_notice(
                urgent_lines=urgent_lines,
                silent_count=silent_count,
                followup_count=followup_count,
                collapsed_count=collapsed_count,
                recovery_line=recovery_line,
            )
            if not notice_text:
                return

            # Per-key cooldown: skip if we've notified about this specific key recently
            # (We check at the notice-text level as a proxy)
            if (
                notice_text == self._last_notice_text
                and (now - self._last_notice_at) < _DUP_NOTICE_SUPPRESS_SEC
            ):
                return

            # Global send cooldown: don't spam even if content differs
            if (now - self._last_notice_at) < _NOTICE_SEND_COOLDOWN_SEC:
                logger.debug(
                    "AutoPoll: skipped, send cooldown (%.1fs since last)",
                    now - self._last_notice_at,
                )
                return

            self._last_notice_text = notice_text
            self._last_notice_at = now

            # Tag as tail-note so frontends can style/hide appropriately
            notice_msg = Msg(
                name="system",
                content=[TextBlock(type="text", text=notice_text)],
                role="system",
                metadata={"_autopoll_tail_note": True},
            )
            if hasattr(memory, "add"):
                await memory.add(notice_msg)
            elif hasattr(agent, "memory") and hasattr(agent.memory, "add"):
                await agent.memory.add(notice_msg)
            else:
                logger.debug("AutoPoll: cannot inject, memory has no add()")
                return

            logger.info(
                "AutoPoll: injected urgent=%d silent=%d followup=%d collapsed=%d for %s",
                len(urgent_lines),
                silent_count,
                followup_count,
                collapsed_count,
                agent_id,
            )

        except Exception as e:
            self._poll_failed = True
            logger.debug("AutoPoll failed: %s", e)

    @staticmethod
    def _build_notice(
        urgent_lines: list[str],
        silent_count: int,
        followup_count: int,
        collapsed_count: int,
        recovery_line: str,
    ) -> str:
        parts: list[str] = []

        if recovery_line:
            parts.append(recovery_line)

        if urgent_lines:
            body = "\n".join(urgent_lines[:_MAX_URGENT_LINES])
            tail_parts = []
            if followup_count > 0:
                tail_parts.append(f"📋 {followup_count}条待跟进（submit/review/rework）")
            if silent_count > 0:
                tail_parts.append(f"📦 {silent_count}条常规更新（已折叠{collapsed_count}条）")
            tail = ""
            if tail_parts:
                tail = f"\n\n后台：" + " | ".join(tail_parts) + "\n输入“查看轮询”展开。"
            parts.append(f"📡 后台紧急/阻断更新\n\n{body}{tail}")
        elif silent_count > 0 or followup_count > 0:
            tail_parts = []
            if followup_count > 0:
                tail_parts.append(f"📋 {followup_count}条待跟进")
            if silent_count > 0:
                tail_parts.append(f"📦 {silent_count}条常规更新（已折叠{collapsed_count}条）")
            parts.append(f"📡 后台更新：" + " | ".join(tail_parts) + "\n输入“查看轮询”展开。")

        return "\n\n".join(parts).strip()

    def _collect_updates(self, agent_id: str, ws_dir: Path) -> tuple[list[str], int, int, int]:
        urgent_lines: list[str] = []
        silent_count = 0
        followup_count = 0
        collapsed_count = 0
        seen_urgent_keys: set[str] = set()

        # 1) Mailbox unread (collapse by task/thread/id key)
        try:
            inbox_dir = ws_dir / "mailbox" / "inbox"
            if inbox_dir.exists():
                files = sorted(
                    inbox_dir.glob("*.json"),
                    key=lambda p: p.stat().st_mtime,
                )
                parsed: list[dict[str, Any]] = []
                for f in files:
                    try:
                        parsed.append(json.loads(f.read_text(encoding="utf-8")))
                    except Exception:
                        continue

                parsed = self._filter_muted_threads(ws_dir, parsed)

                latest_by_key: dict[str, dict[str, Any]] = {}
                for data in parsed:
                    key = (
                        str(data.get("task_id") or "").strip()
                        or str(data.get("thread_id") or "").strip()
                        or str(data.get("id") or "").strip()
                    )
                    if not key:
                        key = f"file:{id(data)}"
                    latest_by_key[key] = data

                collapsed_count += max(0, len(parsed) - len(latest_by_key))

                for key, data in latest_by_key.items():
                    msg_kind = str(data.get("msg_kind") or data.get("msg_type") or "general").lower()
                    priority = str(data.get("priority") or "normal").lower()
                    need_reply = bool(data.get("need_reply"))
                    queue_mode = str(data.get("queue_mode") or "").lower()

                    effective_mode = queue_mode or (
                        "steer" if priority == "urgent" or msg_kind in {"blocker", "blocked", "urgent"}
                        else "followup" if msg_kind in {"submit", "review", "rework"}
                        else "collect"
                    )

                    if effective_mode == "collect":
                        if msg_kind in _DEFAULT_MUTED_KINDS and priority != "urgent" and not need_reply:
                            silent_count += 1
                        else:
                            # Non-urgent collect: still silent by default
                            silent_count += 1
                        continue

                    if effective_mode == "followup":
                        followup_count += 1
                        # Buffer the raw message for round-end delivery
                        self._followup_buffer.append(data)
                        continue

                    # steer: deduplicate by key
                    if key in seen_urgent_keys:
                        collapsed_count += 1
                        continue
                    seen_urgent_keys.add(key)

                    from_agent = data.get("from_agent", "?")
                    task_key = data.get("task_id") or data.get("thread_id") or "-"
                    content_line = str(data.get("content") or "").strip().splitlines()[:1]
                    content = content_line[0][:120] if content_line else ""
                    urgent_lines.append(
                        f"- [{task_key}] {from_agent}: {content}"
                    )

        except Exception as e:
            logger.debug("AutoPoll mailbox check failed: %s", e)

        # 2) Task board snapshot (always steer/blocker)
        try:
            teams_dir = ws_dir.parent / "shared" / "teams"
            if teams_dir.exists():
                for team_dir in teams_dir.iterdir():
                    if not team_dir.is_dir():
                        continue
                    tasks_file = team_dir / "tasks.json"
                    if not tasks_file.exists():
                        continue
                    try:
                        tasks = json.loads(tasks_file.read_text(encoding="utf-8"))
                    except Exception:
                        continue

                    for t in tasks:
                        if t.get("assigned_to") != agent_id and t.get("claimed_by") != agent_id:
                            continue

                        status = str(t.get("status") or "").lower()
                        priority = str(t.get("priority") or "normal").lower()
                        task_id = t.get("id", "-")

                        if status == "blocked" or priority == "urgent":
                            key = f"task:{task_id}"
                            if key in seen_urgent_keys:
                                collapsed_count += 1
                                continue
                            seen_urgent_keys.add(key)

                            urgent_lines.append(
                                f"- [{task_id}] {team_dir.name}/{status}: {str(t.get('title') or '')[:80]}"
                            )
                        else:
                            silent_count += 1

        except Exception as e:
            logger.debug("AutoPoll task board check failed: %s", e)

        # Sort urgent lines by priority: blocker > blocked > urgent > default
        def urgent_sort_key(line: str) -> tuple[int, str]:
            if "/blocked]" in line:
                return (1, line)
            if "/blocker]" in line:
                return (0, line)
            return (5, line)

        urgent_lines.sort(key=urgent_sort_key)

        return urgent_lines, silent_count, followup_count, collapsed_count

    @staticmethod
    def _filter_muted_threads(ws_dir: Path, msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter out mailbox messages from muted/archived threads."""
        if not msgs:
            return msgs
        state_file = ws_dir / "mailbox" / "thread_state.json"
        if not state_file.exists():
            return msgs
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            return msgs

        threads = state.get("threads") or {}
        muted = {
            tid
            for tid, info in threads.items()
            if isinstance(info, dict) and info.get("status") in {"muted", "archived"}
        }
        if not muted:
            return msgs

        filtered = [m for m in msgs if str(m.get("thread_id") or "") not in muted]
        if len(filtered) != len(msgs):
            logger.info(
                "AutoPoll thread mute filter: dropped=%d muted_threads=%d",
                len(msgs) - len(filtered),
                len(muted),
            )
        return filtered
