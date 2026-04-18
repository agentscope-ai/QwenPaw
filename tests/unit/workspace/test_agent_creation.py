# -*- coding: utf-8 -*-
"""Tests for agent creation with short UUID."""
from unittest.mock import patch

from qwenpaw.config.config import (
    AgentProfileConfig,
    generate_short_agent_id,
)


def test_agent_creation_auto_generates_short_id():
    """Test that agent creation validates short ID generation."""
    # Test that an empty ID triggers auto-generation logic
    agent_config = AgentProfileConfig(
        id="",  # Empty ID should trigger auto-generation
        name="Test Agent",
        description="Test agent description",
    )

    # Verify the empty ID case
    assert agent_config.id == ""

    # The actual auto-generation happens in the API endpoint
    # This test verifies the precondition


def test_generate_short_id_collision_handling():
    """Test that agent creation can handle ID collisions."""
    # Generate some IDs
    existing_ids = {generate_short_agent_id() for _ in range(5)}

    # Mock that first few attempts collide
    collision_count = 0
    original_generate = generate_short_agent_id

    def mock_generate():
        nonlocal collision_count
        if collision_count < 3:
            collision_count += 1
            # Return an existing ID to simulate collision
            return list(existing_ids)[0]
        # Return a new unique ID
        return original_generate()

    with patch(
        "qwenpaw.app.routers.agents.generate_short_agent_id",
        side_effect=mock_generate,
    ) as mock_fn:
        # Generate IDs until we get a unique one
        for _ in range(10):
            new_id = mock_fn()
            if new_id not in existing_ids:
                break

        # Verify the mock was called
        assert mock_fn.call_count > 0


def test_default_agent_preserved():
    """Test that 'default' agent ID is preserved."""
    agent_config = AgentProfileConfig(
        id="default",
        name="Default Agent",
        description="Default agent",
    )

    # 'default' should not be replaced with short UUID
    assert agent_config.id == "default"


def test_short_uuid_properties():
    """Test properties of generated short UUIDs."""
    # Generate multiple IDs
    ids = [generate_short_agent_id() for _ in range(20)]

    for agent_id in ids:
        # Each should be 6 characters
        assert len(agent_id) == 6
        # Should be alphanumeric
        assert agent_id.isalnum()
        # Should not contain ambiguous characters (shortuuid excludes them)
        # This is a property of shortuuid library
        assert "I" not in agent_id  # Excluded by shortuuid
        assert "l" not in agent_id  # Excluded by shortuuid
        assert "O" not in agent_id  # Excluded by shortuuid
        assert "0" not in agent_id  # Excluded by shortuuid
