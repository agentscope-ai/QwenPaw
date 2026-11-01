# -*- coding: utf-8 -*-
"""Changed-file planning against the Console and official plugin layout."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check-channels.sh"
CONSOLE_TEST = "tests/contract/channels/test_console_contract.py"
ALL_TESTS = {
    "tests/contract/channels",
    "tests/unit/channels",
    "tests/unit/plugins/test_plugin_process.py",
}

pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="requires a POSIX-compatible Bash runtime",
)


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _run_script(
    tmp_path: Path,
    *,
    target: str = "--changed",
    changed_paths: tuple[str, ...] = (),
    untracked_paths: tuple[str, ...] = (),
    deleted_paths: tuple[str, ...] = (),
    git_diff_fails: bool = False,
    checker_fails: bool = False,
    pytest_fails: bool = False,
) -> subprocess.CompletedProcess[str]:
    repo = tmp_path / "repo"
    script = repo / "scripts" / "check-channels.sh"
    script.parent.mkdir(parents=True)
    shutil.copyfile(SCRIPT_PATH, script)
    # Keep manifest discovery real: no fabricated built-in plugin contracts.
    for manifest in (REPO_ROOT / "plugins/channel").glob("*/channel.json"):
        destination = repo / manifest.relative_to(REPO_ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(manifest, destination)
    for relative_path in (CONSOLE_TEST, *changed_paths, *untracked_paths):
        changed_file = repo / relative_path
        changed_file.parent.mkdir(parents=True, exist_ok=True)
        if not changed_file.exists():
            changed_file.write_text("# fixture\n", encoding="utf-8")

    for relative_path in deleted_paths:
        (repo / relative_path).unlink()

    bin_dir = tmp_path / "bin"
    _write_executable(
        bin_dir / "git",
        """#!/usr/bin/env bash
case "${1:-}" in
    diff)
        [ "${FAKE_GIT_DIFF_FAIL:-0}" = "1" ] && exit 7
        printf '%s\\n' "${FAKE_CHANGED_FILES:-}"
        ;;
    ls-files)
        printf '%s\\n' "${FAKE_UNTRACKED_FILES:-}"
        ;;
    *) exit 2 ;;
esac
""",
    )
    fake_python = bin_dir / "fake-python"
    _write_executable(
        fake_python,
        f"#!{sys.executable}\n"
        + """import json
import os
import subprocess
import sys
args = sys.argv[1:]
with open(os.environ["FAKE_PYTHON_LOG"], "a") as stream:
    stream.write(json.dumps(args) + "\\n")
if args == ["-"]:
    raise SystemExit(subprocess.call([sys.executable, "-"], stdin=sys.stdin))
if args == ["scripts/check_channel_contracts.py", "--list-specs"]:
    print("console\\tconsole\\ttests/contract/channels/test_console_contract.py")
    raise SystemExit(0)
if args == ["scripts/check_channel_contracts.py"]:
    raise SystemExit(int(os.environ["FAKE_CHECKER_FAIL"]))
if args[:2] == ["-m", "pytest"]:
    print("pytest diagnostic output")
    deleted = json.loads(os.environ["FAKE_DELETED_PATHS"])
    if any(path in args for path in deleted):
        raise SystemExit(4)
    raise SystemExit(int(os.environ["FAKE_PYTEST_FAIL"]))
