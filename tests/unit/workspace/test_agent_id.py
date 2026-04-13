# -*- coding: utf-8 -*-
"""Tests for agent ID generation and short UUID functionality."""
from qwenpaw.config.config import generate_short_agent_id


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
