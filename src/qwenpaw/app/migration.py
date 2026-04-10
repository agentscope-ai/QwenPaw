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
    AgentsLLMRoutingConfig,
    AgentsRunningConfig,
    ChannelConfig,
    HeartbeatConfig,
    MCPConfig,
    build_qa_agent_tools_config,
    save_agent_config,
)
from ..constant import (
    BUILTIN_QA_AGENT_ID,
    BUILTIN_QA_AGENT_NAME,
    BUILTIN_QA_AGENT_SKILL_NAMES,
    WORKING_DIR,
)
from ..config.utils import load_config, save_config

logger = logging.getLogger(__name__)

# Workspace items to migrate: (name, is_directory)
_WORKSPACE_ITEMS_TO_MIGRATE = [
    # Directories
    ("sessions", True),
    ("memory", True),
    ("active_skills", True),
    ("customized_skills", True),
    # Files
    ("chats.json", False),
    ("jobs.json", False),
    ("feishu_receive_ids.json", False),
    ("dingtalk_session_webhooks.json", False),
]

_WORKSPACE_JSON_DEFAULTS: list[tuple[str, dict]] = [
    ("chats.json", {"version": 1, "chats": []}),
    ("jobs.json", {"version": 1, "jobs": []}),
]


def migrate_legacy_workspace_to_default_agent() -> bool:
    # pylint: disable=too-many-statements
    """Migrate legacy single-agent workspace to default agent workspace.

    This function:
    1. Checks if migration is needed
    2. Creates default agent workspace
    3. Migrates legacy workspace files and directories
    4. Creates agent.json with legacy configuration
    5. Updates root config.json to new structure

    Returns:
        bool: True if migration was performed, False if already migrated
    """
    try:
        return _do_migrate_legacy_workspace()
    except Exception as e:
        logger.error(
            f"Legacy workspace migration failed: {e}. "
            "Please check your configuration. If you have custom skills, "
            "verify that all SKILL.md files have valid YAML frontmatter.",
            exc_info=True,
        )
        return False


