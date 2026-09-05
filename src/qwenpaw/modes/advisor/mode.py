# -*- coding: utf-8 -*-
"""``AdvisorMode`` — the ``AgentMode`` entry point for Advisor Mode."""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from agentscope.message import Msg, TextBlock

from ..base import AgentMode, find_active_explicit_mode
from ...app.agent_context import get_current_session_id
from ...runtime.hooks import HookBase, HookContext
from ...runtime.slash_command_registry import CommandSpec
from ..goal.helpers import rewrite_user_msg
from .config import is_enabled, resolve_agent_config
from .middleware import (
    AdvisorMiddleware,
    default_log_dir,
)
from .trigger import InterventionTrigger
from .models import (
    AdvisorClient,
    resolve_worker_slot,
    resolve_advisor_slot,
    slot_label,
    slot_to_dict,
)

if TYPE_CHECKING:
    from ...runtime.tool_registry import ToolDescriptor

logger = logging.getLogger(__name__)

_LOOP_DESCRIPTION = (
    "Let a stronger model plan and step in while a cheaper one does the "
    "work."
)

# How many conversations keep their advisor state (per-conversation switch,
# advisor history, consult budget) per mode instance. The least recently
# used conversation is dropped past this, which bounds memory on a
# long-running server.
_MAX_SESSIONS = 64


_UNAVAILABLE_NOTICE = (
    "Advisor Mode is switched off for this agent. Turn it on in "
    "Configuration → Agent Loop Settings → Advisor, then pick Advisor in "
    "the Loop mode menu or send `/advisor on`."
)


def _system_message(text: str) -> Msg:
    return Msg(
        name="system",
        role="system",
        content=[TextBlock(type="text", text=text)],
    )


@dataclass
class AdvisorSessionState:
    """Advisor state that outlives one request.

    ``override`` is the per-conversation switch (set by ``/advisor``): it
    takes precedence over the agent's default from ``agent.json``.
    ``advisor_history`` is the advisor conversation, and ``middleware`` the
    instance serving the request in flight (looked up by the
    ``consult_advisor`` tool). Whether the opening plan has been written
    is read off that instance too, so the plan happens once per
    conversation rather than once per user turn.
    """

    override: bool | None = None
    advisor_history: list[dict[str, str]] = field(default_factory=list)
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
      (:class:`WorkerModelHook`).
    * ``middlewares`` contributes :class:`AdvisorMiddleware`, which asks
      the advisor (the primary model) for a plan and re-consults it mid-run.
    * ``tools`` registers the real ``consult_advisor`` tool so the agent
      can ask on its own.
    * ``commands`` registers ``/advisor``, which also makes the mode
      selectable in the chat composer like ``/goal`` and ``/mission``.
    """

    name = "advisor"

    def __init__(self) -> None:
        self._sessions: "OrderedDict[str, AdvisorSessionState]" = OrderedDict()

    def setup(self, workspace: object) -> None:
        from .tools import register_advisor_tools_governance

        super().setup(workspace)
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
        """Forget the conversation's switch and advisor history on
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
        menu sends ``/advisor <task>``. ``/advisor on`` does the same
        anywhere slash commands work) — and only while the agent has the
        mode switched on in Configuration.
        """
        key = self._session_key(ctx)
        state = self._sessions.get(key) if key else None
        if state is None or not state.override:
            return False
        return is_enabled(resolve_agent_config(ctx))

    def hooks(self) -> list[HookBase]:
        from .hooks import WorkerModelHook

        return [WorkerModelHook(owner_mode=self)]

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
        cfg = agent_config or resolve_agent_config(ctx)
        return [self.build_middleware(ctx, cfg)]

    def commands(self) -> list[CommandSpec]:
        return [
            CommandSpec(
                name="advisor",
                handler=self._command_handler,
                category="builtin",
                help_text=_LOOP_DESCRIPTION,
                metadata={"builtin": True},
            ),
        ]

    # ── middleware construction ─────────────────────────────────────────

    def build_middleware(
        self,
        ctx: HookContext,
        cfg: Any,
    ) -> AdvisorMiddleware:
        """Build the request-scoped :class:`AdvisorMiddleware`.

        The advisor conversation, the on-demand budget and the fact that
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
        am = cfg.advisor_mode
        advisor = AdvisorClient(
            agent_id=agent_id,
            agent_config=cfg,
            model_slot=resolve_advisor_slot(cfg),
            thinking=am.advisor_thinking,
        )
        env_root = getattr(cfg, "project_dir", None) or getattr(
            ctx,
            "workspace_dir",
            None,
        )
        middleware = AdvisorMiddleware(
            advisor=advisor,
            trigger=InterventionTrigger(config=am.intervention),
            plan_enabled=am.plan_enabled,
            followup_enabled=am.followup_enabled,
            on_demand_enabled=am.on_demand_enabled,
            max_consults=am.max_consults,
            consults_used=state.consults_used,
            plan_injected=state.plan_injected,
            advisor_history=state.advisor_history,
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
        text = (args or "").strip()
        word = text.lower()
        key = self._session_key(ctx)
        cfg = resolve_agent_config(ctx)
        if cfg is None:
            return _system_message(
                "Advisor Mode: could not load the agent configuration.",
            )

        if word in ("", "status", "help"):
            return _system_message(self._status_text(cfg, self._override(key)))

        if word != "off" and not is_enabled(cfg):
            return _system_message(_UNAVAILABLE_NOTICE)

        conflict = None if word == "off" else find_active_explicit_mode(ctx)
        if conflict is not None and conflict != self.name:
            return _system_message(
                f"End the active {conflict} mode before starting /advisor.",
            )

        if word in ("on", "off"):
            enabled = word == "on"
            if key:
                self.session_state(key).override = enabled
            return _system_message(self._status_text(cfg, enabled))

        # Anything else is a task: start the mode and let the agent run it.
        if key:
            self.session_state(key).override = True
        rewrite_user_msg(ctx, text)
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
        am = cfg.advisor_mode
        active = am.enabled and bool(override)
        advisor = slot_label(resolve_advisor_slot(cfg))
        worker_slot = slot_to_dict(resolve_worker_slot(cfg))
        worker = (
            slot_label(worker_slot)
            if worker_slot is not None
            else f"{advisor} (no sub-agent model configured)"
        )
        if not am.enabled:
            headline = (
                "Advisor Mode: off, switched off for this agent in "
                "Configuration."
            )
        elif active:
            headline = "Advisor Mode: on for this conversation."
        else:
            headline = (
                "Advisor Mode: off, not selected for this conversation. "
                "Pick Advisor in the Loop mode menu or send `/advisor on`."
            )
        return (
            f"{headline}\n"
            f"- advisor model: {advisor}\n"
            f"- worker model: {worker}\n"
            f"- opening plan: {'on' if am.plan_enabled else 'off'}\n"
            "- mid-run auto intervention: "
            f"{'on' if am.followup_enabled else 'off'}\n"
            "- consult_advisor tool: "
            f"{'on' if am.on_demand_enabled else 'off'} "
            f"(max {am.max_consults} per conversation)"
        )


__all__ = ["AdvisorMode"]
