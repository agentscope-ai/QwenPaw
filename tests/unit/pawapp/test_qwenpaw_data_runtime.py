# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_FILE = (
    REPOSITORY_ROOT
    / "plugins"
    / "apps"
    / "qwenpaw-data"
    / "backend"
    / "runtime.py"
)
APP_DIR = REPOSITORY_ROOT / "plugins" / "apps" / "qwenpaw-data"


def _load_runtime_module():
    spec = importlib.util.spec_from_file_location(
        "qwenpaw_data_app_runtime_under_test",
        RUNTIME_FILE,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_context_python_preserves_virtualenv_launcher_symlink(
    tmp_path: Path,
) -> None:
    runtime = _load_runtime_module()
    base_python = tmp_path / "base-python"
    base_python.write_text("", encoding="utf-8")
    launcher = tmp_path / ".venv-qwenpaw-data" / "bin" / "python"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(base_python)
    runtime.PLUGIN_DIR = tmp_path

    selected = runtime.context_python()

    assert selected == launcher.absolute()
    assert selected != launcher.resolve()


def test_runtime_packages_available_probes_service_entrypoints(
    monkeypatch,
) -> None:
    runtime = _load_runtime_module()
    imported: list[str] = []

    def import_module(name: str) -> object:
        imported.append(name)
        return object()

    monkeypatch.setattr(runtime.importlib, "import_module", import_module)

    assert runtime.runtime_packages_available()
    assert imported == [
        "context_manager.api.server",
        "qwenpaw_data.host.core.api.app",
    ]


def test_runtime_packages_unavailable_when_engine_entrypoint_is_missing(
    monkeypatch,
) -> None:
    runtime = _load_runtime_module()

    def import_module(name: str) -> object:
        if name == "qwenpaw_data.host.core.api.app":
            raise ImportError(name)
        return object()

    monkeypatch.setattr(runtime.importlib, "import_module", import_module)

    assert not runtime.runtime_packages_available()


def test_skill_layers_return_only_category_directories(tmp_path: Path) -> None:
    runtime = _load_runtime_module()
    analytics = tmp_path / "analytics"
    (analytics / "metric-review").mkdir(parents=True)
    (analytics / "metric-review" / "SKILL.md").write_text(
        "# Metric review",
        encoding="utf-8",
    )
    (tmp_path / "empty").mkdir()

    assert runtime.skill_layers(tmp_path) == [analytics]


def test_backend_entry_loads_with_plugin_loader_package_shape() -> None:
    module_name = "plugin_qwenpaw_data_contract_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        APP_DIR / "backend" / "main.py",
        submodule_search_locations=[str(APP_DIR)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    module.__package__ = module_name
    module.__path__ = [str(APP_DIR)]
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        assert module.app.app_id == "qwenpaw-data"
        assert module.plugin is module.app
    finally:
        for loaded_name in list(sys.modules):
            if loaded_name == module_name or loaded_name.startswith(
                f"{module_name}.",
            ):
                sys.modules.pop(loaded_name, None)


def test_provision_engine_mcp_creates_databridge_entry(tmp_path: Path) -> None:
    runtime = _load_runtime_module()
    path = runtime.provision_engine_mcp(
        tmp_path,
        "http://127.0.0.1:8765/",
        "cm-token",
    )
    assert path == tmp_path / "host" / "workspace" / ".mcp"
    entries = json.loads(path.read_text(encoding="utf-8"))
    assert len(entries) == 1
    entry = entries[0]
    assert entry["name"] == "databridge"
    assert entry["mcp_config"]["url"] == "http://127.0.0.1:8765/mcp/v1/cm"
    assert entry["mcp_config"]["headers"] == {
        "Authorization": "Bearer cm-token",
    }


def test_provision_engine_mcp_without_token_sends_no_auth_header(
    tmp_path: Path,
) -> None:
    runtime = _load_runtime_module()
    path = runtime.provision_engine_mcp(tmp_path, "http://cm.local", "")
    entries = json.loads(path.read_text(encoding="utf-8"))
    assert entries[0]["mcp_config"]["headers"] == {}


def test_provision_engine_mcp_upserts_and_preserves_user_entries(
    tmp_path: Path,
) -> None:
    runtime = _load_runtime_module()
    workspace = tmp_path / "host" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / ".mcp").write_text(
        json.dumps(
            [
                {"name": "custom-tool", "mcp_config": {"url": "http://x"}},
                {
                    "name": "databridge",
                    "mcp_config": {"url": "http://stale:1/mcp/v1/cm"},
                },
            ],
        ),
        encoding="utf-8",
    )
    path = runtime.provision_engine_mcp(tmp_path, "http://cm:9", "t")
    entries = json.loads(path.read_text(encoding="utf-8"))
    names = [e["name"] for e in entries]
    assert names == ["databridge", "custom-tool"]
    assert entries[0]["mcp_config"]["url"] == "http://cm:9/mcp/v1/cm"


def test_provision_engine_mcp_recovers_from_corrupt_file(
    tmp_path: Path,
) -> None:
    runtime = _load_runtime_module()
    workspace = tmp_path / "host" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / ".mcp").write_text("not-json{", encoding="utf-8")
    path = runtime.provision_engine_mcp(tmp_path, "http://cm:9", "")
    entries = json.loads(path.read_text(encoding="utf-8"))
    assert [e["name"] for e in entries] == ["databridge"]


def test_provision_engine_mcp_skips_without_cm_url(tmp_path: Path) -> None:
    runtime = _load_runtime_module()
    assert runtime.provision_engine_mcp(tmp_path, "", "t") is None
    assert not (tmp_path / "host").exists()
