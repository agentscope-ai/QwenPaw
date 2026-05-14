# -*- coding: utf-8 -*-
"""Pure business logic for sedimenting a session into a workspace skill.

The ``/make-skill <focus>`` user flow is implemented as a prompt
rewriter in :mod:`qwenpaw.app.runner.runner` that translates the
command into a ``/plan`` invocation. The plan itself encodes the
skill proposal (``plan.name`` = skill name, ``plan.description`` =
skill description + workflow summary). User approval / refine /
cancel are handled by ``/plan``'s built-in machinery. The plan's
single subtask expands the workflow summary into a detailed
``SKILL.md`` body and calls the leaf :func:`materialize_skill` tool
(:mod:`qwenpaw.agents.tools.make_skill_tools`) which delegates here.

The LLM does its own summarization inline at ``create_plan`` time —
no in-tool LLM call, no memory ContextVar, no per-session state.
A future auto-make-skill path (no user confirmation) calls the
functions below directly with already-materialised inputs.

Three concerns live here:

1. :func:`name_conflict` — synchronous workspace-manifest check used by
   the runner before rewriting the command.
2. :func:`render_skill_md` — render the SKILL.md frontmatter+body.
3. :func:`materialize_workspace_skill` — persist via the existing
   :class:`qwenpaw.agents.skill_system.workspace_service.SkillService`,
   which already runs the security scanner.
"""
from __future__ import annotations

import logging
from pathlib import Path

import frontmatter

from ..store import (
    get_workspace_skills_dir,
    suggest_conflict_name,
)
from ..workspace_service import SkillService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Synchronous name-conflict check
# ---------------------------------------------------------------------------


def name_conflict(
    workspace_dir: Path,
    normalized_name: str,
) -> tuple[str, str] | None:
    """Return ``(conflicting_name, suggested_rename)`` if the name is
    taken, else ``None``.

    Mirrors :meth:`SkillService.save_skill`'s pattern (see
    ``workspace_service.py:228``): filesystem-existence check on the
    workspace skills directory plus :func:`suggest_conflict_name` for
    a timestamped rename suggestion. Using the same primitives as
    :meth:`SkillService.create_skill` / :meth:`SkillService.save_skill`
    means the runner pre-flight and the actual write path agree on
    what counts as a conflict.

    The caller is responsible for normalising the name (via
    :func:`qwenpaw.agents.skill_system.store.normalize_skill_dir_name`)
    and handling any normalisation error — this function trusts its
    input.
    """
    skill_root = get_workspace_skills_dir(workspace_dir)
    if not (skill_root / normalized_name).exists():
        return None
    existing = (
        {p.name for p in skill_root.iterdir() if p.is_dir()}
        if skill_root.exists()
        else set()
    )
    return normalized_name, suggest_conflict_name(
        normalized_name,
        existing,
    )


# ---------------------------------------------------------------------------
# Rendering + materialization
# ---------------------------------------------------------------------------


def render_skill_md(
    *,
    proposed_name: str,
    description: str,
    body: str,
) -> str:
    """Render a full ``SKILL.md`` (frontmatter + body)."""
    post = frontmatter.Post(body or "")
    post["name"] = proposed_name
    post["description"] = description
    return frontmatter.dumps(post)


def materialize_workspace_skill(
    workspace_dir: Path,
    *,
    proposed_name: str,
    skill_md: str,
) -> str:
    """Persist *skill_md* under ``{workspace}/skills/{proposed_name}``.

    Delegates to :class:`SkillService.create_skill` which performs the
    safety scan (``scan_skill_dir_or_raise``), writes files, and
    updates the manifest atomically. ``enable=True`` so the new skill
    is visible to ``/skills`` immediately. ``source="agent"`` is
    propagated into the manifest entry.

    Returns:
        The on-disk skill name (post-normalisation). ``None`` from
        ``create_skill`` indicates a race — we surface as RuntimeError
        so the tool wrapper turns it into a retry-inviting message.

    Raises:
        SkillsError: From content validation (missing frontmatter etc.).
        SkillScanError: From the security scanner.
        Other exceptions from the underlying create flow.
    """
    service = SkillService(workspace_dir)
    skill_name = service.create_skill(
        name=proposed_name,
        content=skill_md,
        enable=True,
        source="agent",
    )
    if not skill_name:
        raise RuntimeError(
            f"Skill '{proposed_name}' was created concurrently. "
            "Re-run /make-skill with a different focus.",
        )
    return skill_name
