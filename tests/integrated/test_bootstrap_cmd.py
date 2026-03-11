# -*- coding: utf-8 -*-
"""Integrated tests for runtime workspace bootstrap."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys


def _run_bootstrap(
    working_dir: str,
    secret_dir: str,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["COPAW_WORKING_DIR"] = working_dir
    env["COPAW_SECRET_DIR"] = secret_dir
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        env["PYTHONPATH"] = os.pathsep.join(["src", existing_pythonpath])
    else:
        env["PYTHONPATH"] = "src"
    return subprocess.run(
        [sys.executable, "-m", "copaw", "bootstrap"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_bootstrap_cmd_initializes_missing_workspace(tmp_path) -> None:
    working_dir = tmp_path / "working"
    secret_dir = tmp_path / "working.secret"

    result = _run_bootstrap(str(working_dir), str(secret_dir))

    assert result.returncode == 0, result.stderr or result.stdout
    assert (working_dir / "config.json").is_file()
    assert (working_dir / "AGENTS.md").is_file()
    assert (working_dir / "SOUL.md").is_file()
    assert (working_dir / "PROFILE.md").is_file()
    assert (working_dir / "MEMORY.md").is_file()
    assert (working_dir / "BOOTSTRAP.md").is_file()
    assert (working_dir / "HEARTBEAT.md").is_file()
    assert (working_dir / "active_skills").is_dir()

    config = json.loads(
        (working_dir / "config.json").read_text(encoding="utf-8"),
    )
    assert config["agents"]["installed_md_files_language"] == "zh"
    assert config["agents"]["defaults"]["heartbeat"]["every"] == "6h"
    assert config["agents"]["defaults"]["heartbeat"]["target"] == "main"


def test_bootstrap_cmd_repairs_partially_initialized_workspace(
    tmp_path,
) -> None:
    working_dir = tmp_path / "working"
    secret_dir = tmp_path / "working.secret"
    working_dir.mkdir()
    partial_config = {
        "channels": {},
        "mcp": {"clients": {}},
        "tools": {"builtin_tools": {}},
        "last_api": {"host": "0.0.0.0", "port": 8088},
        "agents": {
            "defaults": {"heartbeat": None},
            "running": {},
            "llm_routing": {},
            "language": "zh",
            "installed_md_files_language": None,
            "system_prompt_files": ["AGENTS.md", "SOUL.md", "PROFILE.md"],
        },
        "show_tool_details": True,
    }
    (working_dir / "config.json").write_text(
        json.dumps(partial_config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = _run_bootstrap(str(working_dir), str(secret_dir))

    assert result.returncode == 0, result.stderr or result.stdout
    config = json.loads(
        (working_dir / "config.json").read_text(encoding="utf-8"),
    )
    assert config["last_api"] == {"host": "0.0.0.0", "port": 8088}
    assert config["agents"]["installed_md_files_language"] == "zh"
    assert config["agents"]["defaults"]["heartbeat"]["every"] == "6h"
    assert (working_dir / "AGENTS.md").is_file()
    assert (working_dir / "active_skills").is_dir()


def test_bootstrap_cmd_does_not_restore_user_removed_files(tmp_path) -> None:
    working_dir = tmp_path / "working"
    secret_dir = tmp_path / "working.secret"

    first_run = _run_bootstrap(str(working_dir), str(secret_dir))
    assert first_run.returncode == 0, first_run.stderr or first_run.stdout

    bootstrap_md = working_dir / "BOOTSTRAP.md"
    assert bootstrap_md.is_file()
    bootstrap_md.unlink()

    skill_dir = next((working_dir / "active_skills").iterdir())
    removed_skill_name = skill_dir.name
    shutil.rmtree(skill_dir)

    second_run = _run_bootstrap(str(working_dir), str(secret_dir))

    assert second_run.returncode == 0, second_run.stderr or second_run.stdout
    assert not bootstrap_md.exists()
    assert not (working_dir / "active_skills" / removed_skill_name).exists()
