# -*- coding: utf-8 -*-
"""Tests for BootstrapHook.

Covers:
- Initialization
- __call__ early-exit branches (flag, missing file, not first interaction)
- Happy path: guidance prepended, flag created
- System message skipping
- Exception handling
"""
# pylint: disable=redefined-outer-name
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def working_dir(tmp_path: Path) -> Path:
    """Provide an isolated working directory."""
    return tmp_path


@pytest.fixture
def hook(working_dir):
    """Create a BootstrapHook with default (zh) language."""
    from qwenpaw.agents.hooks.bootstrap import BootstrapHook

    return BootstrapHook(working_dir=working_dir)


@pytest.fixture
def mock_agent():
    """Create a mock agent with async memory.get_memory."""
    agent = MagicMock()
    agent.memory.get_memory = AsyncMock(return_value=[])
    return agent


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestBootstrapHookInit:
    """P0: __init__ tests."""

    def test_stores_working_dir(self, working_dir):
        from qwenpaw.agents.hooks.bootstrap import BootstrapHook

        hook = BootstrapHook(working_dir=working_dir)
        assert hook.working_dir == working_dir

    def test_default_language_is_zh(self, working_dir):
        from qwenpaw.agents.hooks.bootstrap import BootstrapHook

        hook = BootstrapHook(working_dir=working_dir)
        assert hook.language == "zh"

    def test_custom_language_stored(self, working_dir):
        from qwenpaw.agents.hooks.bootstrap import BootstrapHook

        hook = BootstrapHook(working_dir=working_dir, language="en")
        assert hook.language == "en"


# ---------------------------------------------------------------------------
# __call__ — early-exit branches
# ---------------------------------------------------------------------------


class TestBootstrapHookCallEarlyExit:
    """P1: __call__ returns None without side-effects."""

    async def test_returns_none_when_completed_flag_exists(
        self,
        hook,
        mock_agent,
    ):
        """Already bootstrapped: flag present → skip entirely."""
        (hook.working_dir / ".bootstrap_completed").touch()
        result = await hook(mock_agent, {})
        assert result is None
        mock_agent.memory.get_memory.assert_not_called()

    async def test_returns_none_when_bootstrap_md_missing(
        self,
        hook,
        mock_agent,
    ):
        """No BOOTSTRAP.md → skip entirely."""
        result = await hook(mock_agent, {})
        assert result is None
        mock_agent.memory.get_memory.assert_not_called()

    async def test_returns_none_when_not_first_interaction(
        self,
        hook,
        mock_agent,
    ):
        """Not first interaction → skip guidance."""
        (hook.working_dir / "BOOTSTRAP.md").write_text("# Bootstrap")
        with patch(
            "qwenpaw.agents.hooks.bootstrap.is_first_user_interaction",
            return_value=False,
        ):
            result = await hook(mock_agent, {})
        assert result is None


# ---------------------------------------------------------------------------
# __call__ — happy path
# ---------------------------------------------------------------------------


class TestBootstrapHookCallHappyPath:
    """P1: __call__ applies guidance and creates flag."""

    def _user_msg(self):
        msg = MagicMock()
        msg.role = "user"
        return msg

    async def test_prepends_guidance_to_first_user_message(
        self,
        hook,
        mock_agent,
    ):
        (hook.working_dir / "BOOTSTRAP.md").write_text("# Bootstrap")
        user_msg = self._user_msg()
        mock_agent.memory.get_memory = AsyncMock(
            return_value=[user_msg],
        )

        with patch(
            "qwenpaw.agents.hooks.bootstrap.is_first_user_interaction",
            return_value=True,
        ), patch(
            "qwenpaw.agents.hooks.bootstrap.build_bootstrap_guidance",
            return_value="guidance text",
        ) as mock_build, patch(
            "qwenpaw.agents.hooks.bootstrap.prepend_to_message_content",
        ) as mock_prepend:
            result = await hook(mock_agent, {})

        assert result is None
        mock_build.assert_called_once_with("zh")
        mock_prepend.assert_called_once_with(user_msg, "guidance text")

    async def test_creates_completed_flag_after_success(
        self,
        hook,
        mock_agent,
    ):
        (hook.working_dir / "BOOTSTRAP.md").write_text("# Bootstrap")
        user_msg = self._user_msg()
        mock_agent.memory.get_memory = AsyncMock(
            return_value=[user_msg],
        )

        with patch(
            "qwenpaw.agents.hooks.bootstrap.is_first_user_interaction",
            return_value=True,
        ), patch(
            "qwenpaw.agents.hooks.bootstrap.build_bootstrap_guidance",
            return_value="guidance",
        ), patch(
            "qwenpaw.agents.hooks.bootstrap.prepend_to_message_content",
        ):
            await hook(mock_agent, {})

        flag = hook.working_dir / ".bootstrap_completed"
        assert flag.exists()

    async def test_skips_system_messages_prepends_first_user(
        self,
        hook,
        mock_agent,
    ):
        """System messages before first user msg are skipped."""
        (hook.working_dir / "BOOTSTRAP.md").write_text("# Bootstrap")
        sys_msg = MagicMock()
        sys_msg.role = "system"
        user_msg = self._user_msg()
        mock_agent.memory.get_memory = AsyncMock(
            return_value=[sys_msg, user_msg],
        )

        with patch(
            "qwenpaw.agents.hooks.bootstrap.is_first_user_interaction",
            return_value=True,
        ), patch(
            "qwenpaw.agents.hooks.bootstrap.build_bootstrap_guidance",
            return_value="guidance",
        ), patch(
            "qwenpaw.agents.hooks.bootstrap.prepend_to_message_content",
        ) as mock_prepend:
            await hook(mock_agent, {})

        mock_prepend.assert_called_once_with(user_msg, "guidance")

    async def test_uses_hook_language_for_guidance(self, working_dir):
        from qwenpaw.agents.hooks.bootstrap import BootstrapHook

        hook_en = BootstrapHook(working_dir=working_dir, language="en")
        (working_dir / "BOOTSTRAP.md").write_text("# Bootstrap")
        user_msg = MagicMock()
        user_msg.role = "user"
        agent = MagicMock()
        agent.memory.get_memory = AsyncMock(return_value=[user_msg])

        with patch(
            "qwenpaw.agents.hooks.bootstrap.is_first_user_interaction",
            return_value=True,
        ), patch(
            "qwenpaw.agents.hooks.bootstrap.build_bootstrap_guidance",
            return_value="en guidance",
        ) as mock_build, patch(
            "qwenpaw.agents.hooks.bootstrap.prepend_to_message_content",
        ):
            await hook_en(agent, {})

        mock_build.assert_called_once_with("en")


# ---------------------------------------------------------------------------
# __call__ — exception handling
# ---------------------------------------------------------------------------


class TestBootstrapHookCallException:
    """P2: exceptions are swallowed, None is returned."""

    async def test_handles_memory_error_gracefully(
        self,
        hook,
        mock_agent,
    ):
        (hook.working_dir / "BOOTSTRAP.md").write_text("# Bootstrap")
        mock_agent.memory.get_memory = AsyncMock(
            side_effect=RuntimeError("memory error"),
        )
        result = await hook(mock_agent, {})
        assert result is None

    async def test_always_returns_none(self, hook, mock_agent):
        """Return value is always None regardless of kwargs."""
        result = await hook(mock_agent, {"irrelevant": "kwargs"})
        assert result is None
