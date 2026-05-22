# -*- coding: utf-8 -*-
# pylint: disable=unused-argument
# Several tests take ``tmp_path`` for fixture wiring without referencing it.
"""Tests for plugins/bundle/datapaw/agents_setup.py."""
from unittest.mock import MagicMock, patch


def _fake_config(profiles=None, language="zh"):
    """Build a MagicMock that quacks like qwenpaw.config.config.Config."""
    cfg = MagicMock()
    cfg.agents.profiles = profiles if profiles is not None else {}
    cfg.agents.language = language
    return cfg


def test_ensure_builtin_agents_writes_profile_when_missing(tmp_path):
    """First-run: profile absent → create workspace, seed persona, save."""
    from agents_setup import ensure_builtin_agents

    fake_cfg = _fake_config(profiles={})

    saved = []
    seeded = []

    with patch("agents_setup.load_config", return_value=fake_cfg), patch(
        "agents_setup.save_config",
        side_effect=saved.append,
    ), patch("agents_setup.save_agent_config") as save_agent, patch(
        "agents_setup._seed_persona_md_files",
        side_effect=lambda d, language: seeded.append((d, language)),
    ), patch(
        "agents_setup.WORKING_DIR",
        tmp_path,
    ):
        ensure_builtin_agents()

    assert (
        "datapaw" in fake_cfg.agents.profiles
    ), "datapaw was not written to profiles"
    assert len(saved) == 1, "save_config should be called exactly once"
    assert save_agent.call_count == 1
    args, _ = save_agent.call_args
    assert args[0] == "datapaw"
    assert args[1].id == "datapaw"
    assert args[1].name == "DataPaw"

    # Workspace dir must be created and the language passed to the seeder.
    assert seeded, "_seed_persona_md_files was not called"
    seeded_dir, seeded_lang = seeded[0]
    assert seeded_dir.exists()
    assert seeded_lang == "zh"


def test_ensure_builtin_agents_idempotent(tmp_path):
    """Existing profile must not trigger another save_config write."""
    from agents_setup import ensure_builtin_agents
    from qwenpaw.config.config import AgentProfileRef

    ws_dir = (tmp_path / "workspaces" / "datapaw").resolve()
    ws_dir.mkdir(parents=True, exist_ok=True)

    fake_cfg = _fake_config(
        profiles={
            "datapaw": AgentProfileRef(
                id="datapaw",
                workspace_dir=str(ws_dir),
            ),
        },
    )

    with patch("agents_setup.load_config", return_value=fake_cfg), patch(
        "agents_setup.save_config",
    ) as save_config, patch(
        "agents_setup.save_agent_config",
    ) as save_agent, patch(
        "agents_setup._seed_persona_md_files",
    ), patch(
        "agents_setup.WORKING_DIR",
        tmp_path,
    ):
        ensure_builtin_agents()

    # Already present → save_config should NOT be called.
    save_config.assert_not_called()
    # save_agent_config is still allowed (keeps agent.json synced).
    assert save_agent.call_count == 1


# ---------------------------------------------------------------------------
# _seed_persona_md_files
# ---------------------------------------------------------------------------


def test_seed_persona_md_files_copies_zh(tmp_path):
    """zh default: both SOUL.md and PROFILE.md copied into the workspace."""
    from agents_setup import _seed_persona_md_files

    _seed_persona_md_files(tmp_path, language="zh")

    assert (tmp_path / "SOUL.md").exists()
    assert (tmp_path / "PROFILE.md").exists()
    assert "DataPaw" in (tmp_path / "SOUL.md").read_text(encoding="utf-8")


def test_seed_persona_md_files_copies_en(tmp_path):
    """en path: copy the English version."""
    from agents_setup import _seed_persona_md_files

    _seed_persona_md_files(tmp_path, language="en")

    assert (tmp_path / "SOUL.md").exists()
    text = (tmp_path / "SOUL.md").read_text(encoding="utf-8")
    # en/SOUL.md begins with "DataPaw is a reasoning..." up top.
    assert "DataPaw is" in text


