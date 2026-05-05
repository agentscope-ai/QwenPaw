# -*- coding: utf-8 -*-
"""Backup restore operations."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import shutil
import zipfile
from pathlib import Path

from .._utils.constants import (
    PREFIX_CONFIG,
    PREFIX_SECRETS,
    PREFIX_SKILL_POOL,
    PREFIX_WORKSPACES,
    zip_path,
)
from .._utils.meta import read_meta_from_zip
from .._utils.safe_swap import (
    cleanup_stale_restore_artifacts,
    commit_tmp,
    discard_tmp,
    extract_to_tmp,
)
from ..models import BackupMeta, RestoreBackupRequest
from ...config.config import AgentProfileRef
from ...config.utils import load_config, save_config
from ...constant import CONFIG_FILE, SECRET_DIR, WORKING_DIR
from ...security.secret_store import reload_master_key_from_disk
from .restore_helpers import (
    collect_workspace_agents_from_zip,
    handle_master_key_conflict,
    resolve_workspace_dst,
    rewrite_agent_workspace_dir,
)

logger = logging.getLogger(__name__)

_SUPPORTED_BACKUP_VERSIONS = {"1"}

# Serialise concurrent restores so that concurrent HTTP requests cannot
# interleave their file operations (especially critical on Windows where open
# handles prevent directory renames).
_RESTORE_LOCK = asyncio.Lock()


async def restore(backup_id: str, req: RestoreBackupRequest) -> None:
    """Restore a backup to the workspace."""
    async with _RESTORE_LOCK:
        await asyncio.to_thread(_restore_sync, backup_id, req)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_version(meta: BackupMeta) -> None:
    """Raise ValueError when *meta.version* is not supported."""
    if meta.version not in _SUPPORTED_BACKUP_VERSIONS:
        raise ValueError(
            f"Unsupported backup version: {meta.version!r}. "
            f"Supported versions: {sorted(_SUPPORTED_BACKUP_VERSIONS)}",
        )


def _zip_has_prefix(zf: zipfile.ZipFile, prefix: str) -> bool:
    """Return True when *zf* contains at least one non-directory entry
    whose path starts with *prefix*."""
    for info in zf.infolist():
        if not info.is_dir() and info.filename.startswith(prefix):
            return True
    return False


def _plan_agent_destinations(
    agent_ids: list[str],
    ws_agents: set[str],
    config_before,
    req: RestoreBackupRequest,
) -> dict[str, tuple[Path, bool]]:
    """Compute and validate destination paths for all agents to restore.

    Returns a mapping ``{agent_id: (resolved_dst, is_new)}``.

    Raises :class:`ValueError` on two types of conflicts:

    * Two different agent IDs resolve to the **same physical directory**.
    * A *new* agent's destination collides with the workspace of an
      **existing agent that is not being restored** in this operation,
      which would silently clobber that agent's data.
    """
    restore_set = set(agent_ids)

    # Build the set of "other" agents' resolved workspace paths to guard
    # against cross-agent collisions for newly placed agents.
    other_workspace_paths: set[Path] = set()
    for aid, ref in config_before.agents.profiles.items():
        if aid in restore_set:
            continue
        try:
            p = Path(ref.workspace_dir).expanduser().resolve()
            other_workspace_paths.add(p)
        except Exception:
            pass

    dst_map: dict[str, tuple[Path, bool]] = {}
    seen_paths: dict[
        Path,
        str,
    ] = {}  # resolved path → first aid that claimed it

    for aid in agent_ids:
        if aid not in ws_agents:
            # Will be skipped in the staging loop; no need to plan a dst.
            continue
        ref = config_before.agents.profiles.get(aid)
        dst, is_new = resolve_workspace_dst(
            aid,
            ref,
            req.default_workspace_dir,
        )

        # Conflict: two agents in the same restore batch resolve to the
        # same dir.
        if dst in seen_paths:
            raise ValueError(
                f"Agent destination conflict: both '{seen_paths[dst]}' and "
                f"'{aid}' would restore to {dst}. "
                "Ensure agent_ids are unique and have distinct workspaces.",
            )
        seen_paths[dst] = aid

        # Conflict: new agent would overwrite an unrelated existing agent.
        if is_new and dst in other_workspace_paths:
            raise ValueError(
                f"New agent '{aid}' destination {dst} is already used by an "
                "existing agent that is not part of this restore. Provide a "
                "different default_workspace_dir to avoid overwriting it.",
            )

        dst_map[aid] = (dst, is_new)

    return dst_map


# ---------------------------------------------------------------------------
# Main restore logic
# ---------------------------------------------------------------------------


def _collect_agent_ids(
    zf: zipfile.ZipFile,
    req: RestoreBackupRequest,
) -> tuple[list[str], set[str]]:
    """Determine which agent IDs to restore and which exist in the archive."""
    if not req.include_agents:
        return [], set()
    ws_agents = collect_workspace_agents_from_zip(zf)
    agent_ids = list(dict.fromkeys(req.agent_ids))
    unknown = [aid for aid in agent_ids if aid not in ws_agents]
    if unknown:
        logger.warning(
            "Agents not found in backup, will be skipped: %s",
            unknown,
        )
    logger.info(
        "Agents to restore: %s (available in backup: %s)",
        agent_ids,
        sorted(ws_agents),
    )
    return agent_ids, ws_agents


def _stage_secrets(zf: zipfile.ZipFile, staged_dirs: list[Path]) -> None:
    """Stage secrets directory from *zf*; appends to *staged_dirs* on
    success."""
    if not _zip_has_prefix(zf, PREFIX_SECRETS):
        logger.warning(
            "include_secrets=True but backup contains no secrets "
            "entries; skipping to avoid wiping existing secrets.",
        )
        return
    bak_path = handle_master_key_conflict(zf)
    if bak_path is not None:
        logger.warning(
            "master_key differs; old key preserved at %s – "
            "needed to decrypt credentials created before this restore.",
            bak_path,
        )
    cleanup_stale_restore_artifacts(SECRET_DIR)
    extract_to_tmp(zf, PREFIX_SECRETS, SECRET_DIR, zip_slip_base=SECRET_DIR)
    staged_dirs.append(SECRET_DIR)


def _stage_skill_pool(zf: zipfile.ZipFile, staged_dirs: list[Path]) -> None:
    """Stage skill pool directory from *zf*; appends to *staged_dirs* on
    success."""
    from ...agents.skills_manager import get_skill_pool_dir

    if not _zip_has_prefix(zf, PREFIX_SKILL_POOL):
        logger.warning(
            "include_skill_pool=True but backup contains no skill "
            "pool entries; skipping to avoid wiping existing skill pool.",
        )
        return
    skill_pool_dir = get_skill_pool_dir()
    logger.info("Staging skill pool from backup")
    cleanup_stale_restore_artifacts(skill_pool_dir)
    extract_to_tmp(
        zf,
        PREFIX_SKILL_POOL,
        skill_pool_dir,
        zip_slip_base=skill_pool_dir,
    )
    staged_dirs.append(skill_pool_dir)


def _stage_agents(
    zf: zipfile.ZipFile,
    agent_ids: list[str],
    ws_agents: set[str],
    planned_dst_map: dict[str, tuple[Path, bool]],
    staged_dirs: list[Path],
    dst_map: dict[str, Path],
    new_aids: list[str],
) -> None:
    """Stage each requested agent workspace from *zf*."""
    for aid in agent_ids:
        if aid not in ws_agents:
            logger.warning("Agent '%s' not found in backup, skipping", aid)
            continue
        dst, is_new = planned_dst_map[aid]
        prefix = f"{PREFIX_WORKSPACES}{aid}/"
        if not _zip_has_prefix(zf, prefix):
            logger.warning(
                "Agent '%s' has no files in backup; skipping to "
                "avoid wiping existing workspace.",
                aid,
            )
            continue
        if is_new:
            logger.info("Staging new agent '%s' to: %s", aid, dst)
        else:
            logger.info(
                "Staging agent '%s' to existing workspace: %s",
                aid,
                dst,
            )
        cleanup_stale_restore_artifacts(dst)
        extract_to_tmp(zf, prefix, dst)
        staged_dirs.append(dst)
        dst_map[aid] = dst
        if is_new:
            new_aids.append(aid)


def _stage_all(
    zf: zipfile.ZipFile,
    req: RestoreBackupRequest,
    agent_ids: list[str],
    ws_agents: set[str],
    planned_dst_map: dict[str, tuple[Path, bool]],
    restore_aids: set[str],
) -> tuple[list[Path], Path | None, dict[str, Path], list[str]]:
    """Phase 1: stage all targets atomically.

    *restore_aids* is the intersection of requested agent IDs and those
    actually present in the backup archive; it is forwarded to
    ``_stage_global_config`` so that the custom-mode config merge only
    applies backup profiles for agents whose workspaces are really restored.

    Returns ``(staged_dirs, staged_config_tmp, dst_map, new_aids)``.
    On any failure every staged artifact is discarded before re-raising.
    """
    staged_dirs: list[Path] = []
    staged_config_tmp: Path | None = None
    dst_map: dict[str, Path] = {}
    new_aids: list[str] = []

    try:
        staged_config_tmp = _stage_global_config(zf, req, restore_aids)
        if req.include_secrets:
            _stage_secrets(zf, staged_dirs)
        if req.include_skill_pool:
            _stage_skill_pool(zf, staged_dirs)
        _stage_agents(
            zf,
            agent_ids,
            ws_agents,
            planned_dst_map,
            staged_dirs,
            dst_map,
            new_aids,
        )
    except BaseException:
        for d in staged_dirs:
            discard_tmp(d)
        if staged_config_tmp is not None:
            staged_config_tmp.unlink(missing_ok=True)
        raise

    return staged_dirs, staged_config_tmp, dst_map, new_aids


def _commit_and_finalize(
    staged_dirs: list[Path],
    staged_config_tmp: Path | None,
    dst_map: dict[str, Path],
    new_aids: list[str],
    backup_id: str,
) -> None:
    """Phase 2: atomically commit all staged dirs then update config."""
    _commit_staged_global_config(staged_config_tmp)

    committed: list[Path] = []
    try:
        for d in staged_dirs:
            commit_tmp(d)
            committed.append(d)
            logger.info("Committed restore for %s", d)
    except Exception:
        remaining = [d for d in staged_dirs if d not in set(committed)]
        for d in remaining:
            discard_tmp(d)
        logger.exception(
            "Phase 2 commit failed after committing %d/%d dirs. "
            "Committed (already live): %s. Discarded (rolled back): %s.",
            len(committed),
            len(staged_dirs),
            committed,
            remaining,
        )
        raise

    if SECRET_DIR in committed:
        reload_master_key_from_disk()

    for aid, dst in dst_map.items():
        rewrite_agent_workspace_dir(dst, aid)

    config = load_config()
    for aid in new_aids:
        if aid not in config.agents.profiles:
            config.agents.profiles[aid] = AgentProfileRef(
                id=aid,
                workspace_dir=str(dst_map[aid]),
            )
            logger.info(
                "Registered new agent '%s' at %s",
                aid,
                dst_map[aid],
            )

    _apply_workspace_paths_and_save(config, dst_map, backup_id)


def _restore_sync(backup_id: str, req: RestoreBackupRequest) -> None:
    zp = zip_path(backup_id)
    if not zp.is_file():
        raise FileNotFoundError(f"Backup not found: {backup_id}")

    with zipfile.ZipFile(zp, "r") as zf:
        meta_json = read_meta_from_zip(zf)
        if meta_json is None:
            raise FileNotFoundError(f"Backup not found: {backup_id}")
        meta = BackupMeta.model_validate_json(meta_json)
        _validate_version(meta)

        logger.info(
            "Starting restore: backup_id=%s name=%r mode=%s "
            "include_agents=%s agent_ids=%s "
            "include_global_config=%s include_secrets=%s",
            backup_id,
            meta.name,
            req.mode,
            req.include_agents,
            req.agent_ids,
            req.include_global_config,
            req.include_secrets,
        )

        agent_ids, ws_agents = _collect_agent_ids(zf, req)
        # Only agents that are both requested and present in the archive will
        # have their workspaces restored; use this set to gate profile merging
        # in the global-config stage so that ghost entries are never created.
        restore_aids: set[str] = set(agent_ids) & ws_agents
        config_before = load_config()
        planned_dst_map = _plan_agent_destinations(
            agent_ids,
            ws_agents,
            config_before,
            req,
        )
        staged_dirs, staged_config_tmp, dst_map, new_aids = _stage_all(
            zf,
            req,
            agent_ids,
            ws_agents,
            planned_dst_map,
            restore_aids,
        )

    _commit_and_finalize(
        staged_dirs,
        staged_config_tmp,
        dst_map,
        new_aids,
        backup_id,
    )


def _merge_profiles_into(
    backup_cfg: dict,
    current_cfg: dict,
    restore_aids: set[str],
) -> dict:
    """Return a merged config dict for custom-mode restores.

    All top-level keys (providers, channels, etc.) come from *backup_cfg*
    (backup wins).  ``agents.profiles`` is rebuilt with the following logic:

    * Start from the **current** local profiles so that agents not involved
      in this restore are never touched.
    * For each agent ID in *restore_aids* that has a profile in the backup,
      overwrite (or insert) that profile with the backup's version.

    This ensures that when ``include_agents=False`` (restore_aids is empty)
    the profiles section remains exactly as it was on disk, preventing
    "ghost agents" from appearing in the agent manager.
    """
    merged = copy.deepcopy(backup_cfg)
    backup_profiles: dict = (
        backup_cfg.get("agents", {}).get("profiles", {})
        if isinstance(backup_cfg, dict)
        else {}
    )
    current_profiles: dict = (
        current_cfg.get("agents", {}).get("profiles", {})
        if isinstance(current_cfg, dict)
        else {}
    )

    # Build the merged profiles: local baseline, selectively overridden by
    # backup entries for agents that are actually being restored.
    merged_profiles: dict = copy.deepcopy(current_profiles)
    for aid in restore_aids:
        if aid in backup_profiles:
            merged_profiles[aid] = copy.deepcopy(backup_profiles[aid])
            logger.debug(
                "Restored agent '%s' profile from backup"
                " during custom-mode merge",
                aid,
            )

    merged.setdefault("agents", {})["profiles"] = merged_profiles
    return merged


def _stage_global_config(
    zf: zipfile.ZipFile,
    req: RestoreBackupRequest,
    restore_aids: set[str],
) -> Path | None:
    """Stage global config.json from the zip to a sibling .tmp file.

    When ``req.mode == 'full'`` the backup bytes are copied verbatim so that
    the restore is a complete replacement (including ``agents.profiles``).

    When ``req.mode == 'custom'`` the backup config is merged with the current
    config: all top-level keys come from the backup, but ``agents.profiles``
    is rebuilt from the current local profiles, with only the agents in
    *restore_aids* overwritten/added from the backup.  Agents not in
    *restore_aids* keep their local state, preventing ghost entries when
    ``include_agents=False`` (restore_aids is empty).

    Returns the staging path, or ``None`` if skipped (not requested or not
    present in the archive).
    """
    if not req.include_global_config:
        return None
    if PREFIX_CONFIG not in zf.namelist():
        logger.warning(
            "include_global_config=True requested but"
            " backup contains no config.json; skipping",
        )
        return None
    dest = WORKING_DIR / CONFIG_FILE
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        if req.mode == "full":
            # Full restore: copy backup bytes verbatim (agents.profiles
            # will be exactly what the backup contained).
            with zf.open(PREFIX_CONFIG) as src, open(tmp, "wb") as out:
                shutil.copyfileobj(src, out)
            logger.debug(
                "Staged global config (full replace) to %s",
                tmp,
            )
        else:
            # Custom restore: merge – backup wins on all top-level keys, but
            # agents.profiles is rebuilt from local state, only applying
            # backup profiles for agents in restore_aids.
            backup_cfg = json.loads(zf.read(PREFIX_CONFIG))
            try:
                with open(dest, "r", encoding="utf-8") as f:
                    current_cfg = json.load(f)
            except (OSError, ValueError):
                current_cfg = {}
            merged = _merge_profiles_into(
                backup_cfg,
                current_cfg,
                restore_aids,
            )
            with open(tmp, "w", encoding="utf-8") as out:
                json.dump(merged, out, indent=2, ensure_ascii=False)
            logger.debug(
                "Staged global config (custom merge, restore_aids=%s) to %s",
                sorted(restore_aids),
                tmp,
            )
        return tmp
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _commit_staged_global_config(
    staged_tmp: Path | None,
) -> None:
    """Atomically replace config.json with the staged tmp file."""
    if staged_tmp is None:
        return
    dest = WORKING_DIR / CONFIG_FILE
    staged_tmp.replace(dest)
    logger.info("Global config committed to %s", dest)


def _apply_workspace_paths_and_save(
    config,
    dst_map: dict[str, Path],
    backup_id: str,
) -> None:
    """Fix workspace_dir for restored agents in config and persist."""
    for aid, dst in dst_map.items():
        ref = config.agents.profiles.get(aid)
        if ref is not None:
            ref.workspace_dir = str(dst)

    if dst_map:
        save_config(config)

    logger.info(
        "Restore complete: backup_id=%s restored_agents=%s",
        backup_id,
        list(dst_map.keys()),
    )