def _do_migrate_legacy_workspace() -> bool:
    """Internal implementation of legacy workspace migration."""
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
    default_workspace = Path(f"{WORKING_DIR}/workspaces/default").expanduser()
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
    # Use atomic write to prevent corruption
    agent_config_path = default_workspace / "agent.json"
    agent_config_tmp = default_workspace / "agent.json.tmp"

    try:
        with open(agent_config_tmp, "w", encoding="utf-8") as f:
            json.dump(
                default_agent_config.model_dump(exclude_none=True),
                f,
                ensure_ascii=False,
                indent=2,
            )
        # Atomic rename (safer than direct write)
        agent_config_tmp.replace(agent_config_path)
        logger.info(f"Created agent config: {agent_config_path}")
    except Exception as e:
        logger.error(f"Failed to save agent config: {e}")
        # Clean up temp file if it exists
        if agent_config_tmp.exists():
            agent_config_tmp.unlink()
        raise

    migrated_items = []

    for source_dir in [Path(WORKING_DIR).expanduser()]:
        _migrate_workspace_items_from_source(
            source_dir,
            default_workspace,
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


def _migrate_workspace_items_from_source(
    source_dir: Path,
    target_dir: Path,
    migrated_items: list,
) -> None:
    """Migrate all workspace items from a single source directory.

    Args:
        source_dir: Source directory (e.g., ~/.copaw or WORKING_DIR)
        target_dir: Target directory (e.g., workspaces/default/)
        migrated_items: List to append migrated item names
    """
    for item_name, _ in _WORKSPACE_ITEMS_TO_MIGRATE:
        _migrate_workspace_item(
            source_dir / item_name,
            target_dir / item_name,
            item_name,
            migrated_items,
        )

    # Migrate all .md files
    if source_dir.exists():
        for md_file in sorted(source_dir.glob("*.md")):
            _migrate_workspace_item(
                md_file,
                target_dir / md_file.name,
                md_file.name,
                migrated_items,
            )


# pylint: disable=too-many-branches,too-many-statements
def migrate_legacy_skills_to_skill_pool() -> bool:
    """Migrate legacy skill layouts into workspace skills/ directories.

    Legacy layout had two flat directories per workspace:
    - ``active_skills/``  — skills the agent was actually using
    - ``customized_skills/`` — user-created or edited skills (may overlap)

    New layout uses ``<workspace>/skills/`` (unified).

    Migration rules:
    1. Legacy ``active_skills`` are copied to ``skills/`` and marked
       enabled.
    2. Legacy ``customized_skills`` are copied to ``skills/`` and marked
       enabled only if the same name also appears in ``active_skills``
       with identical content. Otherwise they remain disabled.
    3. When both directories contain the same name with different
       content, both are preserved with suffixes: ``<name>-customize``
       (disabled) and ``<name>-active`` (enabled).
    4. Channels default to ``["all"]`` when metadata is absent.

    The migration is idempotent and non-destructive: existing new-layout
    skills are never overwritten; ``_copy_if_missing`` skips targets that
    already exist on disk.

    Users can manually upload workspace skills to the shared pool later
    via the UI.

    Returns:
        bool: True if skills were migrated, False otherwise.
    """
    try:
        return _do_migrate_legacy_skills()
    except Exception as e:
        logger.error(
            f"Legacy skill migration failed: {e}. "
            "This may be due to malformed YAML in custom SKILL.md files. "
            "Please check your skills and fix any YAML syntax errors.",
            exc_info=True,
        )
        return False


def _do_migrate_legacy_skills() -> bool:
    """Internal implementation of legacy skills migration."""
    from datetime import datetime, timezone

    from ..agents.skills_manager import (
        _build_signature,
        _copy_skill_dir,
        _default_workspace_manifest,
        _mutate_json,
        ensure_skill_pool_initialized,
        get_pool_skill_manifest_path,
        get_workspace_skill_manifest_path,
        get_workspace_skills_dir,
        reconcile_workspace_manifest,
    )

    # --- Phase 0: Check if migration already completed ---
    # If skill pool manifest exists, migration has been done
    pool_manifest = get_pool_skill_manifest_path()
    if pool_manifest.exists():
        return False

    def _has_legacy_skill_root(root: Path) -> bool:
        return any(
            (root / name).exists()
            for name in ("active_skills", "customized_skills")
        )

    def _discover_skill_dirs(root: Path) -> dict[str, Path]:
        if not root.exists() or not root.is_dir():
            return {}
        return {
            path.name: path
            for path in sorted(root.iterdir())
            if path.is_dir() and (path / "SKILL.md").exists()
        }

    def _register_workspace(
        workspace_dir: Path,
        workspaces: list[Path],
        seen: set[str],
    ) -> None:
        text = str(workspace_dir.expanduser())
        if text in seen:
            return
        seen.add(text)
        workspaces.append(Path(text))

    def _copy_if_missing(source_dir: Path, target_dir: Path) -> bool:
        if target_dir.exists():
            try:
                if _build_signature(source_dir) == _build_signature(
                    target_dir,
                ):
                    return False
            except Exception:
                pass
            logger.debug(
                (
                    "Skipping legacy skill copy from %s to %s "
                    "because target exists"
                ),
                source_dir,
                target_dir,
            )
            return False
        _copy_skill_dir(source_dir, target_dir)
        return True

    # --- Phase 1: Initialize pool ---
    try:
        ensure_skill_pool_initialized()
    except Exception as e:
        logger.warning(
            "Failed to initialize skill pool before migration: %s",
            e,
        )
        return False

    try:
        config = load_config()
    except Exception as e:
        logger.warning("Failed to load config for skill migration: %s", e)
        return False

    default_workspace = Path(
        f"{WORKING_DIR}/workspaces/default",
    ).expanduser()
    default_workspace.mkdir(parents=True, exist_ok=True)

    # --- Phase 1: Discover workspaces ---
    workspace_dirs: list[Path] = []
    seen_workspaces: set[str] = set()
    for profile in config.agents.profiles.values():
        _register_workspace(
            Path(profile.workspace_dir).expanduser(),
            workspace_dirs,
            seen_workspaces,
        )

    workspaces_root = Path(WORKING_DIR) / "workspaces"
    if workspaces_root.exists():
        for workspace_dir in sorted(workspaces_root.iterdir()):
            if workspace_dir.is_dir():
                _register_workspace(
                    workspace_dir.expanduser(),
                    workspace_dirs,
                    seen_workspaces,
                )

    _register_workspace(default_workspace, workspace_dirs, seen_workspaces)

    # --- Phase 2: Build migration sources ---
    migration_sources: list[tuple[Path, Path, str]] = []
    seen_sources: set[tuple[str, str, str]] = set()

    # Track which workspaces already have skills
    workspaces_with_existing_skills: set[str] = set()

    for workspace_dir in workspace_dirs:
        key = (str(workspace_dir), str(workspace_dir), "workspace")
        if key not in seen_sources:
            seen_sources.add(key)
            migration_sources.append(
                (workspace_dir, workspace_dir, "workspace"),
            )
            # Check if workspace already has skills
            ws_skills_dir = get_workspace_skills_dir(workspace_dir)
            if ws_skills_dir.exists() and any(
                p.is_dir() and (p / "SKILL.md").exists()
                for p in ws_skills_dir.iterdir()
            ):
                workspaces_with_existing_skills.add(str(workspace_dir))

    legacy_root = Path(WORKING_DIR).expanduser()
    if (
        legacy_root != default_workspace
        and _has_legacy_skill_root(legacy_root)
        and not _has_legacy_skill_root(default_workspace)
        and str(default_workspace) not in workspaces_with_existing_skills
    ):
        key = (str(legacy_root), str(default_workspace), "legacy_root")
        if key not in seen_sources:
            seen_sources.add(key)
            migration_sources.append(
                (legacy_root, default_workspace, "legacy_root"),
            )

    workspace_active_names: dict[Path, set[str]] = {}
    copied_workspace_skills = 0

    # --- Phase 3: Copy legacy skills into workspace skills/ dir ---
    for source_root, target_workspace, source_kind in migration_sources:
        workspace_skills_dir = get_workspace_skills_dir(target_workspace)
        workspace_skills_dir.mkdir(parents=True, exist_ok=True)

        customized = _discover_skill_dirs(source_root / "customized_skills")
        active = _discover_skill_dirs(source_root / "active_skills")

        if not customized and not active:
            continue

        logger.debug(
            "Found legacy skills in %s (%s): %d customized, %d active",
            source_root,
            source_kind,
            len(customized),
            len(active),
        )

        active_names = workspace_active_names.setdefault(
            target_workspace,
            set(),
        )

        # Intra-workspace conflict: when active/ and customized/ both
        # contain a skill with the same directory name but different file
        # content, we suffix *both* copies ("-customize" and "-active")
        # to avoid silently discarding either version.
        same_name_diff_content: set[str] = set()
        for skill_name in set(customized.keys()) & set(active.keys()):
            custom_sig = _build_signature(customized[skill_name])
            active_sig = _build_signature(active[skill_name])
            if custom_sig != active_sig:
                same_name_diff_content.add(skill_name)

        # Process customized skills
        for skill_name, skill_dir in customized.items():
            if skill_name in same_name_diff_content:
                # Same name but different content: add "-customize" suffix
                target_name = f"{skill_name}-customize"
                if _copy_if_missing(
                    skill_dir,
                    workspace_skills_dir / target_name,
                ):
                    copied_workspace_skills += 1
                # NOT added to active_names, so will be disabled
            else:
                # Normal case: copy without suffix
                if _copy_if_missing(
                    skill_dir,
                    workspace_skills_dir / skill_name,
                ):
                    copied_workspace_skills += 1
                # If also in active with same content, mark as enabled
                if skill_name in active:
                    active_names.add(skill_name)

        # Process active skills
        for skill_name, skill_dir in active.items():
            if skill_name in same_name_diff_content:
                # Same name but different content: add "-active" suffix
                target_name = f"{skill_name}-active"
                if _copy_if_missing(
                    skill_dir,
                    workspace_skills_dir / target_name,
                ):
                    copied_workspace_skills += 1
                active_names.add(target_name)  # Mark as enabled
            elif skill_name not in customized:
                # Different name: copy without suffix
                if _copy_if_missing(
                    skill_dir,
                    workspace_skills_dir / skill_name,
                ):
                    copied_workspace_skills += 1
                active_names.add(skill_name)  # Mark as enabled
            # else: already handled in customized loop

    # --- Phase 4: Reconcile workspace manifests ---
    for workspace_dir in workspace_dirs:
        # reconcile discovers on-disk skills and populates skill.json
        # with correct source, metadata, and signature.
        reconcile_workspace_manifest(workspace_dir)
        active_names = workspace_active_names.get(workspace_dir, set())

        if not active_names:
            continue

        def _update(
            payload: dict,
            active_names: set[str] = active_names,
        ) -> int:
            payload.setdefault("skills", {})
            changed = 0
            for skill_name in sorted(active_names):
                entry = payload["skills"].get(skill_name)
                if entry is None:
                    continue
                if not entry.get("enabled", False):
                    entry["enabled"] = True
                    entry["updated_at"] = (
                        datetime.now(timezone.utc)
                        .isoformat()
                        .replace("+00:00", "Z")
                    )
                    changed += 1
            return changed

        _mutate_json(
            get_workspace_skill_manifest_path(workspace_dir),
            _default_workspace_manifest(),
            _update,
        )

    if copied_workspace_skills > 0:
        logger.info(
            "Legacy skill migration completed: %d workspace copies",
            copied_workspace_skills,
        )

    return copied_workspace_skills > 0


def _ensure_workspace_json_files(
    workspace_dir: Path,
    label: str = "",
) -> None:
    for filename, default in _WORKSPACE_JSON_DEFAULTS:
        filepath = workspace_dir / filename
        if not filepath.exists():
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=2)
            if label:
                logger.debug("Created %s for %s", filename, label)


