# -*- coding: utf-8 -*-
"""Real update-worker subprocess sequencing and failure propagation."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    ("install_status", "prepare_status", "status", "phases"),
    [
        (0, 0, 0, ["install", "prepare"]),
        (23, 0, 23, ["install"]),
        (0, 29, 29, ["install", "prepare"]),
    ],
    ids=["install-then-prepare", "failed-install", "failed-preparation"],
)
def test_update_worker_prepares_after_successful_install(
    tmp_path,
    capsys,
    install_status,
    prepare_status,
    status,
    phases,
):
    """Dropping or ignoring the second process must not produce success."""
    from qwenpaw.cli.update_cmd import run_update_worker

    marker = tmp_path / "phases"

    def command(phase, exit_status):
        return [
            sys.executable,
            "-I",
            "-c",
            "from pathlib import Path; "
            f"path=Path({str(marker)!r}); "
            f"path.open('a').write({phase + chr(10)!r}); "
            f"raise SystemExit({exit_status})",
        ]

    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "command": command("install", install_status),
                "prepare_channels_command": command("prepare", prepare_status),
                "current_version": "0.0.1",
                "latest_version": "0.0.2",
                "installer_label": "offline subprocess fixture",
            },
        ),
    )
    assert run_update_worker(plan) == status
    assert marker.read_text().splitlines() == phases
    assert not plan.exists()
    output = capsys.readouterr().out
    assert ("Update completed successfully" in output) is (status == 0)
    if status:
        assert f"Update failed with exit code {status}" in output


@pytest.mark.skipif(sys.platform == "win32", reason="Unix user-site fixture")
def test_update_preparation_supports_user_site_without_shadow_imports(
    tmp_path,
    monkeypatch,
):
    """Isolated-mode flags must not hide a pip --user installation."""
    from click.testing import CliRunner
    from qwenpaw.cli import update_cmd as module

    python = sys._base_executable  # Run outside this test interpreter's venv.
    info = module.InstallInfo(
        package_dir="unused",
        python_executable=python,
        environment_root=sys.base_prefix,
        environment_kind="system",
        installer="pip",
        source_type="pypi",
    )
    monkeypatch.setattr(module, "_detect_installation", lambda: info)
    monkeypatch.setattr(module, "_fetch_latest_version", lambda **_: "99.0.0")
    monkeypatch.setattr(
        module,
        "_detect_running_service",
        lambda *_: module.RunningServiceInfo(False),
    )
    monkeypatch.setattr(module, "_plan_dir", lambda: tmp_path)
    captured = {}

    def capture(plan_path):
        captured.update(json.loads(plan_path.read_text()))
        plan_path.unlink()
        return 0

    monkeypatch.setattr(module, "_run_update_worker_foreground", capture)
    result = CliRunner().invoke(module.update_cmd, ["--yes"])
    assert result.exit_code == 0, result.output
    command = captured["prepare_channels_command"]
    assert command[0] == python
    assert command[-4:] == ["-m", "qwenpaw", "plugins", "prepare-upgrade"]
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PYTHON")
    }
    env["HOME"] = str(tmp_path / "home")
    site = subprocess.check_output(
        [python, "-c", "import site; print(site.getusersitepackages())"],
        env=env,
        text=True,
    ).strip()
    user_site = Path(site)
    user_site.mkdir(parents=True)
    probe = "channel_upgrade_user_site_probe"
    (user_site / (probe + ".py")).write_text("print('fresh-user-site')\n")
    (tmp_path / (probe + ".py")).write_text("raise SystemExit(91)\n")
    env["PYTHONPATH"] = str(tmp_path)
    command[command.index("-m") + 1] = probe
    result = subprocess.run(
        command,
        env=env,
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "fresh-user-site"
