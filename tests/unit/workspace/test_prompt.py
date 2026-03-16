# -*- coding: utf-8 -*-
"""Tests for agent identity in system prompt."""
import tempfile
from pathlib import Path
import pytest
from copaw.agents.prompt import build_system_prompt_from_working_dir


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        yield workspace


def test_prompt_without_agent_id(temp_workspace):  # pylint: disable=W0621
    """Test system prompt without agent_id."""
    # Create a simple AGENTS.md
    agents_md = temp_workspace / "AGENTS.md"
    agents_md.write_text("You are a helpful assistant.", encoding="utf-8")

    prompt = build_system_prompt_from_working_dir(
        working_dir=temp_workspace,
        agent_id=None,
    )

    assert "You are a helpful assistant" in prompt
    assert "Agent Identity" not in prompt
    assert "You are agent" not in prompt


def test_prompt_with_default_agent_id(
    temp_workspace,
):  # pylint: disable=W0621
    """Test system prompt with 'default' agent_id."""
    agents_md = temp_workspace / "AGENTS.md"
    agents_md.write_text("You are a helpful assistant.", encoding="utf-8")

    prompt = build_system_prompt_from_working_dir(
        working_dir=temp_workspace,
        agent_id="default",
    )

    # 'default' is special and should not add identity header
    assert "You are a helpful assistant" in prompt
    assert "Agent Identity" not in prompt


def test_prompt_with_custom_agent_id(
    temp_workspace,
):  # pylint: disable=W0621
    """Test system prompt with custom agent_id."""
    agents_md = temp_workspace / "AGENTS.md"
    agents_md.write_text("You are a helpful assistant.", encoding="utf-8")

    prompt = build_system_prompt_from_working_dir(
        working_dir=temp_workspace,
        agent_id="abc123",
    )

    # Custom agent should have identity header
    assert "Agent Identity" in prompt
    assert "Your agent id is `abc123`" in prompt
    assert "You are a helpful assistant" in prompt
    # Identity should be at the beginning
    assert prompt.index("Agent Identity") < prompt.index("helpful assistant")


def test_prompt_with_empty_workspace(
    temp_workspace,
):  # pylint: disable=W0621
    """Test system prompt with empty workspace."""
    prompt = build_system_prompt_from_working_dir(
        working_dir=temp_workspace,
        agent_id="xyz789",
    )

    # Should still add identity header even with no markdown files
    assert "Agent Identity" in prompt
    assert "Your agent id is `xyz789`" in prompt


def test_prompt_identity_format(temp_workspace):  # pylint: disable=W0621
    """Test the exact format of identity header."""
    prompt = build_system_prompt_from_working_dir(
        working_dir=temp_workspace,
        agent_id="test99",
    )

    expected_header = (
        "# Agent Identity\n\n"
        "Your agent id is `test99`. "
        "This is your unique identifier in the multi-agent system.\n\n"
    )
    assert expected_header in prompt
