# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import runpy

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = REPO_ROOT / "scripts" / "pack-tauri" / "qwenpaw.spec"


def _collected_submodule_packages() -> set[str]:
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    packages = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "collect_submodules" or not node.args:
            continue
        package = node.args[0]
        if isinstance(package, ast.Constant) and isinstance(
            package.value,
            str,
        ):
            packages.add(package.value)
    return packages


def _called_packages(function_name: str) -> set[str]:
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    packages = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name):
            continue
        if node.func.id != function_name or not node.args:
            continue
        package = node.args[0]
        if isinstance(package, ast.Constant) and isinstance(
            package.value,
            str,
        ):
            packages.add(package.value)
    return packages


def _metadata_packages() -> set[str]:
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "_metadata_pkgs"
            for target in node.targets
        ):
            continue
        return {
            item.value
            for item in node.value.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
    return set()


def _data_directories() -> set[tuple[str, str]]:
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "_data_dirs"
            for target in node.targets
        ):
            continue
        return {
            (source.value, target.value)
            for item in node.value.elts
            if isinstance(item, ast.Tuple)
            for source, target in [item.elts]
            if isinstance(source, ast.Constant)
            and isinstance(source.value, str)
            and isinstance(target, ast.Constant)
            and isinstance(target.value, str)
        }
    return set()


def _analysis_path_names() -> set[str]:
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    analysis = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Analysis"
    )
    pathex = next(
        keyword.value
        for keyword in analysis.keywords
        if keyword.arg == "pathex"
    )
    return {node.id for node in ast.walk(pathex) if isinstance(node, ast.Name)}


def _load_spec_function(name: str):
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    module = ast.fix_missing_locations(
        ast.Module(body=[function], type_ignores=[]),
    )
    namespace = {"Path": Path}
    exec(compile(module, SPEC_PATH, "exec"), namespace)  # noqa: S102
    return namespace[name]


def test_desktop_spec_collects_pawapp_sdk_for_runtime_loaded_plugins():
    assert "qwenpaw.pawapp" in _collected_submodule_packages()


def test_desktop_spec_collects_qwenpawmail_from_nested_source_root():
    assert "qwenpawmail_mcp" in _collected_submodule_packages()
    assert "MAIL_MCP_SRC" in _analysis_path_names()


def test_desktop_spec_collects_provider_catalog_data():
    assert (
        "providers/data",
        "qwenpaw/providers/data",
    ) in _data_directories()


def test_desktop_spec_collects_reme_entry_point_plugins():
    plugin_modules = {"reme_auto_fin", "reme_daily_paper"}
    plugin_distributions = {"reme-auto-fin", "reme-daily-paper"}

    assert plugin_modules <= _collected_submodule_packages()
    assert plugin_modules <= _called_packages("collect_data_files")
    assert {"reme-ai", *plugin_distributions} <= _metadata_packages()


def test_desktop_spec_reaches_analysis_without_vendor_sdks(
    tmp_path,
    monkeypatch,
) -> None:
    """Run real collectors with a bounded installed full dependency graph."""
    assert importlib.util.find_spec("qoder_agent_sdk") is None
    assert importlib.util.find_spec("codex_cli_bin") is None

    # The core test environment does not install desktop's full extra. Its
    # editable metadata may also predate a dependency move to a plugin.
    # Keep the selected full graph explicit while collecting its installed
    # transitive distributions through the production metadata collector.
    metadata = tmp_path / "qwenpaw-0.0.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: qwenpaw\nVersion: 0.0.0\n"
        "Provides-Extra: full\n"
        "Requires-Dist: openai; extra == 'full'\n"
        "Requires-Dist: pydantic; extra == 'full'\n"
        "Requires-Dist: httpx; extra == 'full'\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    # Stage the real spec and collectors with a controlled Console input so
    # this backend unit test does not require a complete frontend build.
    staged_root = tmp_path / "repo"
    staged_pack = staged_root / "scripts" / "pack-tauri"
    staged_pack.mkdir(parents=True)
    for name in ("qwenpaw.spec", "collect_runtime_metadata.py"):
        (staged_pack / name).symlink_to(SPEC_PATH.parent / name)
    for name in ("src", "packages", "plugins"):
        (staged_root / name).symlink_to(
            REPO_ROOT / name,
            target_is_directory=True,
        )
    console_dist = staged_root / "console" / "dist"
    console_dist.mkdir(parents=True)
    (console_dist / "index.html").write_text(
        "<!doctype html>",
        encoding="utf-8",
    )

    class ReachedAnalysis(Exception):
        """Stop before the expensive onedir build."""

    collected_data = []

    def stop_at_analysis(*_args, **kwargs):
        collected_data.extend(kwargs["datas"])
        raise ReachedAnalysis

    with pytest.raises(ReachedAnalysis):
        runpy.run_path(
            str(staged_pack / "qwenpaw.spec"),
            init_globals={
                "SPECPATH": str(staged_pack),
                "Analysis": stop_at_analysis,
            },
        )

    metadata_names = {
        destination.partition("-")[0].replace("_", "-")
        for _source, destination in collected_data
        if destination.endswith(".dist-info")
    }
    host_transitives = {
        "typing-extensions",
        "typing-inspection",
        "annotated-types",
        "certifi",
        "jiter",
        "distro",
    }
    assert host_transitives <= metadata_names
    assert (
        not {
            "openai-codex",
            "codex-cli-bin",
            "qoder-agent-sdk",
        }
        & metadata_names
    )


def test_executable_scripts_preserves_runtime_hooks_and_selected_entry(
    tmp_path,
):
    executable_scripts = _load_spec_function("executable_scripts")
    backend_entry = tmp_path / "entry.py"
    cli_entry = tmp_path / "cli_entry.py"
    inspect_hook = tmp_path / "pyi_rth_inspect.py"
    multiprocessing_hook = tmp_path / "pyi_rth_multiprocessing.py"
    future_hook = tmp_path / "future_runtime_hook.py"
    scripts = [
        ("pyi_rth_inspect", str(inspect_hook), "PYSOURCE"),
        (
            "pyi_rth_multiprocessing",
            str(multiprocessing_hook),
            "PYSOURCE",
        ),
        ("future_runtime_hook", str(future_hook), "PYSOURCE"),
        ("entry", str(backend_entry), "PYSOURCE"),
        ("cli_entry", str(cli_entry), "PYSOURCE"),
    ]
    entry_scripts = (backend_entry, cli_entry)

    backend_scripts = executable_scripts(
        scripts,
        backend_entry,
        entry_scripts,
    )
    cli_scripts = executable_scripts(scripts, cli_entry, entry_scripts)

    assert backend_scripts == [*scripts[:3], scripts[3]]
    assert cli_scripts == [*scripts[:3], scripts[4]]


@pytest.mark.parametrize("entry_count", [0, 2])
def test_executable_scripts_requires_exactly_one_selected_entry(
    tmp_path,
    entry_count,
):
    executable_scripts = _load_spec_function("executable_scripts")
    backend_entry = tmp_path / "entry.py"
    cli_entry = tmp_path / "cli_entry.py"
    runtime_hook = tmp_path / "runtime_hook.py"
    scripts = [
        ("runtime_hook", str(runtime_hook), "PYSOURCE"),
        *[
            ("entry", str(backend_entry), "PYSOURCE")
            for _ in range(entry_count)
        ],
        ("cli_entry", str(cli_entry), "PYSOURCE"),
    ]

    with pytest.raises(SystemExit, match="must appear exactly once"):
        executable_scripts(
            scripts,
            backend_entry,
            (backend_entry, cli_entry),
        )
