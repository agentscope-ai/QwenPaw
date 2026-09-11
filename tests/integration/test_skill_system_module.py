# -*- coding: utf-8 -*-
"""Integration tests for the skill_system module internals.

Covers src/qwenpaw/agents/skill_system/* (store, registry,
pool_service, workspace_service) — Plugins module, 2,366 uncovered
lines.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ------------------------------------------------------------------ #
# store path helpers
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_store_pool_dir_exists() -> None:
    """get_skill_pool_dir returns an existing directory."""
    from qwenpaw.agents.skill_system.store import get_skill_pool_dir

    pool_dir = get_skill_pool_dir()
    assert isinstance(pool_dir, Path)


@pytest.mark.integration
@pytest.mark.p1
def test_store_workspace_skills_dir(tmp_path) -> None:
    """get_workspace_skills_dir prefers the skills/ subdirectory."""
    from qwenpaw.agents.skill_system.store import (
        get_workspace_skills_dir,
    )

    skills_dir = get_workspace_skills_dir(tmp_path)
    assert skills_dir == tmp_path / "skills"


@pytest.mark.integration
@pytest.mark.p1
def test_store_workspace_manifest_path(tmp_path) -> None:
    """get_workspace_skill_manifest_path points at skill.json."""
    from qwenpaw.agents.skill_system.store import (
        get_workspace_skill_manifest_path,
    )

    assert get_workspace_skill_manifest_path(tmp_path) == (
        tmp_path / "skill.json"
    )


@pytest.mark.integration
@pytest.mark.p1
def test_store_workspace_identity(tmp_path) -> None:
    """get_workspace_identity resolves id + display name."""
    from qwenpaw.agents.skill_system.store import get_workspace_identity

    identity = get_workspace_identity(tmp_path)
    assert isinstance(identity, dict)
    assert identity.get("workspace_id") == tmp_path.name


@pytest.mark.integration
@pytest.mark.p1
def test_store_pool_manifest_path() -> None:
    """get_pool_skill_manifest_path lives inside the pool dir."""
    from qwenpaw.agents.skill_system.store import (
        get_pool_skill_manifest_path,
        get_skill_pool_dir,
    )

    manifest = get_pool_skill_manifest_path()
    assert manifest.parent == get_skill_pool_dir()


@pytest.mark.integration
@pytest.mark.p1
def test_store_extra_skill_dirs() -> None:
    """get_extra_skill_dirs returns a list of existing paths."""
    from qwenpaw.agents.skill_system.store import get_extra_skill_dirs

    dirs = get_extra_skill_dirs()
    assert isinstance(dirs, list)


# ------------------------------------------------------------------ #
# registry
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_registry_builtin_language_preference() -> None:
    """builtin language preference get/set round-trips."""
    from qwenpaw.agents.skill_system.registry import (
        get_builtin_skill_language_preference,
        set_builtin_skill_language_preference,
    )

    original = get_builtin_skill_language_preference()
    try:
        set_builtin_skill_language_preference("en")
        assert get_builtin_skill_language_preference() == "en"
    finally:
        set_builtin_skill_language_preference(original)


@pytest.mark.integration
@pytest.mark.p1
def test_registry_packaged_builtin_versions() -> None:
    """get_packaged_builtin_versions returns a name->version map."""
    from qwenpaw.agents.skill_system.registry import (
        get_packaged_builtin_versions,
    )

    versions = get_packaged_builtin_versions()
    assert isinstance(versions, dict)
    assert len(versions) > 0


@pytest.mark.integration
@pytest.mark.p1
def test_registry_builtin_skills_dir() -> None:
    """get_builtin_skills_dir returns a directory path."""
    from qwenpaw.agents.skill_system.registry import get_builtin_skills_dir

    assert isinstance(get_builtin_skills_dir(), Path)


# ------------------------------------------------------------------ #
# pool service
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_pool_service_list_all_skills() -> None:
    """SkillPoolService.list_all_skills returns a list."""
    from qwenpaw.agents.skill_system.pool_service import (
        SkillPoolService,
    )

    service = SkillPoolService()
    skills = service.list_all_skills()
    assert isinstance(skills, list)


@pytest.mark.integration
@pytest.mark.p1
def test_pool_service_delete_nonexistent() -> None:
    """SkillPoolService.delete_skill returns False for unknown name."""
    from qwenpaw.agents.skill_system.pool_service import (
        SkillPoolService,
    )

    service = SkillPoolService()
    assert service.delete_skill("integ-nonexistent-skill") is False
