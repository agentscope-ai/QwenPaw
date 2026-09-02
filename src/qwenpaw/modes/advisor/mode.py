# -*- coding: utf-8 -*-
"""``AdvisorMode`` — the ``AgentMode`` entry point for Advisor Mode."""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from agentscope.message import Msg, TextBlock

from ..base import AgentMode
from ...app.agent_context import get_current_session_id
from ...runtime.hooks import HookBase, HookContext
from ...runtime.slash_command_registry import CommandSpec
from .config import is_enabled, resolve_agent_config
from .middleware import (
    DEFAULT_MAX_CONSULTS,
    AdvisorMiddleware,
    default_log_dir,
)
from .trigger import InterventionTrigger, TriggerConfig
from .teacher import (
    AdvisorTeacher,
    effective_student_slot,
    effective_teacher_slot,
    slot_label,
    slot_to_dict,
)

if TYPE_CHECKING:
    from ...runtime.tool_registry import ToolDescriptor

logger = logging.getLogger(__name__)

_USAGE = (
    "Usage: /advisor <task>  (start Advisor Mode for this conversation and "
    "run the task)\n"
    "       /advisor on | off  (switch it on or off for this conversation)\n"
    "       /advisor status\n"
    "In Advisor Mode the agent's main model writes a plan up front, answers "
    "the agent's questions, and steps in when the agent keeps failing, while "
    "the agent itself runs on the configured sub-agent model."
)

_LOOP_DESCRIPTION = (
    "Advisor: the main model plans the task, answers the agent's questions "
    "and steps in when it keeps failing; the agent runs on the sub-agent "
    "model. /advisor off leaves the mode."
)
_LOOP_NAME_I18N = {"en": "Advisor", "zh-CN": "顾问"}
_LOOP_DESCRIPTION_I18N = {
    "en": (
        "**Advisor**: the main model plans the task, answers the agent's "
        "questions and steps in when it keeps failing; the agent runs on "
        "the sub-agent model."
    ),
    "zh-CN": ("**顾问**：主模型先写计划、回答智能体的提问，并在其反复失败时" "介入；智能体本身使用 Sub-agent 模型运行。"),
}

# How many chat sessions' advisor state to keep per mode instance.
_MAX_SESSIONS = 64


_UNAVAILABLE_NOTICE = (
    "Advisor Mode is switched off for this agent. Turn it on in "
    "Configuration → Agent Loop Settings → Advisor, then pick Advisor in "
    "the composer's mode menu or send /advisor on."
)


def _trigger_config(advisor_config: Any) -> TriggerConfig:
    """The mid-run intervention thresholds from ``advisor_mode.intervention``
    (defaults when the section is missing)."""
    section = getattr(advisor_config, "intervention", None)
    defaults = TriggerConfig()
    kwargs = {}
    for name in (
        "consecutive_failures",
        "window_size",
        "window_failures",
        "cooldown_steps",
        "max_interventions",
    ):
        kwargs[name] = int(getattr(section, name, getattr(defaults, name)))
    return TriggerConfig(**kwargs)


def _system_reply(text: str) -> Msg:
    return Msg(
        name="system",
        role="system",
        content=[TextBlock(type="text", text=text)],
    )


def _rewrite_user_msg(ctx: Any, text: str) -> None:
    """Replace the last user message's content with *text*.

    Used when ``/advisor <task>`` starts the mode: the agent must see the
    bare task, not the slash command.
    """
    msgs = getattr(ctx, "input_msgs", None)
    if not msgs:
        return
    last = msgs[-1]
    if not isinstance(last, Msg):
        return
    last.content = [TextBlock(type="text", text=text)]


@dataclass
class AdvisorSessionState:
    """Advisor state that outlives one request.

    ``override`` is the per-conversation switch (set by ``/advisor``): it
    takes precedence over the agent's default from ``agent.json``.
    ``teacher_history`` is the teacher conversation, and ``middleware`` the
    instance serving the request in flight (looked up by the
    ``consult_advisor`` tool). Whether the opening plan has been written
    is read off that instance too, so the plan happens once per
    conversation rather than once per user turn.
    """

    override: bool | None = None
    teacher_history: list[dict[str, str]] = field(default_factory=list)
    middleware: AdvisorMiddleware | None = None

    @property
    def consults_used(self) -> int:
        """On-demand consultations spent in this session so far."""
        return self.middleware.consults_used if self.middleware else 0

    @property
    def plan_injected(self) -> bool:
        """Whether the opening plan already reached this conversation."""
        return bool(self.middleware and self.middleware.plan_injected)


