# -*- coding: utf-8 -*-
"""Helpers to bind a KB-capable agent to a shared knowledge base."""

from __future__ import annotations

import logging
from pathlib import Path

from ...config.config import AgentProfileConfig
from ...config.utils import load_config
from ..agent_types import agent_type_has_knowledge_base
from .mount import KnowledgeMountError, ensure_knowledge_mount
from .store import ensure_kb, resolve_kb_id, validate_kb_id

logger = logging.getLogger(__name__)


class WorkspaceConflictError(ValueError):
    """Raised when another agent already uses the same workspace_dir."""


def assert_unique_workspace(
    workspace_dir: str | Path,
    *,
    agent_id: str,
    profiles: dict | None = None,
) -> None:
    """Reject sharing via identical workspace_dir (use knowledge_base_id)."""
    target = str(Path(workspace_dir).expanduser().resolve())
    if profiles is None:
        profiles = load_config().agents.profiles
    for other_id, ref in profiles.items():
        if other_id == agent_id:
            continue
        other_ws = getattr(ref, "workspace_dir", None) or ""
        if not other_ws:
            continue
        try:
            other = str(Path(other_ws).expanduser().resolve())
        except OSError:
            continue
        if other == target:
            raise WorkspaceConflictError(
                f"workspace_dir {target} is already used by agent "
                f"{other_id!r}. Do not share whole workspaces; bind a "
                f"shared knowledge_base_id instead.",
            )


def bind_knowledge_base(
    agent_config: AgentProfileConfig,
    *,
    knowledge_base_id: str | None = None,
    domain: str = "business",
) -> str | None:
    """Ensure KB exists, mount into workspace, persist id on config.

    Returns the bound kb id, or None when the agent type is not KB-capable.
    """
    if not agent_type_has_knowledge_base(agent_config.agent_type):
        return None

    mem = agent_config.running.reme_light_memory_config
    kb_id = resolve_kb_id(
        agent_id=agent_config.id,
        knowledge_base_id=knowledge_base_id or mem.knowledge_base_id,
    )
    # Use the agent's display name (falling back to the kb id) so KB.md
    # metadata is human-friendly rather than a bare id.
    kb_name = (agent_config.name or kb_id).strip() or kb_id
    workspace = agent_config.workspace_dir
    if not workspace:
        raise KnowledgeMountError(
            "workspace_dir is required to mount a knowledge base",
        )
    mount_name = mem.knowledge_dir_name or "knowledge"
    # Detect a dangling mount BEFORE ensure_kb recreates the KB skeleton.
    # A human may have deleted the shared KB on disk; recreating an empty
    # KB here would silently mask that deletion. Surface it instead.
    from .mount import detect_dangling_mount

    dangling = detect_dangling_mount(workspace, mount_name=mount_name)
    if dangling is not None:
        raise KnowledgeMountError(
            f"Knowledge mount {dangling} points at a missing shared "
            f"knowledge base (kb_id={kb_id}). The knowledge-base directory "
            "was removed from disk. Restore it, or update the agent's "
            "knowledge_base_id to rebind to a different knowledge base.",
        )
    ensure_kb(kb_id, name=kb_name, domain=domain)
    ensure_knowledge_mount(
        workspace,
        kb_id,
        mount_name=mount_name,
        domain=domain,
    )
    try:
        from .dream import migrate_wikilink_targets

        migrate_wikilink_targets(kb_id, knowledge_dir=mount_name)
    except Exception:
        logger.debug(
            "Wikilink path migration skipped for kb %s",
            kb_id,
            exc_info=True,
        )
    mem.knowledge_base_id = kb_id
    logger.info(
        "Bound agent %s to knowledge base %s",
        agent_config.id,
        kb_id,
    )
    return kb_id


def normalize_requested_kb_id(value: str | None) -> str | None:
    """Validate optional create-time knowledge_base_id."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return validate_kb_id(stripped)
