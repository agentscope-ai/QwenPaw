# -*- coding: utf-8 -*-
"""Tests for Goal Mode terminal-state prompt and tools."""
from __future__ import annotations

import inspect
from types import SimpleNamespace

from qwenpaw.app.agent_context import scoped_session_id
from qwenpaw.modes.goal.contributor import GoalPromptContributor
from qwenpaw.modes.goal.goal_mode import GoalMode, GoalSession
from qwenpaw.modes.goal.tools import make_update_goal
from qwenpaw.runtime.prompt_contributors import build_default_prompt_manager


def _goal_mode(session_id: str = "goal-test") -> tuple[GoalMode, GoalSession]:
    """Create one Goal Mode with an active session."""
    mode = GoalMode()
    session = GoalSession(goal="Finish the requested work")
    mode.sessions[session_id] = session
    return mode, session


def test_goal_prompts_describe_complete_and_blocked_terminals():
    """Initial and continuation prompts expose both terminal states."""
    mode, session = _goal_mode()

    with scoped_session_id("goal-test"):
        initial = mode.prompt_provider(None)
        session.iteration = 1
        continuation = mode.prompt_provider(None)

    for prompt in (initial, continuation):
        assert 'update_goal(status="complete")' in prompt
        assert 'update_goal(status="blocked")' in prompt
        assert "three consecutive goal turns" in prompt
        assert "one ordinary tool failure" in prompt
        assert "materially different safe approach" in prompt


def test_goal_prompt_follows_protected_execution_contract(tmp_path):
    """The more specific goal contract appears after the base contract."""
    mode, _session = _goal_mode()
    manager = build_default_prompt_manager()
    manager.register(GoalPromptContributor(owner=mode))
    ctx = SimpleNamespace(
        workspace_dir=str(tmp_path),
        agent_id="test-agent",
        extras={
            "agent_config": SimpleNamespace(system_prompt_files=[]),
        },
    )

    with scoped_session_id("goal-test"):
        prompt = manager.build_sync(ctx)

    assert prompt.index("# Task execution contract") < prompt.index(
        "You are now in goal mode",
    )


def test_update_goal_descriptor_matches_blocked_conditions():
    """Tool schema and callable docstring teach the same blocker rules."""
    mode = GoalMode()
    descriptor = next(
        item for item in mode.tools() if item.name == "update_goal"
    )
    docstring = inspect.getdoc(descriptor.func) or ""

    for raw_text in (descriptor.description, docstring):
        text = " ".join(raw_text.split())
        assert "user input" in text
        assert "approval" in text
        assert "new authority" in text
        assert "unavailable external state" in text
        assert "three consecutive goal turns" in text
        assert "materially different safe approach" in text


def test_update_goal_blocked_preserves_terminal_session():
    """Blocked remains available to the goal gate as an inactive session."""
    mode, session = _goal_mode()

    with scoped_session_id("goal-test"):
        result = make_update_goal(mode)("blocked")

    assert result == "Goal marked as blocked. The user will be notified."
    assert not session.active
    assert session.last_verdict == "blocked"
    assert mode.get_session("goal-test") is session


def test_update_goal_complete_removes_session():
    """Complete retains the existing session cleanup behavior."""
    mode, session = _goal_mode()

    with scoped_session_id("goal-test"):
        result = make_update_goal(mode)("complete")

    assert result == "Goal marked as complete. Iterations used: 0"
    assert not session.active
    assert session.last_verdict == "satisfied"
    assert mode.get_session("goal-test") is None


def test_update_goal_rejects_invalid_status_without_mutation():
    """An invalid status leaves the active goal unchanged."""
    mode, session = _goal_mode()

    with scoped_session_id("goal-test"):
        result = make_update_goal(mode)("waiting")

    assert result == (
        "Invalid status 'waiting'. Must be 'complete' or 'blocked'."
    )
    assert session.active
    assert session.last_verdict == ""