def ensure_default_agent_exists() -> None:
    """Ensure that the default agent exists in config.

    This function is called on startup to verify the default agent
    is properly configured. If not, it will be created.
    Also ensures necessary workspace files exist (chats.json, jobs.json).
    """
    try:
        _do_ensure_default_agent()
    except Exception as e:
        logger.error(
            f"Failed to ensure default agent exists: {e}. "
            "Application may not work correctly.",
            exc_info=True,
        )


def _do_ensure_default_agent() -> None:
    """Internal implementation of default agent initialization."""
    config = load_config()

    # Get or determine default workspace path
    if "default" in config.agents.profiles:
        agent_ref = config.agents.profiles["default"]
        default_workspace = Path(agent_ref.workspace_dir).expanduser()
        agent_existed = True
    else:
        default_workspace = Path(
            f"{WORKING_DIR}/workspaces/default",
        ).expanduser()
        agent_existed = False

    # Ensure workspace directory exists
    default_workspace.mkdir(parents=True, exist_ok=True)

    _ensure_workspace_json_files(default_workspace, "default agent")

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


def _other_agent_owns_workspace(
    profiles: dict[str, AgentProfileRef],
    workspace: Path,
    builtin_id: str,
) -> str | None:
    """If another profile's workspace resolves to ``workspace``, return its id.

    Prevents creating the builtin QA profile on the canonical path
    ``workspaces/<builtin_id>/`` when a user already assigned that directory
    to a different agent: ``save_agent_config`` would overwrite their
    ``agent.json``.
    """
    try:
        target = workspace.resolve()
    except OSError:
        target = workspace.expanduser()
    for aid, ref in profiles.items():
        if aid == builtin_id:
            continue
        other = Path(ref.workspace_dir).expanduser()
        try:
            other_res = other.resolve()
        except OSError:
            other_res = other
        if other_res == target:
            return aid
    return None


