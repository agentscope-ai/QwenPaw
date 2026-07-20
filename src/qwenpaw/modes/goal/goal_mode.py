# -*- coding: utf-8 -*-
"""GoalMode — QwenPaw's built-in persistent loop mode.

Similar to Codex /goal: user sets a goal, agent works
until the rubric grader confirms completion or budget
is exhausted.

Inherits ``AgentMode`` so it plugs into the standard
``builtin_mode_clses`` bootstrap — all registration
stays inside this file and ``modes/goal/``.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from agentscope.message import Msg, TextBlock

from ..base import AgentMode
from ...app.agent_context import (
    get_current_session_id,
)
from ...loop.gates import (
    GoalStatusRubric,
    StopHandler,
    StopHandlerRegistration,
)
from ...runtime.hooks import HookBase, HookContext
from ...runtime.slash_command_registry import (
    CommandSpec,
)
from .gates import GoalBudgetGate, GoalTurnGate, RubricGate
from .helpers import (
    create_completion_gate,
    create_doom_loop_gate,
    register_goal_tools_governance,
    rewrite_user_msg,
)
from .prompts import (
    CONTINUATION_PROMPT,
    INITIAL_GOAL_PROMPT,
)

if TYPE_CHECKING:
    from ...runtime.prompt_manager import (
        PromptContributor,
    )

logger = logging.getLogger(__name__)

DEFAULT_MAX_ITERATIONS = 20
DEFAULT_MAX_TOKENS = 300000


@dataclass
class GoalSession:
    """Runtime state for an active /goal session."""

    goal: str
    active: bool = True
    iteration: int = 0
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    max_tokens: int = DEFAULT_MAX_TOKENS
    tokens_used: int = 0
    last_verdict: str = ""
    last_feedback: str = ""
    started_at: float = field(
        default_factory=time.time,
    )


class GoalMode(AgentMode):
    """Built-in /goal mode (AgentMode subclass).

    Registers /goal and /cancel slash commands. When
    active, three gates in the universal StopHandler
    control loop termination:
    1. GoalTurnGate — hard turn limit + completion
    2. GoalBudgetGate — token budget limit
    3. RubricGate — rubric evaluation (LLM-based)

    This is the ONLY built-in loop mode. All other
    loops (ralph, ultrawork, etc.) are plugins.
    """

    name = "goal"

    def __init__(self) -> None:
        self._sessions: dict[str, GoalSession] = {}
        self._default_max_tokens = DEFAULT_MAX_TOKENS
        self._handler: StopHandler | None = None

    @property
    def sessions(self) -> dict[str, GoalSession]:
        """Expose sessions for sibling modules."""
        return self._sessions

    @property
    def default_max_tokens(self) -> int:
        """Default token budget for new goals."""
        return self._default_max_tokens

    def active_session(
        self,
    ) -> GoalSession | None:
        """Return active session for current context.

        Uses get_current_session_id() ContextVar to
        look up session. Returns None if no session or
        session is inactive.
        """
        key = get_current_session_id()
        if key is None:
            return None
        s = self._sessions.get(key)
        if s is not None and s.active:
            return s
        return None

    def session_by_ctx_var(
        self,
    ) -> Optional[GoalSession]:
        """Return session by ContextVar (any status).

        Uses agent_context.get_current_session_id().
        Returns session even when active=False so
        that gates can detect completed goals.
        """
        key = get_current_session_id()
        if key is None:
            return None
        return self._sessions.get(key)

    def deactivate(self) -> None:
        """Remove current session from _sessions.

        Called after goal completion to prevent stale
        sessions from blocking subsequent messages.
        """
        key = get_current_session_id()
        if key is not None:
            self._sessions.pop(key, None)

    def on_conversation_reset(
        self,
        ctx: HookContext,
    ) -> None:
        """Clear the current goal session on /new or /clear."""
        self._sessions.pop(ctx.session_id, None)
        if self._handler is not None:
            self._handler.reset_session()

    # ---- AgentMode interface ----

    def commands(self) -> list[CommandSpec]:
        """Return /goal command spec."""
        return [
            CommandSpec(
                name="goal",
                handler=self._activate_handler,
                category="builtin",
                help_text=("Set a goal \u2014 agent works " "until done."),
                metadata={"builtin": True},
            ),
        ]

    def tools(self) -> list:
        """Return goal tools: get/create/update."""
        from ...runtime.tool_registry import (
            ToolDescriptor,
        )
        from .tools import (
            make_create_goal,
            make_get_goal,
            make_update_goal,
        )

        return [
            ToolDescriptor(
                name="get_goal",
                func=make_get_goal(self),
                requires_modes=("goal",),
                description=(
                    "Get the current goal status, " "budgets, and usage."
                ),
            ),
            ToolDescriptor(
                name="create_goal",
                func=make_create_goal(self),
                requires_modes=("goal",),
                description=(
                    "Create a goal only when " "explicitly requested."
                ),
            ),
            ToolDescriptor(
                name="update_goal",
                func=make_update_goal(self),
                requires_modes=("goal",),
                description=("Mark goal as complete " "or blocked."),
            ),
        ]

    def hooks(self) -> list[HookBase]:
        """No bypass hooks — Gate controls."""
        return []

    def prompt_contributors(
        self,
    ) -> list["PromptContributor"]:
        """Return goal-mode prompt contributor."""
        from .contributor import (
            GoalPromptContributor,
        )

        return [
            GoalPromptContributor(owner=self),
        ]

    def setup(self, workspace: object) -> None:
        """Register gates into the goal-scoped handler."""
        super().setup(workspace)

        handler = StopHandler()
        self._handler = handler
        workspace.plugins.stop_handlers.append(
            StopHandlerRegistration(
                plugin_id="__goal_mode__",
                handler=handler,
                priority=0,
                name="goal-stop-handler",
                scope="goal",
                is_active=lambda: self.active_session() is not None,
            ),
        )
        rubric = GoalStatusRubric(
            get_session_fn=self.session_by_ctx_var,
        )
        doom_gate = create_doom_loop_gate(workspace)
        if doom_gate is not None:
            handler.register(doom_gate)
        handler.register(GoalTurnGate(self))
        handler.register(GoalBudgetGate(self))
        handler.register(RubricGate(self, rubric))

        completion_gate = create_completion_gate(
            workspace,
        )
        if completion_gate is not None:
            handler.register(completion_gate)

        register_goal_tools_governance()

    def is_active(self, ctx: Any) -> bool:
        """Goal mode is active when session live."""
        return self.active_session() is not None

    # ---- slash command handlers ----

    async def _activate_handler(
        self,
        ctx: Any,
        args: str,
    ) -> Optional[Msg]:
        """Handle /goal <task description>.

        Returns None so the Runtime does NOT skip
        the agent. Rewrites user message to bare text.
        """
        if not args or not args.strip():
            return Msg(
                name="system",
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Usage: /goal <description>"
                            "\nExample: /goal fix all "
                            "failing tests"
                        ),
                    ),
                ],
                role="system",
            )

        goal_text = args.strip()
        session_key = self._current_session_key(
            ctx,
        )
        session = GoalSession(goal=goal_text)
        self._sessions[session_key] = session

        logger.info(
            "Goal mode activated: %s (key=%s)",
            goal_text[:80],
            session_key,
        )

        rewrite_user_msg(ctx, goal_text)
        return None

    # ---- prompt / session helpers ----

    def prompt_provider(
        self,
        agent: Any,  # pylint: disable=unused-argument
    ) -> str:
        """Provide goal-mode skill prompt.

        First turn uses INITIAL_GOAL_PROMPT;
        subsequent turns use CONTINUATION_PROMPT.
        """
        session = self.active_session()
        if session is None:
            return ""

        if session.iteration == 0:
            return INITIAL_GOAL_PROMPT.format(
                objective=session.goal,
                max_iterations=(session.max_iterations),
                token_budget=session.max_tokens,
            )

        remaining = max(
            0,
            session.max_tokens - session.tokens_used,
        )
        return CONTINUATION_PROMPT.format(
            objective=session.goal,
            iteration=session.iteration,
            max_iterations=(session.max_iterations),
            tokens_used=session.tokens_used,
            token_budget=session.max_tokens,
            remaining_tokens=remaining,
        )

    @staticmethod
    def _current_session_key(
        ctx: Any,
    ) -> str:
        """Derive session key from context."""
        if isinstance(ctx, dict):
            return ctx.get(
                "session_id",
                "default",
            )
        return getattr(
            ctx,
            "session_id",
            "default",
        )

    def get_session(
        self,
        session_key: str = "default",
    ) -> Optional[GoalSession]:
        """Get goal session (for status display)."""
        return self._sessions.get(session_key)

    def get_all_active_sessions(
        self,
    ) -> dict[str, GoalSession]:
        """Return all active sessions."""
        return {k: v for k, v in self._sessions.items() if v.active}


__all__ = ["GoalMode", "GoalSession"]
