# -*- coding: utf-8 -*-
"""LoopLoader — translate loop skill JSON into PluginApi calls."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from .doom_loop import DoomLoopDetector, DoomLoopSignal
from .schema import LoopSkillConfig
from .stop_handler import StopAction, StopHandlerResult

logger = logging.getLogger(__name__)


class LoopLoader:
    """Load a loop skill config and wire it into QwenPaw.

    Translates the 6-dimension JSON schema into PluginApi calls:
    - slash_command → register_slash_command
    - skill_prompt → register_prompt_section
    - rubric → register_agent_stop_handler
    - doom_loop → register_tool_call_observer
    - safety/budget → stop handler internal logic
    """

    def __init__(self, api: Any) -> None:
        self._api = api
        self._active_loops: dict[str, _LoopSession] = {}

    def load(self, config_path: str | Path) -> None:
        """Load and register a loop skill from JSON file."""
        path = Path(config_path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        cfg = LoopSkillConfig(**raw)
        self._register(cfg)

    def load_from_dict(self, data: dict) -> None:
        """Load and register from a dictionary."""
        cfg = LoopSkillConfig(**data)
        self._register(cfg)

    def _register(self, cfg: LoopSkillConfig) -> None:
        """Wire all 6 dimensions into PluginApi."""
        self._api.register_slash_command(
            name=cfg.slash_command,
            handler=self._make_activate_handler(cfg),
            help_text=cfg.description,
            metadata={"loop_name": cfg.name},
        )

        self._api.register_prompt_section(
            name=f"loop-skill-{cfg.name}",
            after="workspace",
            provider=self._make_prompt_provider(cfg),
            condition=lambda agent, _n=cfg.name: (self._is_loop_active(_n)),
        )

        if cfg.rubric.mode in ("hard_check", "soft_judge"):
            self._api.register_agent_stop_handler(
                handler=self._make_rubric_handler(cfg),
                priority=cfg.priority,
                name=f"loop-{cfg.name}",
            )

        if cfg.doom_loop.enabled:
            self._api.register_tool_call_observer(
                observer=self._make_observer(cfg),
                name=f"doom-{cfg.name}",
            )
            from .hitl_hook import HitlPauseHook

            self._api.register_runtime_hook(HitlPauseHook())

        logger.info(
            f"LoopLoader registered loop '{cfg.name}' "
            f"as /{cfg.slash_command}",
        )

    def _is_loop_active(self, loop_name: str) -> bool:
        """Check if a loop is currently active."""
        session = self._active_loops.get(loop_name)
        return session is not None and session.active

    def _make_activate_handler(self, cfg: LoopSkillConfig):
        """Create the slash command handler that activates loop."""
        loader = self

        async def _handler(
            ctx,  # pylint: disable=unused-argument
            args: str,
        ):
            session = _LoopSession(
                config=cfg,
                task_description=args,
            )
            loader._active_loops[  # pylint: disable=protected-access
                cfg.name
            ] = session
            logger.info(
                f"Loop '{cfg.name}' activated with: {args}",
            )
            from agentscope.message import Msg

            return Msg(
                name="system",
                content=(
                    f"Loop mode '{cfg.name}' activated. " f"Task: {args}"
                ),
                role="system",
            )

        return _handler

    @staticmethod
    def _make_prompt_provider(cfg: LoopSkillConfig):
        """Create prompt provider from skill_prompt."""

        def _provider(agent):  # pylint: disable=unused-argument
            return cfg.skill_prompt

        return _provider

    def _make_rubric_handler(self, cfg: LoopSkillConfig):
        """Create stop handler from rubric config."""
        loader = self

        async def _handler(
            ctx,  # pylint: disable=unused-argument
        ) -> StopHandlerResult:
            session = (
                loader._active_loops.get(  # pylint: disable=protected-access
                    cfg.name,
                )
            )
            if session is None or not session.active:
                return StopHandlerResult(
                    action=StopAction.ALLOW,
                )

            session.iteration_count += 1

            # Safety valve checks
            safety = cfg.safety
            if session.iteration_count >= safety.max_iterations:
                session.active = False
                return StopHandlerResult(
                    action=StopAction.ALLOW,
                    reason="Max iterations reached",
                )

            # Budget check
            budget = safety.budget
            if session.total_tokens >= budget.max_tokens:
                if budget.on_exceed == "force_stop":
                    session.active = False
                    return StopHandlerResult(
                        action=StopAction.ALLOW,
                        reason="Token budget exceeded",
                    )
                return StopHandlerResult(
                    action=StopAction.ALLOW,
                    reason="Token budget exceeded (HITL)",
                )

            # Rubric evaluation
            continuation = (
                cfg.rubric.continuation_prompt
                or f"Continue working on the task. "
                f"Iteration {session.iteration_count}"
                f"/{safety.max_iterations}."
            )

            return StopHandlerResult(
                action=StopAction.BLOCK,
                continuation_message=continuation,
                reason=f"Loop '{cfg.name}' rubric: task incomplete",
            )

        return _handler

    def _make_observer(self, cfg: LoopSkillConfig):
        """Create tool call observer for doom loop detection."""
        detector = DoomLoopDetector(
            window_size=cfg.doom_loop.window_size,
            similarity_threshold=(cfg.doom_loop.similarity_threshold),
            action=cfg.doom_loop.action,
            hitl_message=(
                cfg.doom_loop.hitl_message
                or f"Agent repeating actions in loop " f"'{cfg.name}'"
            ),
        )

        async def _observer(
            tool_name: str,
            args: dict,
            result: Any,
            history: list,  # pylint: disable=unused-argument
        ) -> DoomLoopSignal:
            args_str = json.dumps(
                args,
                sort_keys=True,
                default=str,
            )
            args_hash = hashlib.md5(
                args_str.encode(),
            ).hexdigest()[:8]

            success = not (
                hasattr(result, "state") and str(result.state) == "error"
            )
            detector.record(tool_name, args_hash, success)
            return detector.check()

        return _observer

    def deactivate(self, loop_name: str) -> bool:
        """Deactivate a running loop."""
        session = self._active_loops.get(loop_name)
        if session is None:
            return False
        session.active = False
        return True

    def get_status(self, loop_name: str) -> dict | None:
        """Get current loop status for frontend display."""
        session = self._active_loops.get(loop_name)
        if session is None:
            return None
        cfg = session.config
        safety = cfg.safety
        budget = safety.budget
        token_pct = (
            session.total_tokens / budget.max_tokens
            if budget.max_tokens > 0
            else 0.0
        )
        return {
            "name": cfg.name,
            "active": session.active,
            "iteration": session.iteration_count,
            "max_iterations": safety.max_iterations,
            "tokens_used": session.total_tokens,
            "token_budget": budget.max_tokens,
            "token_pct": min(token_pct, 1.0),
            "cost_usd": session.total_cost_usd,
            "cost_budget": budget.max_cost_usd,
            "task": session.task_description,
        }


class _LoopSession:
    """Runtime state for an active loop session."""

    __slots__ = (
        "config",
        "task_description",
        "active",
        "iteration_count",
        "total_tokens",
        "total_cost_usd",
        "thinking_only_streak",
    )

    def __init__(
        self,
        config: LoopSkillConfig,
        task_description: str,
    ) -> None:
        self.config = config
        self.task_description = task_description
        self.active = True
        self.iteration_count = 0
        self.total_tokens = 0
        self.total_cost_usd = 0.0
        self.thinking_only_streak = 0


__all__ = ["LoopLoader"]