class AdvisorMode(AgentMode):
    """Bundle for Advisor Mode behaviour.

    * ``is_available``: ``agent_config.advisor_mode.enabled`` — whether
      the agent offers the mode at all (composer menu, ``/advisor``).
    * ``is_active``: the conversation's ``/advisor`` switch, which only
      counts while the mode is available.
    * ``hooks`` swaps the agent onto ``subagent_model`` before the build
      (:class:`StudentModelHook`).
    * ``middlewares`` contributes :class:`AdvisorMiddleware`, which asks
      the teacher (the main model) for a plan and re-consults it mid-run.
    * ``tools`` registers the real ``consult_advisor`` tool so the agent
      can ask on its own.
    * ``commands`` registers ``/advisor``, which also makes the mode
      selectable in the chat composer like ``/goal`` and ``/mission``.
    """

    name = "advisor"
    # Listed in the composer's loop-mode menu and mutually exclusive with
    # the other loop modes while active.
    exclusive = True

    def __init__(self) -> None:
        from .tools import register_advisor_tools_governance

        self._sessions: "OrderedDict[str, AdvisorSessionState]" = OrderedDict()
        # Without this the governor denies the tool by policy.
        register_advisor_tools_governance()

    # ── per-session state ───────────────────────────────────────────────

    @staticmethod
    def _session_key(ctx: Any) -> str:
        key = getattr(ctx, "session_id", None) if ctx is not None else None
        return str(key or get_current_session_id() or "")

    def session_state(self, session_id: str) -> AdvisorSessionState:
        """Return (creating if needed) the state for ``session_id``."""
        state = self._sessions.get(session_id)
        if state is None:
            state = AdvisorSessionState()
            self._sessions[session_id] = state
        self._sessions.move_to_end(session_id)
        while len(self._sessions) > _MAX_SESSIONS:
            self._sessions.popitem(last=False)
        return state

    def current_middleware(self) -> AdvisorMiddleware | None:
        """The middleware serving the request in flight, if any.

        Uses the ``get_current_session_id()`` ContextVar, the same way
        Goal mode's tools find their session.
        """
        key = get_current_session_id()
        if not key:
            return None
        state = self._sessions.get(key)
        return state.middleware if state is not None else None

    async def on_conversation_reset(self, ctx: HookContext) -> None:
        """Forget the conversation's switch and teacher history on
        ``/new`` and ``/clear``."""
        key = self._session_key(ctx)
        if key and self._sessions.pop(key, None) is not None:
            logger.info("Advisor Mode: reset session %s", key)

    # ── AgentMode surface ───────────────────────────────────────────────

    def is_available(self, agent_config: object) -> bool:
        """Offered in the composer only when switched on for the agent."""
        return is_enabled(agent_config)

    def is_active(self, ctx: HookContext) -> bool:
        """On for this conversation.

        Conversations start in the default loop. Advisor Mode is on only
        after it was picked for the conversation (the composer's mode
        menu sends ``/advisor <task>``; ``/advisor on`` does the same
        anywhere slash commands work) — and only while the agent has the
        mode switched on in Configuration.
        """
        if not is_enabled(resolve_agent_config(ctx)):
            return False
        key = self._session_key(ctx)
        state = self._sessions.get(key) if key else None
        return bool(state is not None and state.override)

    def hooks(self) -> list[HookBase]:
        from .hooks import StudentModelHook

        return [StudentModelHook(owner_mode=self)]

    def tools(self) -> list["ToolDescriptor"]:
        from ...runtime.tool_registry import ToolDescriptor
        from .tools import (
            CONSULT_TOOL_DESCRIPTION,
            CONSULT_TOOL_NAME,
            make_consult_advisor,
        )

        return [
            ToolDescriptor(
                name=CONSULT_TOOL_NAME,
                func=make_consult_advisor(self),
                requires_modes=(self.name,),
                description=CONSULT_TOOL_DESCRIPTION,
            ),
        ]

    def middlewares(
        self,
        ctx: HookContext,
        agent_config: object,
    ) -> list:
        if not self.is_active(ctx):
            return []
        cfg = agent_config or resolve_agent_config(ctx)
        return [self.build_middleware(ctx, cfg)]

    def commands(self) -> list[CommandSpec]:
        return [
            CommandSpec(
                name="advisor",
                handler=self._command_handler,
                category="builtin",
                help_text=_LOOP_DESCRIPTION,
                metadata={
                    "builtin": True,
                    "loop_name": "Advisor",
                    "name_i18n": dict(_LOOP_NAME_I18N),
                    "description_i18n": dict(_LOOP_DESCRIPTION_I18N),
                },
            ),
        ]

    # ── middleware construction ─────────────────────────────────────────

    def build_middleware(
        self,
        ctx: HookContext,
        cfg: Any,
    ) -> AdvisorMiddleware:
        """Build the request-scoped :class:`AdvisorMiddleware`.

        The teacher conversation, the on-demand budget and the fact that
        the opening plan has been written carry over from the earlier
        requests of the same chat session.
        """
        agent_id = (
            getattr(cfg, "id", None) or getattr(ctx, "agent_id", None) or ""
        )
        session_id = self._session_key(ctx)
        state = (
            self.session_state(session_id)
            if session_id
            else AdvisorSessionState()
        )
        teacher = AdvisorTeacher(
            agent_id=agent_id,
            agent_config=cfg,
            model_slot=effective_teacher_slot(cfg),
        )
        env_root = getattr(cfg, "project_dir", None) or getattr(
            ctx,
            "workspace_dir",
            None,
        )
        am = getattr(cfg, "advisor_mode", None)
        middleware = AdvisorMiddleware(
            teacher=teacher,
            trigger=InterventionTrigger(config=_trigger_config(am)),
            plan_enabled=bool(getattr(am, "plan_enabled", True)),
            followup_enabled=bool(getattr(am, "followup_enabled", True)),
            on_demand_enabled=bool(getattr(am, "on_demand_enabled", True)),
            max_consults=int(
                getattr(am, "max_consults", DEFAULT_MAX_CONSULTS),
            ),
            consults_used=state.consults_used,
            plan_injected=state.plan_injected,
            teacher_history=state.teacher_history,
            env_context_root=env_root,
            log_dir=default_log_dir(agent_id),
            session_id=session_id,
            agent_id=agent_id,
        )
        state.middleware = middleware
        return middleware

    # ── /advisor command ────────────────────────────────────────────────

    async def _command_handler(
        self,
        ctx: Any,
        args: str,
    ) -> Optional[Msg]:
        """Handle ``/advisor``.

        * ``/advisor <task>``: switch this conversation into Advisor Mode
          and run the task (the agent sees the bare task). This is what the
          chat composer sends when the mode is picked from its menu.
        * ``/advisor on`` / ``/advisor off``: switch this conversation.
        * ``/advisor`` / ``/advisor status``: report the current state.
        """
        from ...config.config import load_agent_config

        agent_id = getattr(ctx, "agent_id", None) or "default"
        text = (args or "").strip()
        word = text.lower()
        key = self._session_key(ctx)
        try:
            cfg = load_agent_config(agent_id)
        except Exception as exc:
            return _system_reply(f"Advisor Mode: config unavailable ({exc})")

        if word in ("", "status", "help"):
            return _system_reply(self._status_text(cfg, self._override(key)))

        if word != "off" and not is_enabled(cfg):
            return _system_reply(_UNAVAILABLE_NOTICE)

        if word in ("on", "off"):
            enabled = word == "on"
            if key:
                self.session_state(key).override = enabled
            state = "enabled" if enabled else "disabled"
            return _system_reply(
                f"Advisor Mode {state} for this conversation.\n"
                f"{self._status_text(cfg, enabled if key else None)}",
            )

        # Anything else is a task: start the mode and let the agent run it.
        if key:
            self.session_state(key).override = True
        _rewrite_user_msg(ctx, text)
        logger.info(
            "Advisor Mode: started for session %s with task %r",
            key,
            text[:80],
        )
        return None

    def _override(self, key: str) -> bool | None:
        state = self._sessions.get(key) if key else None
        return state.override if state is not None else None

    @staticmethod
    def _status_text(cfg: Any, override: bool | None = None) -> str:
        am = getattr(cfg, "advisor_mode", None)
        available = bool(am and getattr(am, "enabled", False))
        active = available and bool(override)
        plan = bool(am is None or getattr(am, "plan_enabled", True))
        followup = bool(am is None or getattr(am, "followup_enabled", True))
        on_demand = bool(
            am is None or getattr(am, "on_demand_enabled", True),
        )
        max_consults = int(
            getattr(am, "max_consults", DEFAULT_MAX_CONSULTS)
            if am is not None
            else DEFAULT_MAX_CONSULTS,
        )
        teacher = slot_label(effective_teacher_slot(cfg))
        student_slot = slot_to_dict(effective_student_slot(cfg))
        student = (
            slot_label(student_slot)
            if student_slot is not None
            else f"{teacher} (no sub-agent model configured)"
        )
        if not available:
            scope = "switched off for this agent in Configuration"
        elif active:
            scope = "this conversation"
        else:
            scope = (
                "not selected for this conversation; pick Advisor in the "
                "composer's mode menu or send /advisor on"
            )
        return (
            f"Advisor Mode: {'on' if active else 'off'} ({scope})\n"
            f"- advisor (teacher): {teacher}\n"
            f"- agent (student): {student}\n"
            f"- opening plan: {'on' if plan else 'off'}\n"
            f"- mid-run auto intervention: {'on' if followup else 'off'}\n"
            f"- consult_advisor tool: {'on' if on_demand else 'off'} "
            f"(max {max_consults} per conversation)"
        )


__all__ = ["AdvisorMode", "AdvisorSessionState"]
