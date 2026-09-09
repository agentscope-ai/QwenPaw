# -*- coding: utf-8 -*-
"""Regression tests for changed-file planning in check-channels.sh."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check-channels.sh"

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
    git_diff_fails: bool = False,
    checker_fails: bool = False,
    contract_fails: bool = False,
    unit_fails: bool = False,
) -> subprocess.CompletedProcess[str]:
    repo = tmp_path / "repo"
    script = repo / "scripts" / "check-channels.sh"
    script.parent.mkdir(parents=True)
    shutil.copyfile(SCRIPT_PATH, script)
    script.chmod(0o755)

    for key in ("discord", "onebot", "sip"):
        contract = (
            repo
            / "tests"
            / "contract"
            / "channels"
            / f"test_{key}_contract.py"
        )
        contract.parent.mkdir(parents=True, exist_ok=True)
        contract.write_text("# fixture\n", encoding="utf-8")

    for relative_path in changed_paths + untracked_paths:
        changed_file = repo / relative_path
        changed_file.parent.mkdir(parents=True, exist_ok=True)
        changed_file.write_text("# changed\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    fake_git = bin_dir / "git"
    _write_executable(
        fake_git,
        """#!/usr/bin/env bash
if [ "${1:-}" = "-C" ]; then
    shift 2
fi
case "${1:-}" in
    rev-parse)
        printf 'true\n'
        ;;
    diff)
        if [ "${FAKE_GIT_DIFF_FAIL:-0}" = "1" ]; then
            exit 7
        fi
        printf '%s\n' "${FAKE_CHANGED_FILES:-}"
        ;;
    ls-files)
        printf '%s\n' "${FAKE_UNTRACKED_FILES:-}"
        ;;
    *)
        exit 2
        ;;