def test_seed_persona_md_files_unknown_language_falls_back_to_zh(tmp_path):
    """Unknown language → fall back to zh."""
    from agents_setup import _seed_persona_md_files

    _seed_persona_md_files(tmp_path, language="ja")

    assert (tmp_path / "SOUL.md").exists()
    assert "DataPaw" in (tmp_path / "SOUL.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# uninstall_builtin_agents
# ---------------------------------------------------------------------------


def test_uninstall_builtin_agents_removes_profile_and_workspace(tmp_path):
    """Uninstall: drop datapaw profile and rmtree the workspace dir."""
    from agents_setup import uninstall_builtin_agents
    from qwenpaw.config.config import AgentProfileRef

    ws_dir = tmp_path / "workspaces" / "datapaw"
    ws_dir.mkdir(parents=True)
    (ws_dir / "marker").write_text("x", encoding="utf-8")
    (ws_dir / "agent.json").write_text("{}", encoding="utf-8")

    fake_cfg = _fake_config(
        profiles={
            "datapaw": AgentProfileRef(
                id="datapaw",
                workspace_dir=str(ws_dir),
            ),
        },
    )
    fake_cfg.agents.active_agent = "default"

    with patch("agents_setup.load_config", return_value=fake_cfg), patch(
        "agents_setup.save_config",
    ) as save_config_mock:
        uninstall_builtin_agents()

    assert "datapaw" not in fake_cfg.agents.profiles, "profile was not removed"
    save_config_mock.assert_called_once_with(fake_cfg)
    assert not ws_dir.exists(), "workspace dir was not removed"


def test_uninstall_builtin_agents_resets_active_agent_when_datapaw(tmp_path):
    """If active_agent points to datapaw, uninstall resets it to default."""
    from agents_setup import uninstall_builtin_agents
    from qwenpaw.config.config import AgentProfileRef

    ws_dir = tmp_path / "workspaces" / "datapaw"
    ws_dir.mkdir(parents=True)

    fake_cfg = _fake_config(
        profiles={
            "datapaw": AgentProfileRef(
                id="datapaw",
                workspace_dir=str(ws_dir),
            ),
        },
    )
    fake_cfg.agents.active_agent = "datapaw"

    with patch("agents_setup.load_config", return_value=fake_cfg), patch(
        "agents_setup.save_config",
    ):
        uninstall_builtin_agents()

    assert fake_cfg.agents.active_agent == "default"


def test_uninstall_builtin_agents_noop_when_not_installed(tmp_path):
    """No profile present → silently return."""
    from agents_setup import uninstall_builtin_agents

    fake_cfg = _fake_config(profiles={})

    with patch("agents_setup.load_config", return_value=fake_cfg), patch(
        "agents_setup.save_config",
    ) as save_config_mock:
        uninstall_builtin_agents()

    save_config_mock.assert_not_called()


# ---------------------------------------------------------------------------
# _install_plugin_skills
# ---------------------------------------------------------------------------


def test_install_plugin_skills_copies_skills_into_workspace(tmp_path):
    """All plugin-bundled skill dirs land under workspace/skills/."""
    from agents_setup import _install_plugin_skills

    _install_plugin_skills(tmp_path)

    ws_skills = tmp_path / "skills"
    # Spot-check representative skills (bi-* and analysis-plan-builder).
    assert (ws_skills / "analysis-plan-builder" / "SKILL.md").exists()
    assert (ws_skills / "bi-anomaly-detection" / "SKILL.md").exists()
    assert (ws_skills / "bi-report-generation" / "SKILL.md").exists()


def test_install_plugin_skills_writes_enabled_manifest(tmp_path):
    """In skill.json, plugin skills get enabled=True + source set."""
    from agents_setup import _install_plugin_skills

    _install_plugin_skills(tmp_path)

    import json as _json

    manifest_path = tmp_path / "skill.json"
    assert manifest_path.exists()
    manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))

    skills = manifest["skills"]
    # At a minimum, these three core skills must be present and enabled.
    for required in (
        "analysis-plan-builder",
        "bi-anomaly-detection",
        "bi-report-generation",
    ):
        assert required in skills, f"manifest is missing {required}"
        entry = skills[required]
        assert entry["enabled"] is True
        assert entry["source"] == "plugin:datapaw"
        assert "all" in entry["channels"]


def test_install_plugin_skills_idempotent(tmp_path):
    """Repeated calls must not produce duplicates or flip enabled."""
    from agents_setup import _install_plugin_skills
    import json as _json

    _install_plugin_skills(tmp_path)
    manifest1 = _json.loads(
        (tmp_path / "skill.json").read_text(encoding="utf-8"),
    )
    skills1 = list(manifest1["skills"].keys())

    _install_plugin_skills(tmp_path)
    manifest2 = _json.loads(
        (tmp_path / "skill.json").read_text(encoding="utf-8"),
    )
    skills2 = list(manifest2["skills"].keys())

    assert sorted(skills1) == sorted(skills2)
    # enabled remains True.
    for name in skills1:
        if manifest2["skills"][name]["source"] == "plugin:datapaw":
            assert manifest2["skills"][name]["enabled"] is True


def test_install_plugin_skills_preserves_user_customized_skills(tmp_path):
    """User-installed customized skills must stay untouched on install."""
    from agents_setup import _install_plugin_skills
    import json as _json

    # Install once so the manifest file exists.
    _install_plugin_skills(tmp_path)

    # Simulate a user-customized skill: add a my-custom dir + manifest entry.
    custom_skill = tmp_path / "skills" / "my-custom"
    custom_skill.mkdir(parents=True)
    (custom_skill / "SKILL.md").write_text(
        "---\nname: my-custom\ndescription: user skill\n---\n# my-custom\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "skill.json"
    manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["skills"]["my-custom"] = {
        "enabled": False,  # user intentionally left it disabled
        "channels": ["all"],
        "source": "customized",
    }
    manifest_path.write_text(_json.dumps(manifest), encoding="utf-8")

    # Second install: plugin skills keep state; customized untouched.
    _install_plugin_skills(tmp_path)

    manifest2 = _json.loads(manifest_path.read_text(encoding="utf-8"))
    custom_entry = manifest2["skills"].get("my-custom")
    assert custom_entry is not None, "user skill was accidentally removed"
    assert (
        custom_entry["enabled"] is False
    ), "plugin install wrongly flipped user skill's enabled"
    assert custom_entry["source"] == "customized"
