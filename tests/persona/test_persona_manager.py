# -*- coding: utf-8 -*-
"""Tests for PersonaManager and PersonaSpec."""
import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path

from copaw.agents.persona import PersonaManager, PersonaScope, PersonaSpec


@pytest.fixture
def temp_personas_dir():
    """Create a temporary directory for persona tests."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def persona_manager(temp_personas_dir):
    """Create a PersonaManager with temporary storage."""
    manager = PersonaManager(save_dir=temp_personas_dir)
    return manager


@pytest.mark.asyncio
async def test_create_persona_global(persona_manager):
    """Test creating a global persona."""
    persona = await persona_manager.create_persona(
        name="Default Assistant",
        description="A helpful assistant",
        system_prompt_addon="You are a helpful assistant.",
        scope=PersonaScope.GLOBAL,
    )

    assert persona.name == "Default Assistant"
    assert persona.scope == PersonaScope.GLOBAL
    assert persona.enabled is True
    assert persona.id is not None

    # Verify it was saved
    loaded = await persona_manager.get_persona(persona.id)
    assert loaded is not None
    assert loaded.name == "Default Assistant"


@pytest.mark.asyncio
async def test_create_persona_channel(persona_manager):
    """Test creating a channel-specific persona."""
    persona = await persona_manager.create_persona(
        name="工作助手",
        description="专业的职场助手",
        system_prompt_addon="使用正式、专业的语言。",
        scope=PersonaScope.CHANNEL,
        channel="dingtalk",
    )

    assert persona.scope == PersonaScope.CHANNEL
    assert persona.channel == "dingtalk"
    assert persona.name == "工作助手"


@pytest.mark.asyncio
async def test_create_persona_user(persona_manager):
    """Test creating a user-specific persona."""
    persona = await persona_manager.create_persona(
        name="投资顾问",
        description="个人投资助手",
        scope=PersonaScope.USER,
        user_id="user123",
    )

    assert persona.scope == PersonaScope.USER
    assert persona.user_id == "user123"


@pytest.mark.asyncio
async def test_create_persona_user_channel(persona_manager):
    """Test creating a user-channel persona."""
    persona = await persona_manager.create_persona(
        name="老师",
        description="孩子的教育助手",
        scope=PersonaScope.USER_CHANNEL,
        channel="imessage",
        user_id="child123",
    )

    assert persona.scope == PersonaScope.USER_CHANNEL
    assert persona.channel == "imessage"
    assert persona.user_id == "child123"


@pytest.mark.asyncio
async def test_create_persona_validation(persona_manager):
    """Test validation when creating personas."""
    # CHANNEL scope requires channel
    with pytest.raises(ValueError, match="channel is required"):
        await persona_manager.create_persona(
            name="Test",
            description="Test",
            scope=PersonaScope.CHANNEL,
        )

    # USER scope requires user_id
    with pytest.raises(ValueError, match="user_id is required"):
        await persona_manager.create_persona(
            name="Test",
            description="Test",
            scope=PersonaScope.USER,
        )

    # USER_CHANNEL scope requires both
    with pytest.raises(ValueError, match="channel is required"):
        await persona_manager.create_persona(
            name="Test",
            description="Test",
            scope=PersonaScope.USER_CHANNEL,
        )


@pytest.mark.asyncio
async def test_delete_persona(persona_manager):
    """Test deleting a persona."""
    persona = await persona_manager.create_persona(
        name="To Delete",
        description="Will be deleted",
    )

    # Delete it
    deleted = await persona_manager.delete_persona(persona.id)
    assert deleted is True

    # Verify it's gone
    loaded = await persona_manager.get_persona(persona.id)
    assert loaded is None

    # Deleting non-existent returns False
    result = await persona_manager.delete_persona("non-existent-id")
    assert result is False


@pytest.mark.asyncio
async def test_update_persona(persona_manager):
    """Test updating a persona."""
    persona = await persona_manager.create_persona(
        name="Original",
        description="Original description",
        system_prompt_addon="Original prompt",
    )

    # Update name and description
    updated = await persona_manager.update_persona(
        persona.id,
        name="Updated",
        description="Updated description",
    )

    assert updated is not None
    assert updated.name == "Updated"
    assert updated.description == "Updated description"

    # Update enabled status
    updated = await persona_manager.update_persona(
        persona.id,
        enabled=False,
    )
    assert updated is not None
    assert updated.enabled is False


@pytest.mark.asyncio
async def test_enable_disable_persona(persona_manager):
    """Test enabling and disabling personas."""
    persona = await persona_manager.create_persona(
        name="Test Persona",
        description="Test",
        enabled=True,
    )

    # Disable it
    result = await persona_manager.disable_persona(persona.id)
    assert result is True

    loaded = await persona_manager.get_persona(persona.id)
    assert loaded.enabled is False

    # Enable again
    result = await persona_manager.enable_persona(persona.id)
    assert result is True

    loaded = await persona_manager.get_persona(persona.id)
    assert loaded.enabled is True


@pytest.mark.asyncio
async def test_list_personas(persona_manager):
    """Test listing personas with filters."""
    await persona_manager.create_persona(name="Global", description="G")
    await persona_manager.create_persona(name="DingTalk", description="D", channel="dingtalk", scope=PersonaScope.CHANNEL)
    await persona_manager.create_persona(name="Feishu", description="F", channel="feishu", scope=PersonaScope.CHANNEL)

    # List all
    all_personas = await persona_manager.list_personas()
    assert len(all_personas) == 3

    # List only GLOBAL
    global_personas = await persona_manager.list_personas(scope=PersonaScope.GLOBAL)
    assert len(global_personas) == 1

    # Add disabled persona
    disabled = await persona_manager.create_persona(
        name="Disabled",
        description="X",
        enabled=False,
    )

    # enabled_only=True excludes it
    enabled = await persona_manager.list_personas(enabled_only=True)
    assert len(enabled) == 3

    # enabled_only=False includes it
    all_with_disabled = await persona_manager.list_personas(enabled_only=False)
    assert len(all_with_disabled) == 4


@pytest.mark.asyncio
async def test_get_active_persona_priority(persona_manager):
    """Test getting active persona with priority selection."""
    # Create personas with different scopes
    await persona_manager.create_persona(
        name="Global",
        description="Global persona",
        scope=PersonaScope.GLOBAL,
    )
    await persona_manager.create_persona(
        name="DingTalk",
        description="DingTalk persona",
        scope=PersonaScope.CHANNEL,
        channel="dingtalk",
    )
    await persona_manager.create_persona(
        name="User",
        description="User persona",
        scope=PersonaScope.USER,
        user_id="user123",
    )
    await persona_manager.create_persona(
        name="User+DingTalk",
        description="User+Channel persona",
        scope=PersonaScope.USER_CHANNEL,
        channel="dingtalk",
        user_id="user123",
    )

    # Get persona for dingtalk/user123
    active = await persona_manager.get_active_persona(
        channel="dingtalk",
        user_id="user123",
    )

    # Should get USER_CHANNEL (highest priority)
    assert active.name == "User+DingTalk"

    # Get persona for feishu/user123
    active = await persona_manager.get_active_persona(
        channel="feishu",
        user_id="user123",
    )

    # Should get USER (user123 applies to all channels)
    assert active.name == "User"

    # Get persona for feishu/other-user
    active = await persona_manager.get_active_persona(
        channel="feishu",
        user_id="other-user",
    )

    # Should get GLOBAL
    assert active.name == "Global"


@pytest.mark.asyncio
async def test_persona_is_applicable_to():
    """Test PersonaSpec.is_applicable_to method."""
    # Global persona
    global_p = PersonaSpec(
        name="Global",
        description="Global",
        system_prompt_addon="",
        scope=PersonaScope.GLOBAL,
    )
    assert global_p.is_applicable_to(channel="dingtalk", user_id="user1")

    # Disabled persona
    disabled_p = PersonaSpec(
        name="Disabled",
        description="Disabled",
        system_prompt_addon="",
        enabled=False,
    )
    assert disabled_p.is_applicable_to() is False

    # Channel-specific
    channel_p = PersonaSpec(
        name="Channel",
        description="Channel",
        system_prompt_addon="",
        scope=PersonaScope.CHANNEL,
        channel="dingtalk",
    )
    assert channel_p.is_applicable_to(channel="dingtalk") is True
    assert channel_p.is_applicable_to(channel="feishu") is False

    # User-specific
    user_p = PersonaSpec(
        name="User",
        description="User",
        system_prompt_addon="",
        scope=PersonaScope.USER,
        user_id="user123",
    )
    assert user_p.is_applicable_to(user_id="user123") is True
    assert user_p.is_applicable_to(user_id="user456") is False

    # User+Channel
    uc_p = PersonaSpec(
        name="UC",
        description="UC",
        system_prompt_addon="",
        scope=PersonaScope.USER_CHANNEL,
        channel="dingtalk",
        user_id="user123",
    )
    assert uc_p.is_applicable_to(channel="dingtalk", user_id="user123") is True
    assert uc_p.is_applicable_to(channel="feishu", user_id="user123") is False


@pytest.mark.asyncio
async def test_get_priority_score():
    """Test PersonaSpec.get_priority_score method."""
    global_p = PersonaSpec(
        name="Global",
        description="Global",
        system_prompt_addon="",
        scope=PersonaScope.GLOBAL,
    )
    assert global_p.get_priority_score(channel="d", user_id="u") == 1

    channel_p = PersonaSpec(
        name="Channel",
        description="Channel",
        system_prompt_addon="",
        scope=PersonaScope.CHANNEL,
        channel="dingtalk",
    )
    assert channel_p.get_priority_score(channel="dingtalk", user_id="u") == 2
    assert channel_p.get_priority_score(channel="feishu", user_id="u") == 0

    user_p = PersonaSpec(
        name="User",
        description="User",
        system_prompt_addon="",
        scope=PersonaScope.USER,
        user_id="user123",
    )
    assert user_p.get_priority_score(channel="d", user_id="user123") == 3

    uc_p = PersonaSpec(
        name="UC",
        description="UC",
        system_prompt_addon="",
        scope=PersonaScope.USER_CHANNEL,
        channel="dingtalk",
        user_id="user123",
    )
    assert uc_p.get_priority_score(channel="dingtalk", user_id="user123") == 4


@pytest.mark.asyncio
async def test_persistence(persona_manager, temp_personas_dir):
    """Test personas are persisted to disk."""
    persona = await persona_manager.create_persona(
        name="Persistent",
        description="Test persistence",
        system_prompt_addon="Test prompt",
    )

    # Verify file exists
    personas_file = Path(temp_personas_dir) / "personas.json"
    assert personas_file.exists()

    # Create new manager and load
    new_manager = PersonaManager(save_dir=temp_personas_dir)
    await new_manager.load()

    # Verify persona was loaded
    loaded = await new_manager.get_persona(persona.id)
    assert loaded is not None
    assert loaded.name == "Persistent"
    assert loaded.system_prompt_addon == "Test prompt"


@pytest.mark.asyncio
async def test_clear_all_personas(persona_manager):
    """Test clearing all personas."""
    await persona_manager.create_persona(name="P1", description="D1")
    await persona_manager.create_persona(name="P2", description="D2")
    await persona_manager.create_persona(name="P3", description="D3")

    await persona_manager.clear_all()

    personas = await persona_manager.list_personas()
    assert len(personas) == 0
