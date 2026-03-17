# -*- coding: utf-8 -*-
"""Configuration migration utilities for multi-agent support.

Handles migration from legacy single-agent config to new multi-agent structure.
"""
import json
import logging
import shutil
from pathlib import Path

from ..config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    AgentsConfig,
    AgentsRunningConfig,
    AgentsLLMRoutingConfig,
)
from ..config.utils import load_config, save_config

logger = logging.getLogger(__name__)


def migrate_legacy_workspace_to_default_agent() -> bool:
    """Migrate legacy single-agent workspace to default agent workspace.

    This function:
    1. Checks if migration is needed
    2. Creates default agent workspace
    3. Migrates sessions, memory, and markdown files
    4. Creates agent.json with legacy configuration
    5. Updates root config.json to new structure

    Returns:
        bool: True if migration was performed, False if already migrated
    """
    try:
        config = load_config()
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return False

    # Check if already migrated
    # Skip if:
    # 1. Multiple agents already exist (multi-agent config), OR
    # 2. Default agent has agent.json (already migrated)
    if len(config.agents.profiles) > 1:
        logger.debug(
            f"Multi-agent config already exists "
            f"({len(config.agents.profiles)} agents), skipping migration",
        )
        return False

    if "default" in config.agents.profiles:
        agent_ref = config.agents.profiles["default"]
        if isinstance(agent_ref, AgentProfileRef):
            workspace_dir = Path(agent_ref.workspace_dir).expanduser()
            agent_config_path = workspace_dir / "agent.json"
            if agent_config_path.exists():
                logger.debug(
                    "Default agent already migrated, skipping migration",
                )
                return False

    logger.info("=" * 60)
    logger.info("Migrating legacy config to multi-agent structure...")
    logger.info("=" * 60)

    # Extract legacy agent configuration
    legacy_agents = config.agents

    # Create default agent workspace
    default_workspace = Path("~/.copaw/workspaces/default").expanduser()
    default_workspace.mkdir(parents=True, exist_ok=True)
    logger.info(f"Created default agent workspace: {default_workspace}")

    # Build default agent configuration from legacy settings
    default_agent_config = AgentProfileConfig(
        id="default",
        name="Default Agent",
        description="Default CoPaw agent (migrated from legacy config)",
        workspace_dir=str(default_workspace),
        channels=config.channels if hasattr(config, "channels") else None,
        mcp=config.mcp if hasattr(config, "mcp") else None,
        heartbeat=(
            legacy_agents.defaults.heartbeat
            if hasattr(legacy_agents, "defaults") and legacy_agents.defaults
            else None
        ),
        running=(
            legacy_agents.running
            if hasattr(legacy_agents, "running") and legacy_agents.running
            else AgentsRunningConfig()
        ),
        llm_routing=(
            legacy_agents.llm_routing
            if hasattr(legacy_agents, "llm_routing")
            and legacy_agents.llm_routing
            else AgentsLLMRoutingConfig()
        ),
        system_prompt_files=(
            legacy_agents.system_prompt_files
            if hasattr(legacy_agents, "system_prompt_files")
            and legacy_agents.system_prompt_files
            else ["AGENTS.md", "SOUL.md", "PROFILE.md"]
        ),
        tools=config.tools if hasattr(config, "tools") else None,
        security=config.security if hasattr(config, "security") else None,
    )

    # Save default agent configuration to workspace/agent.json
    agent_config_path = default_workspace / "agent.json"
    with open(agent_config_path, "w", encoding="utf-8") as f:
        json.dump(
            default_agent_config.model_dump(exclude_none=True),
            f,
            ensure_ascii=False,
            indent=2,
        )
    logger.info(f"Created agent config: {agent_config_path}")

    # Migrate existing workspace files to default agent workspace
    old_workspace = Path("~/.copaw").expanduser()

    migrated_items = []

    # Migrate sessions directory
    _migrate_workspace_item(
        old_workspace / "sessions",
        default_workspace / "sessions",
        "sessions",
        migrated_items,
    )

    # Migrate memory directory
    _migrate_workspace_item(
        old_workspace / "memory",
        default_workspace / "memory",
        "memory",
        migrated_items,
    )

    # Migrate chats.json
    _migrate_workspace_item(
        old_workspace / "chats.json",
        default_workspace / "chats.json",
        "chats.json",
        migrated_items,
    )

    # Migrate jobs.json
    _migrate_workspace_item(
        old_workspace / "jobs.json",
        default_workspace / "jobs.json",
        "jobs.json",
        migrated_items,
    )

    # Migrate markdown files
    for md_file in [
        "AGENTS.md",
        "SOUL.md",
        "PROFILE.md",
        "HEARTBEAT.md",
        "MEMORY.md",
        "BOOTSTRAP.md",
    ]:
        _migrate_workspace_item(
            old_workspace / md_file,
            default_workspace / md_file,
            md_file,
            migrated_items,
        )

    # Migrate channel-specific configuration files
    _migrate_workspace_item(
        old_workspace / "feishu_receive_ids.json",
        default_workspace / "feishu_receive_ids.json",
        "feishu_receive_ids.json",
        migrated_items,
    )

    _migrate_workspace_item(
        old_workspace / "dingtalk_session_webhooks.json",
        default_workspace / "dingtalk_session_webhooks.json",
        "dingtalk_session_webhooks.json",
        migrated_items,
    )

    if migrated_items:
        logger.info(f"Migrated workspace items: {', '.join(migrated_items)}")

    # Update root config.json to new structure
    # CRITICAL: Preserve legacy agent fields in root config for downgrade
    # compatibility. Old versions expect these fields to have valid values.
    config.agents = AgentsConfig(
        active_agent="default",
        profiles={
            "default": AgentProfileRef(
                id="default",
                workspace_dir=str(default_workspace),
            ),
        },
        # Preserve legacy fields with values from migrated agent config
        running=default_agent_config.running,
        llm_routing=default_agent_config.llm_routing,
        language=default_agent_config.language,
        system_prompt_files=default_agent_config.system_prompt_files,
    )

    # IMPORTANT: Keep original config fields in root config.json for
    # backward compatibility. If user downgrades, old version can still
    # use these fields. New version will prioritize agent.json.
    # DO NOT clear: channels, mcp, tools, security fields

    save_config(config)
    logger.info(
        "Updated root config.json to multi-agent structure "
        "(kept original fields for backward compatibility)",
    )

    logger.info("=" * 60)
    logger.info("Migration completed successfully!")
    logger.info(f"  Default agent workspace: {default_workspace}")
    logger.info(f"  Default agent config: {agent_config_path}")
    logger.info("=" * 60)

    return True


