# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
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