esac
""",
    )

    fake_python = bin_dir / "fake-python"
    _write_executable(
        fake_python,
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_PYTHON_LOG"
if [ "${1:-}" = "scripts/check_channel_contracts.py" ] && \
   [ "${2:-}" = "--list-specs" ]; then
    printf '%s' "$FAKE_REGISTRY_SPECS"
    exit 0
fi
if [ "${1:-}" = "scripts/check_channel_contracts.py" ] && \
   [ "${FAKE_CHECKER_FAIL:-0}" = "1" ]; then
    exit 8
fi
case "$*" in
    *"-m pytest tests/contract"*)
        [ "${FAKE_CONTRACT_FAIL:-0}" = "1" ] && exit 9
        ;;
    *"-m pytest tests/unit/channels"*)
        [ "${FAKE_UNIT_FAIL:-0}" = "1" ] && exit 10
        ;;
esac
exit 0
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "FAKE_CHANGED_FILES": "\n".join(changed_paths),
            "FAKE_UNTRACKED_FILES": "\n".join(untracked_paths),
            "FAKE_GIT_DIFF_FAIL": str(int(git_diff_fails)),
            "FAKE_CHECKER_FAIL": str(int(checker_fails)),
            "FAKE_CONTRACT_FAIL": str(int(contract_fails)),
            "FAKE_UNIT_FAIL": str(int(unit_fails)),
            "FAKE_PYTHON_LOG": str(tmp_path / "python.log"),
            "FAKE_REGISTRY_SPECS": (
                "discord\tdiscord_\t"
                "tests/contract/channels/test_discord_contract.py\n"
                "onebot\tonebot\t"
                "tests/contract/channels/test_onebot_contract.py\n"
                "sip\tsip\t"
                "tests/contract/channels/test_sip_contract.py\n"
            ),
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


def _python_log(tmp_path: Path) -> str:
    path = tmp_path / "python.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


@pytest.mark.parametrize(
    ("changed_path", "expected_channel"),
    [
        ("tests/unit/channels/test_base_core.py", None),
        ("tests/unit/channels/test_qrcode_auth_handler.py", None),
        ("tests/unit/channels/test_onebot_channel.py", "onebot"),
        ("tests/unit/channels/test_sip_memory_bounds.py", "sip"),
    ],
)
def test_changed_unit_file_is_run_without_inventing_channel_key(
    tmp_path: Path,
    changed_path: str,
    expected_channel: str | None,
) -> None:
    result = _run_script(tmp_path, changed_paths=(changed_path,))

    assert result.returncode == 0, result.stdout + result.stderr
    log = _python_log(tmp_path)
    assert f"-m pytest {changed_path} -v --tb=short" in log
    if expected_channel is None:
        assert "tests/contract/channels/test_" not in log
    else:
        expected_contract = (
            f"tests/contract/channels/test_{expected_channel}_contract.py"
        )
        assert f"-m pytest {expected_contract} -v --tb=short" in log


def test_source_directory_uses_registry_module_mapping(tmp_path: Path) -> None:
    result = _run_script(
        tmp_path,
        changed_paths=("src/qwenpaw/app/channels/discord_/channel.py",),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "-m pytest tests/contract/channels/test_discord_contract.py "
        "-v --tb=short"
    ) in _python_log(tmp_path)


def test_multiple_changed_unit_files_run_together(tmp_path: Path) -> None:
    paths = (
        "tests/unit/channels/test_base_core.py",
        "tests/unit/channels/test_qrcode_auth_handler.py",
    )

    result = _run_script(tmp_path, changed_paths=paths)

    assert result.returncode == 0, result.stdout + result.stderr
    log = _python_log(tmp_path)
    assert all(path in log for path in paths)


def test_untracked_channel_source_is_discovered(tmp_path: Path) -> None:
    result = _run_script(
        tmp_path,
        untracked_paths=("src/qwenpaw/app/channels/discord_/new.py",),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_discord_contract.py" in _python_log(tmp_path)


@pytest.mark.parametrize(
    "common_path",
    [
        "src/qwenpaw/app/channels/base.py",
        "tests/unit/channels/conftest.py",
        "tests/contract/channels/__init__.py",
        "scripts/check_channel_contracts.py",
    ],
)
def test_common_channel_file_runs_all_checks(
    tmp_path: Path,
    common_path: str,
) -> None:
    result = _run_script(tmp_path, changed_paths=(common_path,))

    assert result.returncode == 0, result.stdout + result.stderr
    log = _python_log(tmp_path)
    assert "-m pytest tests/contract/channels -v --tb=short" in log
    assert "-m pytest tests/unit/channels -v --tb=short" in log


def test_unrelated_change_exits_without_pytest(tmp_path: Path) -> None:
    result = _run_script(tmp_path, changed_paths=("README.md",))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "-m pytest" not in _python_log(tmp_path)


def test_git_diff_failure_is_not_hidden(tmp_path: Path) -> None:
    result = _run_script(tmp_path, git_diff_fails=True)

    assert result.returncode != 0


def test_noncanonical_contract_path_is_rejected(tmp_path: Path) -> None:
    path = "tests/contract/channels/test_unknown_contract.py"

    result = _run_script(tmp_path, changed_paths=(path,))

    assert result.returncode != 0
    assert "Non-canonical channel contract path" in result.stdout


def test_unknown_explicit_channel_is_rejected(tmp_path: Path) -> None:
    result = _run_script(tmp_path, target="unknown")

    assert result.returncode != 0
    assert "Unknown built-in channel" in result.stdout
    assert "-m pytest" not in _python_log(tmp_path)


@pytest.mark.parametrize("failure", ["checker", "contract"])
def test_required_check_failure_blocks_runner(
    tmp_path: Path,
    failure: str,
) -> None:
    result = _run_script(
        tmp_path,
        target="sip",
        checker_fails=failure == "checker",
        contract_fails=failure == "contract",
    )

    assert result.returncode == 1


def test_optional_unit_failure_does_not_block_runner(tmp_path: Path) -> None:
    unit_path = "tests/unit/channels/test_sip_memory_bounds.py"
    result = _run_script(
        tmp_path,
        target="sip",
        changed_paths=(unit_path,),
        unit_fails=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert unit_path in _python_log(tmp_path)
