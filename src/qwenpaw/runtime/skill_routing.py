# -*- coding: utf-8 -*-
"""Load the skill selected for the current request in the active runtime."""
from __future__ import annotations

import logging
import re
from agentscope.message import Msg, TextBlock

from ..agents.file_delivery_guard import (
    FileDeliveryGuard,
    requested_file_types,
    creation_action,
)
from ..agents.retrieval_evidence_guard import RetrievalEvidenceGuard
from ..agents.skill_runtime import (
    SkillIntentRouter,
    SkillRoute,
    discover_enabled_skills,
    route_to_prompt,
    render_skill_list,
    render_skill_info,
)
from ..app.console_delegation import current_delegation
from .message_convert import _get_last_user_text

logger = logging.getLogger(__name__)


def _skill_route(ctx, effective_skills):
    from ..app.chats.utils import strip_injected_skill_block

    text = strip_injected_skill_block(_get_last_user_text(ctx.input_msgs) or "", "user")
    enabled = set(effective_skills)
    channel = getattr(ctx.request, "channel", None) or "console"
    skills = [
        meta
        for meta in discover_enabled_skills(ctx.workspace_dir, channel)
        if meta.name in enabled
    ]
    route = SkillIntentRouter(skills).route(text)
    pending = (getattr(ctx, "mode_state", None) or {}).get("skill_routing", {})
    if (
        route is None
        and pending.get("task")
        and re.fullmatch(
            r"(?:继续|确认|可以|好的|按(?:这个|上述|刚才).{0,10}(?:做|执行|生成)|开始(?:执行|生成|制作)|重试|再试一次|continue|confirmed|proceed)[。.!！\s]*",
            text.strip(),
            re.I,
        )
    ):
        previous = next(
            (skill for skill in skills if skill.name == pending.get("skill")), None
        )
        if previous is not None or pending.get("skill") is None:
            if previous is not None:
                route = SkillRoute(
                    kind="invoke",
                    skill=previous,
                    args=text,
                    reason="pending_task_continuation",
                )
            else:
                route = SkillIntentRouter(skills).route(pending["task"])
            text = pending["task"]
    return text, route


def _remember_pending_task(ctx, text, skill):
    if not hasattr(ctx, "mode_state"):
        ctx.mode_state = {}
    ctx.mode_state["skill_routing"] = {"task": text, "skill": skill}


def finish_skill_request(ctx):
    """Clear a pending deliverable only after observed successful delivery."""
    guard = getattr(ctx.agent, "_delivery_guard", None)
    if guard is not None and guard.delivered:
        ctx.mode_state.pop("skill_routing", None)


def skill_routing_response(ctx):
    """Resolve informational and ambiguous routes before model execution."""
    if ctx.workspace_dir is None:
        return None
    from ..agents.skill_system import resolve_effective_skills

    enabled = resolve_effective_skills(
        ctx.workspace_dir, getattr(ctx.request, "channel", None) or "console"
    )
    request_context = getattr(ctx.request, "request_context", None) or {}
    if isinstance(request_context.get("subagent_skills"), list):
        enabled = [
            name for name in enabled if name in request_context["subagent_skills"]
        ]
    _, route = _skill_route(ctx, enabled)
    if route is None or route.kind == "invoke":
        return None
    if route.kind == "clarify":
        # Natural-language skill selection belongs to the agent, which sees
        # the complete enabled metadata catalog. Do not intercept it with a
        # server-side lexical ranking or force a skill choice on the user.
        return None
    if route.kind == "list":
        text = render_skill_list(list(route.skills))
    elif route.kind == "info" and route.skill is not None:
        text = render_skill_info(route.skill)
    else:
        return None
    return Msg(name="assistant", role="assistant", content=[TextBlock(text=text)])


def prepare_skill_request(ctx, effective_skills: list[str]):
    text, route = _skill_route(ctx, effective_skills)
    delegation = current_delegation.get()
    # A restricted worker returns intermediate output to its caller. The parent
    # still needs actual file delivery before claiming the user's deck is ready.
    require_delivery = not (
        delegation and delegation.is_subtask and delegation.tools is not None
        and "send_file_to_user" not in delegation.tools
    )
    required_types = requested_file_types(text) if require_delivery else set()
    guard = FileDeliveryGuard(required_types) if required_types else None
    ctx.skill_load_required = bool(route and route.kind in {"invoke", "clarify"})
    if route is None or route.kind not in {"invoke", "clarify"}:
        if guard is not None:
            _remember_pending_task(ctx, text, None)
            ctx.inject_context(
                guard.continuation_message, priority=20, source="file-delivery"
            )
        return guard
    if re.search(r"搜索|检索|查询|查找|搜集|收集|search", text, re.I):
        guard = RetrievalEvidenceGuard(required_types)
    explicit = text.strip().startswith("/") or route.reason == "pending_task_continuation"
    instruction = route_to_prompt(route) if explicit else (
        "Discover the matching enabled skill from the available skill metadata. "
        "Compare the descriptions and choose the skill appropriate for the user's "
        "task, then call load_skill before executing its workflow. "
        "Do not treat a remembered skill body as already loaded in this turn."
    )
    if require_delivery and not required_types and creation_action(text) and re.search(r"画|绘|draw|paint", text, re.I):
        required_types = {"image/"}
        guard = FileDeliveryGuard(required_types)
    if guard is not None:
        instruction += "\n" + guard.continuation_message
    # Remember the overall task across an outline-only or prerequisite turn.
    # Per-turn restrictions still apply to this turn's guard and user message.
    pending_task = re.split(r"此轮|本轮", text, maxsplit=1)[0].strip() or text
    _remember_pending_task(ctx, pending_task, route.skill.name if explicit and route.skill else None)
    ctx.inject_context(instruction, priority=20, source="skill-routing")
    logger.info("Skill discovery: load_skill required; selection delegated to agent")
    return guard
