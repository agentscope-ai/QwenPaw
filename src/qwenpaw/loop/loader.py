# -*- coding: utf-8 -*-
"""LoopLoader — translate loop skill JSON into PluginApi calls."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from .doom_loop import (
    DoomLoopDetector,
    DoomLoopSignal,
)
from .rubric_grader import (
    RubricVerdict,
    SubAgentRubric,
)
from .schema import LoopSkillConfig
from .stop_handler import StopAction, StopHandlerResult

logger = logging.getLogger(__name__)

_LOOP_STATE_DIR = ".qwenpaw/loop_state"


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

        from .iter_bypass_hook import (
            LoopIterBypassHook,
            LoopIterRestoreHook,
        )

        self._api.register_runtime_hook(
            LoopIterBypassHook(
                is_active_fn=lambda: any(
                    s.active for s in self._active_loops.values()
                ),
            ),
        )
        self._api.register_runtime_hook(
            LoopIterRestoreHook(),
        )

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

    def _make_rubric_handler(  # noqa: C901
        self,
        cfg: LoopSkillConfig,
    ):
        """Create stop handler with actual rubric evaluation."""
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
            _update_session_tokens(session, ctx)
            safety = cfg.safety

            if session.iteration_count >= safety.max_iterations:
                session.active = False
                return StopHandlerResult(
                    action=StopAction.ALLOW,
                    reason="Max iterations reached",
                )

            budget = safety.budget
            if (
                budget.max_tokens > 0
                and session.total_tokens >= budget.max_tokens
            ):
                session.active = False
                return StopHandlerResult(
                    action=StopAction.ALLOW,
                    reason="Token budget exceeded",
                )

            # ── Rubric evaluation ──
            rubric = cfg.rubric

            if rubric.mode == "hard_check" and rubric.check_expression:
                passed = _eval_hard_check(
                    cfg,
                    session,
                )
                if passed:
                    session.active = False
                    return StopHandlerResult(
                        action=StopAction.ALLOW,
                        reason="Rubric hard_check passed",
                    )

            if rubric.mode == "soft_judge":
                verdict = await _eval_soft_judge(
                    cfg,
                    session,
                )
                if verdict == RubricVerdict.SATISFIED:
                    session.active = False
                    return StopHandlerResult(
                        action=StopAction.ALLOW,
                        reason="Rubric soft_judge: satisfied",
                    )

            cont = _build_continuation(cfg, session)
            return StopHandlerResult(
                action=StopAction.BLOCK,
                continuation_message=cont,
                reason=(
                    f"Loop '{cfg.name}' iteration "
                    f"{session.iteration_count}"
                ),
            )

        return _handler

    def _make_observer(self, cfg: LoopSkillConfig):
        """Create tool call observer for doom loop detection.

        The returned callable also exposes _doom_loop_state
        so the coordinator can set paused=True on ESCALATE.
        """
        from .doom_loop import DoomLoopState

        detector = DoomLoopDetector(
            window_size=cfg.doom_loop.window_size,
            similarity_threshold=(cfg.doom_loop.similarity_threshold),
            action=cfg.doom_loop.action,
            hitl_message=(
                cfg.doom_loop.hitl_message
                or (f"Agent repeating actions in " f"loop '{cfg.name}'")
            ),
        )
        doom_state = DoomLoopState(detector=detector)

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

        setattr(_observer, "_doom_loop_state", doom_state)
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


def _update_session_tokens(
    session: _LoopSession,
    ctx: Any,
) -> None:
    """Read last-turn token usage and accumulate."""
    try:
        from ..token_usage.model_wrapper import (
            TokenRecordingModelWrapper,
        )

        agent = ctx.get("agent") if isinstance(ctx, dict) else None
        if agent is None:
            return
        rc = getattr(agent, "_request_context", {})
        sid = rc.get("session_id", "")
        if not sid:
            return
        store = getattr(
            TokenRecordingModelWrapper,
            "_usage_by_session",
            {},
        )
        usage = store.get(sid)
        if usage:
            session.total_tokens = usage.get(
                "total_tokens",
                session.total_tokens,
            )
    except Exception:
        pass


def _read_state_file(cfg: LoopSkillConfig) -> dict:
    """Read the loop state JSON file if configured."""
    if cfg.state.mode != "json_file" or not cfg.state.filename:
        return {}
    state_path = Path(_LOOP_STATE_DIR) / cfg.state.filename
    if not state_path.exists():
        return {}
    try:
        return json.loads(
            state_path.read_text(encoding="utf-8"),
        )
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            f"Failed to read state file " f"{state_path}: {exc}",
        )
        return {}


def _eval_hard_check(  # pylint: disable=too-many-return-statements
    cfg: LoopSkillConfig,
    session: _LoopSession,  # pylint: disable=unused-argument
) -> bool:
    """Evaluate hard_check expression against state.

    Supports simple field-based checks:
    - ``field === 'value'``
    - ``items.every(i => i.field)``
    - ``field`` (truthy check)

    Returns True if the expression evaluates as
    satisfied, False otherwise.
    """
    expr = cfg.rubric.check_expression
    state = _read_state_file(cfg)
    if not state:
        return False

    try:
        if ".every(" in expr:
            # Pattern: items.every(i => i.field)
            # Extract array field and check field
            arr_name = expr.split(".every(")[0].strip()
            arr = state.get(arr_name, [])
            if not isinstance(arr, list) or not arr:
                return False
            inner = expr.split("=>")[1].strip().rstrip(")")
            # Support "s.passes || s.blocker_reason"
            if "||" in inner:
                fields = [f.strip().split(".")[-1] for f in inner.split("||")]
                return all(any(item.get(f) for f in fields) for item in arr)
            field = inner.split(".")[-1]
            return all(item.get(field) for item in arr)

        if "===" in expr:
            # Pattern: field === 'value'
            parts = expr.split("===")
            field = parts[0].strip()
            expected = parts[1].strip().strip("'\"")
            return str(state.get(field, "")) == expected

        # Simple truthy check
        return bool(state.get(expr.strip()))
    except Exception as exc:
        logger.debug(
            f"hard_check eval error: {exc}",
        )
        return False


async def _eval_soft_judge(
    cfg: LoopSkillConfig,
    session: _LoopSession,
) -> RubricVerdict:
    """Run soft_judge rubric via LLM grader."""
    prompt = cfg.rubric.soft_judge_prompt
    if not prompt:
        return RubricVerdict.NEEDS_REVISION

    state = _read_state_file(cfg)
    state_str = json.dumps(state, indent=2) if state else "(no state)"

    try:
        rubric = SubAgentRubric(
            fork=cfg.rubric.use_fork,
        )
        result = await rubric.evaluate(
            goal=prompt,
            agent_output=state_str,
            iteration=session.iteration_count,
        )
        return result.verdict
    except Exception as exc:
        logger.warning(
            f"soft_judge grader error: {exc}",
        )
        return RubricVerdict.GRADER_ERROR


def _build_continuation(
    cfg: LoopSkillConfig,
    session: _LoopSession,
) -> str:
    """Build the continuation prompt with variable substitution."""
    safety = cfg.safety
    template = cfg.rubric.continuation_prompt or (
        f"Continue working on the task. "
        f"Iteration {session.iteration_count}"
        f"/{safety.max_iterations}."
    )
    try:
        return template.format(
            iteration=session.iteration_count,
            max_iterations=safety.max_iterations,
            tokens_used=session.total_tokens,
            phase=_read_state_file(cfg).get(
                "phase",
                "unknown",
            ),
        )
    except (KeyError, IndexError):
        return template


__all__ = ["LoopLoader"]
