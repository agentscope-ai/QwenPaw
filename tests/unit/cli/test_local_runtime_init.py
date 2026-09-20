# -*- coding: utf-8 -*-
"""Local Hub initialization preserves existing user settings."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from qwenpaw.cli import app_cmd as app_module

from qwenpaw.cli import init_cmd as module


@pytest.mark.parametrize("existing", [False, True])
def test_local_initialization_runs_once(tmp_path, monkeypatch, existing):
    config_path = tmp_path / "config.json"
    heartbeat = tmp_path / "HEARTBEAT.md"
    workspace = tmp_path / "custom-workspace"
    if existing:
        config_path.write_text("user configuration", encoding="utf-8")
        heartbeat.write_text("user heartbeat", encoding="utf-8")
    monkeypatch.setattr(module, "get_config_path", lambda: config_path)
    monkeypatch.setattr(module, "get_heartbeat_query_path", lambda: heartbeat)
    monkeypatch.setattr(
        module,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                language="zh",
                profiles={
                    "default": SimpleNamespace(workspace_dir=str(workspace)),
                },
            ),
        ),
    )
    monkeypatch.setattr(module, "ensure_skill_pool_initialized", Mock())
    initialize = Mock()
    sync_skills = Mock()
    copy_files = Mock()
    monkeypatch.setattr(module.init_cmd, "callback", initialize)
    monkeypatch.setattr(module, "_sync_default_workspace_skills", sync_skills)
    monkeypatch.setattr(module, "copy_md_files", copy_files)

    module.ensure_local_runtime_initialized()
    module.ensure_local_runtime_initialized()

    if existing:
        initialize.assert_not_called()
        sync_skills.assert_called_once_with(workspace)
        copy_files.assert_called_once_with(
            "zh",
            skip_existing=True,
            workspace_dir=workspace,
        )
        assert config_path.read_text(encoding="utf-8") == "user configuration"
        assert heartbeat.read_text(encoding="utf-8") == "user heartbeat"
    else:
        initialize.assert_called_once_with(
            force=False,
            use_defaults=True,
            accept_security=True,
        )
    assert (tmp_path / ".hub-initialized").is_file()


@pytest.mark.parametrize("provisioner", ["local", "docker", ""])
def test_app_initializes_only_local_hub_runtime(monkeypatch, provisioner):
    monkeypatch.setenv("QWENPAW_RUNTIME_PROVISIONER", provisioner)
    monkeypatch.setenv("QWENPAW_RUNTIME_ID", "test-runtime")
    initialize = Mock()
    monkeypatch.setattr(
        app_module,
        "ensure_local_runtime_initialized",
        initialize,
    )
    monkeypatch.setattr(app_module, "configure_server_process", Mock())
    monkeypatch.setattr(
        app_module,
        "_warn_if_auth_off_non_loopback_bind",
        Mock(),
    )
    monkeypatch.setattr(app_module.uvicorn, "run", Mock())
    result = CliRunner().invoke(app_module.app_cmd, [])
    assert result.exit_code == 0, result.output
    assert initialize.call_count == (1 if provisioner == "local" else 0)