raise SystemExit(0)
""",
    )
    env = os.environ.copy()
    env.update(
        {
            "FAKE_DELETED_PATHS": json.dumps(deleted_paths),
            "FAKE_CHANGED_FILES": "\n".join(changed_paths),
            "FAKE_UNTRACKED_FILES": "\n".join(untracked_paths),
            "FAKE_GIT_DIFF_FAIL": str(int(git_diff_fails)),
            "FAKE_CHECKER_FAIL": str(int(checker_fails)),
            "FAKE_PYTEST_FAIL": str(int(pytest_fails)),
            "FAKE_PYTHON_LOG": str(tmp_path / "python.log"),
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "PYTHON_BIN": str(fake_python),
        },
    )
    return subprocess.run(
        ["bash", str(script), target],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _pytest_paths(tmp_path: Path) -> list[list[str]]:
    path = tmp_path / "python.log"
    calls = [json.loads(line) for line in path.read_text().splitlines()]
    return [call[2:-2] for call in calls if call[:2] == ["-m", "pytest"]]


@pytest.mark.parametrize(
    "changed_path",
    [
        "plugins/channel/discord/qwenpaw_channel_discord/driver.py",
        "plugins/channel/discord/channel.json",
        "plugins/channel/discord/requirements.txt",
        "tests/unit/channels/test_discord.py",
    ],
)
def test_plugin_change_selects_driver_unit_test(tmp_path, changed_path):
    result = _run_script(tmp_path, changed_paths=(changed_path,))
    assert result.returncode == 0, result.stdout + result.stderr
    assert _pytest_paths(tmp_path) == [["tests/unit/channels/test_discord.py"]]


def test_untracked_plugin_source_is_discovered(tmp_path):
    result = _run_script(
        tmp_path,
        untracked_paths=("plugins/channel/discord/new.py",),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _pytest_paths(tmp_path) == [["tests/unit/channels/test_discord.py"]]


@pytest.mark.parametrize("target", ["discord", "sip", "console"])
def test_explicit_channel_uses_current_layout(tmp_path, target):
    result = _run_script(tmp_path, target=target)
    assert result.returncode == 0, result.stdout + result.stderr
    expected = (
        CONSOLE_TEST
        if target == "console"
        else f"tests/unit/channels/test_{target}.py"
    )
    assert _pytest_paths(tmp_path) == [[expected]]


@pytest.mark.parametrize(
    "changed_path",
    ["src/qwenpaw/app/channels/console/channel.py", CONSOLE_TEST],
)
def test_console_change_runs_console_contract(tmp_path, changed_path):
    result = _run_script(tmp_path, changed_paths=(changed_path,))
    assert result.returncode == 0, result.stdout + result.stderr
    assert _pytest_paths(tmp_path) == [[CONSOLE_TEST]]


def test_multiple_changed_unit_files_run_together(tmp_path):
    paths = (
        "tests/unit/channels/test_channel_host.py",
        "tests/unit/channels/test_discord.py",
    )
    result = _run_script(tmp_path, changed_paths=paths)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _pytest_paths(tmp_path) == [sorted(paths)]


@pytest.mark.parametrize(
    "common_path",
    [
        "src/qwenpaw/app/channels/base.py",
        "src/qwenpaw/plugins/channel_adapter.py",
        "src/qwenpaw/plugins/official_execution_context.py",
        "src/qwenpaw/plugins/execution_backend.py",
        "src/qwenpaw/config/channel_config_compat.py",
        "src/qwenpaw/plugins/execution/channel.py",
        "src/qwenpaw/channel_protocol/models.py",
        "tests/channel_support/helpers.py",
        "tests/conftest.py",
        "tests/unit/channels/conftest.py",
        "tests/contract/channels/__init__.py",
        "scripts/check_channel_contracts.py",
        "scripts/check-channels.sh",
    ],
)
def test_common_channel_file_runs_bounded_all_checks(tmp_path, common_path):
    result = _run_script(tmp_path, changed_paths=(common_path,))
    assert result.returncode == 0, result.stdout + result.stderr
    assert _pytest_paths(tmp_path) == [sorted(ALL_TESTS)]


def test_all_runs_only_channel_and_process_checks(tmp_path):
    result = _run_script(tmp_path, target="all")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _pytest_paths(tmp_path) == [sorted(ALL_TESTS)]


def test_unrelated_change_exits_without_pytest(tmp_path):
    result = _run_script(tmp_path, changed_paths=("README.md",))
    assert result.returncode == 0, result.stdout + result.stderr
    assert _pytest_paths(tmp_path) == []


def test_git_diff_failure_is_not_hidden(tmp_path):
    result = _run_script(tmp_path, git_diff_fails=True)
    assert result.returncode != 0
    assert _pytest_paths(tmp_path) == []


def test_unknown_explicit_channel_is_rejected(tmp_path):
    result = _run_script(tmp_path, target="unknown")
    assert result.returncode != 0
    assert "Unknown channel" in result.stdout + result.stderr
    assert _pytest_paths(tmp_path) == []


@pytest.mark.parametrize("target", ["console", "sip", "all"])
@pytest.mark.parametrize("failure", ["checker", "pytest"])
def test_every_check_failure_blocks_runner(tmp_path, target, failure):
    result = _run_script(
        tmp_path,
        target=target,
        checker_fails=failure == "checker",
        pytest_fails=failure == "pytest",
    )
    assert result.returncode == 1
    assert "pytest diagnostic output" in result.stdout
    assert _pytest_paths(tmp_path)


@pytest.mark.parametrize(
    "deleted_path",
    [
        "tests/unit/channels/test_discord.py",
        "tests/unit/channels/test_channel_host.py",
        "tests/unit/plugins/test_plugin_process.py",
        CONSOLE_TEST,
        "plugins/channel/discord/channel.json",
    ],
)
@pytest.mark.parametrize("with_common_change", [False, True])
def test_deleted_check_path_is_rejected(
    tmp_path,
    deleted_path,
    with_common_change,
):
    result = _run_script(
        tmp_path,
        changed_paths=(deleted_path,)
        + (
            ("src/qwenpaw/app/channels/base.py",) if with_common_change else ()
        ),
        deleted_paths=(deleted_path,),
    )
    assert result.returncode == 1
    assert f"Missing channel check path: {deleted_path}" in (
        result.stdout + result.stderr
    )
    assert _pytest_paths(tmp_path) == []


@pytest.mark.parametrize("with_common_change", [False, True])
def test_noncanonical_contract_path_is_rejected(tmp_path, with_common_change):
    path = "tests/contract/channels/test_unknown_contract.py"
    result = _run_script(
        tmp_path,
        changed_paths=(path,)
        + (
            ("src/qwenpaw/app/channels/base.py",) if with_common_change else ()
        ),
    )
    assert result.returncode != 0
    assert "Non-canonical channel contract path" in (
        result.stdout + result.stderr
    )
    assert _pytest_paths(tmp_path) == []


def test_real_manifests_load_with_non_utf8_locale(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("PYTHONUTF8", "0")
    monkeypatch.setenv("PYTHONCOERCECLOCALE", "0")
    result = _run_script(tmp_path, target="discord")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _pytest_paths(tmp_path) == [["tests/unit/channels/test_discord.py"]]


def test_manifest_discovery_emits_posix_source_paths(monkeypatch, capsys):
    # Execute the real discovery code with Windows path semantics; this does
    # not claim to exercise a native Windows shell or filesystem.
    discovery = (
        SCRIPT_PATH.read_text(encoding="utf-8")
        .split(
            "<<'PY'\n",
            1,
        )[1]
        .split("\nPY\n", 1)[0]
    )
    manifest_path = REPO_ROOT / "plugins/channel/discord/channel.json"

    class WindowsManifest(PureWindowsPath):
        def read_text(self, **kwargs):
            return manifest_path.read_text(**kwargs)

    manifest = WindowsManifest("plugins/channel/discord/channel.json")

    class ManifestRoot:
        def glob(self, pattern):
            assert pattern == "*/channel.json"
            return [manifest]

    with monkeypatch.context() as patch:
        patch.setattr("pathlib.Path", lambda root: ManifestRoot())
        exec(discovery, {})
    assert capsys.readouterr().out == (
        "discord\tplugins/channel/discord\t"
        "tests/unit/channels/test_discord.py\n"
    )
