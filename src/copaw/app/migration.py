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

_LEGACY_DEFAULT_WORKING_DIR = Path.home() / ".openclaw"

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
    # Markdown files
    ("AGENTS.md", False),
    ("SOUL.md", False),
    ("PROFILE.md", False),
    ("HEARTBEAT.md", False),
    ("MEMORY.md", False),
    ("BOOTSTRAP.md", False),
]

_WORKSPACE_JSON_DEFAULTS: list[tuple[str, dict]] = [
    ("chats.json", {"version": 1, "chats": []}),
    ("jobs.json", {"version": 1, "jobs": []}),
]


def migrate_legacy_workspace_to_default_agent() -> bool:
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
    agent_config_path = default_workspace / "agent.json"
    with open(agent_config_path, "w", encoding="utf-8") as f:
        json.dump(
            default_agent_config.model_dump(exclude_none=True),
            f,
            ensure_ascii=False,
            indent=2,
        )
    logger.info(f"Created agent config: {agent_config_path}")

    migrated_items = []

    sources_to_migrate = [Path(WORKING_DIR).expanduser()]
    legacy_source = _LEGACY_DEFAULT_WORKING_DIR.expanduser()
    if legacy_source not in sources_to_migrate:
        sources_to_migrate.append(legacy_source)

    for source_dir in sources_to_migrate:
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


