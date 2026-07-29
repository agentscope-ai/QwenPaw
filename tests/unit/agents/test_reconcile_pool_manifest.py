# -*- coding: utf-8 -*-
"""Unit tests for pool manifest reconciliation.

Regression coverage for #6537: plugin-sourced skills have no on-disk
directory in the pool, so ``reconcile_pool_manifest()`` must NOT drop them
(and their user-assigned tags) during the "remove skills no longer on
disk" pass.
"""
from __future__ import annotations

import json

from qwenpaw.agents.skill_system import registry as skill_registry
from qwenpaw.agents.skill_system.registry import reconcile_pool_manifest


def _patch_pool(monkeypatch, pool_dir, manifest_path):
    """Redirect the registry's pool-path lookups at a temp pool."""
    monkeypatch.setattr(skill_registry, "get_skill_pool_dir", lambda: pool_dir)
    monkeypatch.setattr(
        skill_registry,
        "get_pool_skill_manifest_path",
        lambda: manifest_path,
    )
    monkeypatch.setattr(
        skill_registry,
        "get_skill_pool_dirs",
        lambda: [pool_dir],
    )


def test_reconcile_preserves_plugin_sourced_skill_tags(
    tmp_path,
    monkeypatch,
):
    """A plugin-sourced skill (no on-disk dir) keeps its tags across reconcile.

    Fails on the pre-fix code: the removal loop dropped any skill absent
    from the discovered on-disk set, which deleted plugin stubs along with
    their tags (#6537).
    """
    pool_dir = tmp_path / "skill_pool"
    pool_dir.mkdir()
    manifest = pool_dir / "skill.json"
    manifest.write_text(
        json.dumps(
            {
                "skills": {
                    "plugin-skill": {
                        "source": "plugin:superpowers",
                        "protected": False,
                        "tags": ["favorite", "experimental"],
                    },
                },
                "builtin_skill_names": [],
            },
        ),
    )
    _patch_pool(monkeypatch, pool_dir, manifest)

    reconcile_pool_manifest()

    on_disk = json.loads(manifest.read_text())
    entry = on_disk["skills"].get("plugin-skill")
    assert (
        entry is not None
    ), "plugin-sourced skill was dropped by reconcile (regression of #6537)"
    assert entry.get("tags") == ["favorite", "experimental"]


def test_reconcile_still_removes_genuinely_deleted_customized_skill(
    tmp_path,
    monkeypatch,
):
    """A deleted customized skill is still dropped (not over-preserved).

    Guards that the plugin-preservation fix only retains plugin-sourced
    stubs, not every non-disk entry.
    """
    pool_dir = tmp_path / "skill_pool"
    pool_dir.mkdir()
    manifest = pool_dir / "skill.json"
    manifest.write_text(
        json.dumps(
            {
                "skills": {
                    "gone-customized": {
                        "source": "customized",
                        "protected": False,
                        "tags": ["stale"],
                    },
                },
                "builtin_skill_names": [],
            },
        ),
    )
    _patch_pool(monkeypatch, pool_dir, manifest)

    reconcile_pool_manifest()

    on_disk = json.loads(manifest.read_text())
    assert (
        "gone-customized" not in on_disk["skills"]
    ), "customized skill with no on-disk dir should be removed by reconcile"