def _migrate_workspace_item(
    old_path: Path,
    new_path: Path,
    item_name: str,
    migrated_items: list,
) -> None:
    """Migrate a single workspace item (file or directory).

    Args:
        old_path: Source path
        new_path: Destination path
        item_name: Name for logging
        migrated_items: List to append migrated item names
    """
    if not old_path.exists():
        return

    if new_path.exists():
        logger.debug(f"Skipping {item_name} (already exists in new location)")
        return

    try:
        if old_path.is_dir():
            shutil.copytree(old_path, new_path)
        else:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old_path, new_path)

        migrated_items.append(item_name)
        logger.debug(f"Migrated {item_name}")
    except Exception as e:
        logger.warning(f"Failed to migrate {item_name}: {e}")


def ensure_default_agent_exists() -> None:
    """Ensure that the default agent exists in config.

    This function is called on startup to verify the default agent
    is properly configured. If not, it will be created.
    Also ensures necessary workspace files exist (chats.json, jobs.json).
    """
    config = load_config()

    # Get or determine default workspace path
    if "default" in config.agents.profiles:
        agent_ref = config.agents.profiles["default"]
        default_workspace = Path(agent_ref.workspace_dir).expanduser()
        agent_existed = True
    else:
        default_workspace = Path("~/.copaw/workspaces/default").expanduser()
        agent_existed = False

    # Ensure workspace directory exists
    default_workspace.mkdir(parents=True, exist_ok=True)

    # Always ensure chats.json exists (even if agent already registered)
    chats_file = default_workspace / "chats.json"
    if not chats_file.exists():
        with open(chats_file, "w", encoding="utf-8") as f:
            json.dump(
                {"version": 1, "chats": []},
                f,
                ensure_ascii=False,
                indent=2,
            )
        logger.debug("Created chats.json for default agent")

    # Always ensure jobs.json exists (even if agent already registered)
    jobs_file = default_workspace / "jobs.json"
    if not jobs_file.exists():
        with open(jobs_file, "w", encoding="utf-8") as f:
            json.dump(
                {"version": 1, "jobs": []},
                f,
                ensure_ascii=False,
                indent=2,
            )
        logger.debug("Created jobs.json for default agent")

    # Only update config if agent didn't exist
    if not agent_existed:
        logger.info("Creating default agent...")

        # Add default agent reference to config
        config.agents.profiles["default"] = AgentProfileRef(
            id="default",
            workspace_dir=str(default_workspace),
        )

        # Set as active if no active agent
        if not config.agents.active_agent:
            config.agents.active_agent = "default"

        save_config(config)
        logger.info(
            f"Created default agent with workspace: {default_workspace}",
        )
