# -*- coding: utf-8 -*-
"""Tests for agent ID generation, sanitization, and validation."""
import pytest

from qwenpaw.config.config import (
    generate_short_agent_id,
    sanitize_agent_id,
    validate_agent_id,
)


def test_generate_short_agent_id_length():
    """Test that generated agent ID has correct length."""
    agent_id = generate_short_agent_id()
    assert len(agent_id) == 6
    assert isinstance(agent_id, str)


def test_generate_short_agent_id_unique():
    """Test that generated agent IDs are unique."""
    ids = {generate_short_agent_id() for _ in range(100)}
    # With 100 generations, we should get at least 95 unique IDs
    # (allowing for some collisions in the random space)
    assert len(ids) >= 95


def test_generate_short_agent_id_alphanumeric():
    """Test that generated agent ID contains only alphanumeric chars."""
    agent_id = generate_short_agent_id()
    # shortuuid uses base57 alphabet by default
    # (0-9, A-Z, a-z minus ambiguous chars like I, l, O, 0, etc.)
    assert agent_id.isalnum()


# --- sanitize_agent_id ---


def test_sanitize_strips_whitespace():
    """Test sanitize_agent_id strips whitespace."""
    assert sanitize_agent_id("  Browse-Agent  ") == "Browse-Agent"
    assert sanitize_agent_id("MY_BOT") == "MY_BOT"
    assert sanitize_agent_id("hello") == "hello"


def test_sanitize_empty_string():
    """Test sanitize_agent_id with empty / whitespace-only input."""
    assert sanitize_agent_id("") == ""
    assert sanitize_agent_id("   ") == ""


# --- validate_agent_id ---


@pytest.mark.parametrize(
    "agent_id",
    [
        "browse-agent",
        "my_bot_v2",
        "a1",
        "agent123",
        "Browse-Agent",
        "MY_BOT",
    ],
)
def test_validate_valid_ids(agent_id):
    """Test that well-formed IDs pass validation."""
    validate_agent_id(agent_id, set())


@pytest.mark.parametrize(
    "agent_id,expected_msg",
    [
        ("a", "at least 2 characters"),
        ("", "at least 2 characters"),
    ],
)
def test_validate_too_short(agent_id, expected_msg):
    """Test that IDs shorter than 2 chars are rejected."""
    with pytest.raises(ValueError, match=expected_msg):
        validate_agent_id(agent_id, set())


def test_validate_too_long():
    """Test that IDs longer than 64 chars are rejected."""
    long_id = "a" * 65
    with pytest.raises(ValueError, match="at most 64 characters"):
        validate_agent_id(long_id, set())


@pytest.mark.parametrize(
    "agent_id",
    [
        "Browse Agent",  # space
        "中文名",  # non-ASCII
        "special!chars",  # special chars
        "-starts-dash",  # starts with dash
        "_starts-under",  # starts with underscore
        "ends-dash-",  # ends with dash
        "ends_under_",  # ends with underscore
    ],
)
def test_validate_invalid_pattern(agent_id):
    """Test that IDs with invalid characters are rejected."""
    with pytest.raises(ValueError, match="invalid characters"):
        validate_agent_id(agent_id, set())


def test_validate_reserved_id():
    """Test that reserved IDs are rejected."""
    with pytest.raises(ValueError, match="reserved"):
        validate_agent_id("default", set())


def test_validate_duplicate_id():
    """Test that duplicate IDs are rejected."""
    existing = {"browse-agent", "my-bot"}
    with pytest.raises(ValueError, match="already exists"):
        validate_agent_id("browse-agent", existing)


def test_validate_ok_when_no_conflict():
    """Test that a valid ID passes when there is no conflict."""
    existing = {"other-agent"}
    validate_agent_id("browse-agent", existing)  # should not raise