def ensure_qa_agent_exists() -> None:
    """Ensure the builtin QA agent profile and workspace exist.

    On **first creation** only, ``skills/`` is seeded from
    ``BUILTIN_QA_AGENT_SKILL_NAMES`` (e.g. ``guidance``,
    ``copaw_source_index``), and built-in tools are restricted (see
    ``build_qa_agent_tools_config``).
    After that, the user may change skills and tools freely; we do not
    overwrite their choices on later startups.

    If the canonical QA workspace path is already used by another agent id,
    builtin creation is **skipped** (with a warning) so that workspace's
    ``agent.json`` is not overwritten.

    Note:
        This function catches all exceptions internally and never raises.
        Errors are logged for graceful degradation.
    """
    try:
        _do_ensure_qa_agent()
    except Exception as e:
        logger.error(
            f"Failed to ensure QA agent exists: {e}. "
            "QA agent will not be available.",
            exc_info=True,
        )


def _do_ensure_qa_agent() -> None:
    """Internal implementation of QA agent initialization."""
    from .routers.agents import _initialize_agent_workspace

    config = load_config()
    qa_id = BUILTIN_QA_AGENT_ID

    if qa_id in config.agents.profiles:
        agent_ref = config.agents.profiles[qa_id]
        qa_workspace = Path(agent_ref.workspace_dir).expanduser()
        agent_existed = True
    else:
        qa_workspace = Path(
            f"{WORKING_DIR}/workspaces/{qa_id}",
        ).expanduser()
        agent_existed = False

    qa_workspace.mkdir(parents=True, exist_ok=True)

    _ensure_workspace_json_files(qa_workspace, "QA agent")

    if agent_existed:
        return

    other_id = _other_agent_owns_workspace(
        config.agents.profiles,
        qa_workspace,
        qa_id,
    )
    if other_id is not None:
        logger.warning(
            "Skipping builtin QA profile %r: workspace %s is already "
            "used by agent %r. Point that agent to another directory "
            "or remove it from config before the builtin QA slot can "
            "be created.",
            qa_id,
            qa_workspace,
            other_id,
        )
        return

    logger.info("Creating builtin QA agent...")
    qa_skill_list = list(BUILTIN_QA_AGENT_SKILL_NAMES)

    language = config.agents.language or "zh"
    agent_config = AgentProfileConfig(
        id=qa_id,
        name=BUILTIN_QA_AGENT_NAME,
        description=(
            "Builtin Q&A helper for CoPaw setup, local config under "
            "QWENPAW_WORKING_DIR, and documentation. Prefer reading files "
            "before answering; use absolute paths for code outside this "
            "workspace."
        ),
        workspace_dir=str(qa_workspace),
        language=language,
        channels=ChannelConfig(),
        mcp=MCPConfig(),
        heartbeat=HeartbeatConfig(),
        tools=build_qa_agent_tools_config(),
    )

    _initialize_agent_workspace(
        qa_workspace,
        skill_names=qa_skill_list,
        builtin_qa_md_seed=True,
    )

    config.agents.profiles[qa_id] = AgentProfileRef(
        id=qa_id,
        workspace_dir=str(qa_workspace),
    )
    save_config(config)
    save_agent_config(qa_id, agent_config)
    logger.info(
        "Created builtin QA agent with workspace: %s",
        qa_workspace,
    )