# pylint: disable=too-many-branches,too-many-statements
def migrate_legacy_skills_to_skill_pool() -> bool:
    """Migrate legacy skill layouts into workspaces and the local skill pool.

    Migration rules:
    1. Legacy ``active_skills`` become enabled workspace skills.
    2. Legacy ``customized_skills`` become workspace skills and shared pool
       entries.
    3. Legacy active-only custom skills are also preserved in the pool.
    4. Channels default to ``["all"]`` when metadata is absent.

    The migration is idempotent and intentionally non-destructive: existing
    new-layout skills are never overwritten.
    """
    from ..agents.skills_manager import (
        _build_signature,
        _build_skill_metadata,
        _copy_skill_dir,
        _default_pool_manifest,
        _default_workspace_manifest,
        _mutate_json,
        _timestamp,
        ensure_skill_pool_initialized,
        get_builtin_skills_dir,
        get_pool_skill_manifest_path,
        get_skill_pool_dir,
        get_workspace_skill_manifest_path,
        get_workspace_skills_dir,
        read_skill_pool_manifest,
        reconcile_pool_manifest,
        reconcile_workspace_manifest,
        suggest_conflict_name,
    )

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

    def _import_skill_to_pool(
        source_dir: Path,
        preferred_name: str,
        origin: dict[str, str],
    ) -> tuple[str, bool]:
        manifest = read_skill_pool_manifest()
        source_signature = _build_signature(source_dir)

        for existing_name, entry in sorted(manifest.get("skills", {}).items()):
            if entry.get("signature") == source_signature:
                return existing_name, False

        final_name = preferred_name
        while True:
            existing = manifest.get("skills", {}).get(final_name)
            if existing is None:
                break
            if existing.get("signature") == source_signature:
                return final_name, False
            final_name = suggest_conflict_name(final_name, source_dir)

        target_dir = get_skill_pool_dir() / final_name
        if target_dir.exists():
            try:
                if _build_signature(target_dir) != source_signature:
                    _copy_skill_dir(source_dir, target_dir)
            except Exception:
                _copy_skill_dir(source_dir, target_dir)
        else:
            _copy_skill_dir(source_dir, target_dir)

        def _update(payload: dict) -> None:
            payload.setdefault("skills", {})
            payload["skills"][final_name] = _build_skill_metadata(
                final_name,
                target_dir,
                source="shared",
                origin=origin,
                protected=False,
            )

        _mutate_json(
            get_pool_skill_manifest_path(),
            _default_pool_manifest(),
            _update,
        )
        return final_name, True

    pool_was_empty = not bool(_discover_skill_dirs(get_skill_pool_dir()))

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

    for legacy_root in (
        Path(WORKING_DIR).expanduser(),
        _LEGACY_DEFAULT_WORKING_DIR,
    ):
        if legacy_root == default_workspace or not _has_legacy_skill_root(
            legacy_root,
        ):
            continue
        # Skip legacy migration if target workspace already has skills
        if str(default_workspace) in workspaces_with_existing_skills:
            logger.debug(
                "Skipping legacy skill migration from %s to %s: "
                "target workspace already has skills",
                legacy_root,
                default_workspace,
            )
            continue
        key = (str(legacy_root), str(default_workspace), "legacy_root")
        if key in seen_sources:
            continue
        seen_sources.add(key)
        migration_sources.append(
            (legacy_root, default_workspace, "legacy_root"),
        )

    builtin_names = (
        {
            path.name
            for path in get_builtin_skills_dir().iterdir()
            if path.is_dir() and (path / "SKILL.md").exists()
        }
        if get_builtin_skills_dir().exists()
        else set()
    )

    workspace_active_names: dict[Path, set[str]] = {}
    workspace_pool_candidates: dict[Path, dict[str, dict[str, str]]] = {}
    copied_workspace_skills = 0
    imported_pool_skills = 0
    linked_workspace_skills = 0

    def _remember_pool_candidate(
        workspace_dir: Path,
        skill_name: str,
        origin_type: str,
        legacy_root: Path,
    ) -> None:
        """Register a skill for pool import."""
        candidates = workspace_pool_candidates.setdefault(workspace_dir, {})
        candidates[skill_name] = {
            "origin_type": origin_type,
            "legacy_root": str(legacy_root),
        }

    for source_root, target_workspace, source_kind in migration_sources:
        workspace_skills_dir = get_workspace_skills_dir(target_workspace)
        workspace_skills_dir.mkdir(parents=True, exist_ok=True)

        customized = _discover_skill_dirs(source_root / "customized_skills")
        active = _discover_skill_dirs(source_root / "active_skills")

        if not customized and not active:
            continue

        active_names = workspace_active_names.setdefault(
            target_workspace,
            set(),
        )

        # First, detect same-name skills with different content
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
                _remember_pool_candidate(
                    target_workspace,
                    target_name,
                    "legacy_customized_migration",
                    source_root,
                )
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
                _remember_pool_candidate(
                    target_workspace,
                    skill_name,
                    "legacy_customized_migration",
                    source_root,
                )

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
                if skill_name in builtin_names:
                    continue
                _remember_pool_candidate(
                    target_workspace,
                    target_name,
                    "legacy_active_migration",
                    source_root,
                )
            elif skill_name not in customized:
                # Different name: copy without suffix
                if _copy_if_missing(
                    skill_dir,
                    workspace_skills_dir / skill_name,
                ):
                    copied_workspace_skills += 1
                active_names.add(skill_name)  # Mark as enabled
                if skill_name in builtin_names:
                    continue
                _remember_pool_candidate(
                    target_workspace,
                    skill_name,
                    "legacy_active_migration",
                    source_root,
                )
            # else: already handled in customized loop
        logger.debug(
            "Prepared legacy skill migration from %s to %s (%s)",
            source_root,
            target_workspace,
            source_kind,
        )

    if pool_was_empty:
        legacy_pool_roots = [
            Path(WORKING_DIR).expanduser() / "skill_hub",
            Path(WORKING_DIR).expanduser() / "skill_pool",
            _LEGACY_DEFAULT_WORKING_DIR / "skill_hub",
            _LEGACY_DEFAULT_WORKING_DIR / "skill_pool",
        ]

        for legacy_pool_root in legacy_pool_roots:
            if (
                not legacy_pool_root.exists()
                or legacy_pool_root == get_skill_pool_dir()
            ):
                continue
            for skill_name, skill_dir in _discover_skill_dirs(
                legacy_pool_root,
            ).items():
                _, created = _import_skill_to_pool(
                    skill_dir,
                    skill_name,
                    origin={
                        "type": "legacy_pool_migration",
                        "legacy_source_root": str(legacy_pool_root),
                    },
                )
                if created:
                    imported_pool_skills += 1

    workspace_pool_links: dict[Path, dict[str, str]] = {}
    if pool_was_empty:
        for workspace_dir, candidates in workspace_pool_candidates.items():
            links = workspace_pool_links.setdefault(workspace_dir, {})
            workspace_skill_root = get_workspace_skills_dir(workspace_dir)
            for skill_name, candidate in sorted(candidates.items()):
                source_dir = workspace_skill_root / skill_name
                if not source_dir.exists():
                    continue

                workspace_id = workspace_dir.name
                origin_type = candidate["origin_type"]

                # Build pool skill name:
                # - Default agent: skill_name as-is
                # - Non-default agent: insert workspace_id
                # (e.g., docx-agent1, docx-agent1-customize)
                if workspace_id == "default":
                    preferred_name = skill_name
                else:
                    # Parse and rebuild with workspace_id
                    if skill_name.endswith("-customize"):
                        base_name = skill_name[: -len("-customize")]
                        preferred_name = (
                            f"{base_name}-{workspace_id}-customize"
                        )
                    elif skill_name.endswith("-active"):
                        base_name = skill_name[: -len("-active")]
                        preferred_name = f"{base_name}-{workspace_id}-active"
                    else:
                        preferred_name = f"{skill_name}-{workspace_id}"

                final_name, created = _import_skill_to_pool(
                    source_dir,
                    preferred_name,
                    origin={
                        "type": origin_type,
                        "workspace_id": workspace_id,
                        "legacy_source_root": candidate["legacy_root"],
                    },
                )
                links[skill_name] = final_name
                if created:
                    imported_pool_skills += 1

    reconcile_pool_manifest()

    for workspace_dir in workspace_dirs:
        reconcile_workspace_manifest(workspace_dir)
        active_names = workspace_active_names.get(workspace_dir, set())
        pool_links = workspace_pool_links.get(workspace_dir, {})

        if not active_names and not pool_links:
            continue

        # pylint: disable=too-many-branches
        def _update(
            payload: dict,
            active_names: set[str] = active_names,
            pool_links: dict[str, str] = pool_links,
        ) -> int:
            payload.setdefault("skills", {})
            changed = 0
            for skill_name in sorted(active_names):
                entry = payload["skills"].get(skill_name)
                if entry is None:
                    continue
                entry_changed = False
                if (
                    skill_name in builtin_names
                    and entry.get("source") != "builtin"
                ):
                    entry["source"] = "builtin"
                    entry_changed = True
                if not entry.get("enabled", False):
                    entry["enabled"] = True
                    entry_changed = True
                channels = entry.get("channels") or ["all"]
                if entry.get("channels") != channels:
                    entry["channels"] = channels
                    entry_changed = True
                if entry_changed:
                    entry["updated_at"] = _timestamp()
                    changed += 1

            for skill_name, pool_name in sorted(pool_links.items()):
                entry = payload["skills"].get(skill_name)
                if entry is None:
                    continue
                entry_changed = False
                next_origin = {
                    **(entry.get("origin") or {}),
                    "pool_name": pool_name,
                }
                next_sync = {
                    "status": "synced",
                    "pool_name": pool_name,
                }
                channels = entry.get("channels") or ["all"]
                if entry.get("origin") != next_origin:
                    entry["origin"] = next_origin
                    entry_changed = True
                if entry.get("sync_to_pool") != next_sync:
                    entry["sync_to_pool"] = next_sync
                    entry_changed = True
                if "sync_to_hub" in entry:
                    entry.pop("sync_to_hub", None)
                    entry_changed = True
                if entry.get("channels") != channels:
                    entry["channels"] = channels
                    entry_changed = True
                if skill_name in active_names and not entry.get(
                    "enabled",
                    False,
                ):
                    entry["enabled"] = True
                    entry_changed = True
                if entry_changed:
                    entry["updated_at"] = _timestamp()
                    changed += 1

            return changed

        changed = _mutate_json(
            get_workspace_skill_manifest_path(workspace_dir),
            _default_workspace_manifest(),
            _update,
        )
        linked_workspace_skills += int(changed)
        reconcile_workspace_manifest(workspace_dir)

    migrated = any(
        count > 0
        for count in (
            copied_workspace_skills,
            imported_pool_skills,
            linked_workspace_skills,
        )
    )

    if migrated:
        logger.info(
            (
                "Legacy skill migration completed: %d workspace copies, "
                "%d pool imports, %d workspace-pool links"
            ),
            copied_workspace_skills,
            imported_pool_skills,
            linked_workspace_skills,
        )

    return migrated


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

    On **first creation** only, ``active_skills`` is seeded from
    ``BUILTIN_QA_AGENT_SKILL_NAMES`` (e.g. ``guidance``,
    ``copaw_source_index``), and built-in tools are restricted (see
    ``build_qa_agent_tools_config``).
    After that, the user may change skills and tools freely; we do not
    overwrite their choices on later startups.

    If the canonical QA workspace path is already used by another agent id,
    builtin creation is **skipped** (with a warning) so that workspace's
    ``agent.json`` is not overwritten.
    """
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
            "Skipping builtin QA profile %r: workspace %s is already used by "
            "agent %r. Point that agent to another directory or remove it "
            "from config before the builtin QA slot can be created.",
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
            "COPAW_WORKING_DIR, and documentation. Prefer reading files "
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
        agent_config,
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
