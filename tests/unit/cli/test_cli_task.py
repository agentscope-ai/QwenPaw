# -*- coding: utf-8 -*-
"""Tests for the ``copaw task`` headless CLI command."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from click.testing import CliRunner

from copaw.cli.main import cli
from copaw.cli.task_cmd import _read_instruction


def test_read_instruction_returns_raw_text() -> None:
    assert _read_instruction("do something") == "do something"


def test_read_instruction_reads_file_content(tmp_path) -> None:
    md = tmp_path / "task.md"
    md.write_text("# Instruction\nDo the thing.", encoding="utf-8")
    assert _read_instruction(str(md)) == "# Instruction\nDo the thing."


def test_read_instruction_nonexistent_path_returns_raw() -> None:
    result = _read_instruction("/nonexistent/path/to/file.md")
    assert result == "/nonexistent/path/to/file.md"


def test_task_command_registered_in_cli() -> None:
    result = CliRunner().invoke(cli, ["task", "--help"])
    assert result.exit_code == 0
    assert "--instruction" in result.output
    assert "--model" in result.output
    assert "--no-guard" in result.output
    assert "--skills-dir" in result.output
    assert "--output-dir" in result.output
    assert "--max-iters" in result.output
    assert "--timeout" in result.output
    assert "--agent-id" in result.output


def test_task_rejects_empty_instruction(monkeypatch) -> None:
    monkeypatch.setattr(
        "copaw.config.config.load_agent_config",
        MagicMock(),
    )
    result = CliRunner().invoke(cli, ["task", "-i", "   "])
    assert result.exit_code != 0
    assert (
        "empty" in result.output.lower()
        or "empty" in (result.stderr_bytes or b"").decode().lower()
    )


def test_no_guard_flag_sets_env_var(monkeypatch) -> None:
    captured_env: dict = {}

    def _fake_load(_agent_id):
        captured_env["COPAW_TOOL_GUARD_ENABLED"] = os.environ.get(
            "COPAW_TOOL_GUARD_ENABLED",
        )
        raise ValueError("stop early")

    monkeypatch.setattr("copaw.config.config.load_agent_config", _fake_load)

    CliRunner().invoke(cli, ["task", "-i", "hello", "--no-guard"])

    assert captured_env.get("COPAW_TOOL_GUARD_ENABLED") == "false"


def test_skills_dir_flag_sets_env_var(monkeypatch, tmp_path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    captured_env: dict = {}

    def _fake_load(_agent_id):
        captured_env["COPAW_SKILLS_DIR"] = os.environ.get("COPAW_SKILLS_DIR")
        raise ValueError("stop early")

    monkeypatch.setattr("copaw.config.config.load_agent_config", _fake_load)

    CliRunner().invoke(
        cli,
        ["task", "-i", "hello", "--skills-dir", str(skills_dir)],
    )

    assert captured_env.get("COPAW_SKILLS_DIR") == str(skills_dir.resolve())


def test_model_flag_overrides_agent_config(monkeypatch) -> None:
    from copaw.config.config import AgentProfileConfig

    fake_config = AgentProfileConfig(id="default", name="Default")
    monkeypatch.setattr(
        "copaw.config.config.load_agent_config",
        lambda _aid: fake_config,
    )
    monkeypatch.setattr(
        "copaw.cli.task_cmd._run_task",
        AsyncMock(
            return_value={"status": "success", "response": "", "usage": {}},
        ),
    )

    CliRunner().invoke(
        cli,
        ["task", "-i", "hello", "-m", "dashscope/qwen3.6-plus"],
    )

    assert fake_config.active_model is not None
    assert fake_config.active_model.provider_id == "dashscope"
    assert fake_config.active_model.model == "qwen3.6-plus"


def test_model_flag_without_slash(monkeypatch) -> None:
    from copaw.config.config import AgentProfileConfig

    fake_config = AgentProfileConfig(id="default", name="Default")
    monkeypatch.setattr(
        "copaw.config.config.load_agent_config",
        lambda _aid: fake_config,
    )
    monkeypatch.setattr(
        "copaw.cli.task_cmd._run_task",
        AsyncMock(
            return_value={"status": "success", "response": "", "usage": {}},
        ),
    )

    CliRunner().invoke(cli, ["task", "-i", "hello", "-m", "gpt-4o"])

    assert fake_config.active_model is not None
    assert fake_config.active_model.provider_id == ""
    assert fake_config.active_model.model == "gpt-4o"


def test_output_dir_writes_result_json(monkeypatch, tmp_path) -> None:
    from copaw.config.config import AgentProfileConfig

    out_dir = tmp_path / "results"

    fake_config = AgentProfileConfig(id="default", name="Default")
    monkeypatch.setattr(
        "copaw.config.config.load_agent_config",
        lambda _aid: fake_config,
    )

    async def _fake_run_task(**kwargs):
        result = {
            "status": "success",
            "elapsed_seconds": 1.0,
            "response": "42",
            "usage": {},
        }
        od = kwargs.get("output_dir")
        if od:
            p = Path(od)
            p.mkdir(parents=True, exist_ok=True)
            (p / "result.json").write_text(
                json.dumps(result, indent=2),
                encoding="utf-8",
            )
        return result

    monkeypatch.setattr("copaw.cli.task_cmd._run_task", _fake_run_task)

    result = CliRunner().invoke(
        cli,
        ["task", "-i", "hello", "--output-dir", str(out_dir)],
    )

    assert result.exit_code == 0
    result_file = out_dir / "result.json"
    assert result_file.exists()
    data = json.loads(result_file.read_text())
    assert data["status"] == "success"
    assert data["response"] == "42"


def test_exit_code_zero_on_success(monkeypatch) -> None:
    from copaw.config.config import AgentProfileConfig

    monkeypatch.setattr(
        "copaw.config.config.load_agent_config",
        lambda _aid: AgentProfileConfig(id="default", name="Default"),
    )
    monkeypatch.setattr(
        "copaw.cli.task_cmd._run_task",
        AsyncMock(
            return_value={"status": "success", "response": "ok", "usage": {}},
        ),
    )

    result = CliRunner().invoke(cli, ["task", "-i", "hello"])
    assert result.exit_code == 0


def test_exit_code_one_on_error(monkeypatch) -> None:
    from copaw.config.config import AgentProfileConfig

    monkeypatch.setattr(
        "copaw.config.config.load_agent_config",
        lambda _aid: AgentProfileConfig(id="default", name="Default"),
    )
    monkeypatch.setattr(
        "copaw.cli.task_cmd._run_task",
        AsyncMock(
            return_value={
                "status": "error",
                "error": "boom",
                "response": "",
                "usage": {},
            },
        ),
    )

    result = CliRunner().invoke(cli, ["task", "-i", "hello"])
    assert result.exit_code == 1


def test_exit_code_one_on_timeout(monkeypatch) -> None:
    from copaw.config.config import AgentProfileConfig

    monkeypatch.setattr(
        "copaw.config.config.load_agent_config",
        lambda _aid: AgentProfileConfig(id="default", name="Default"),
    )
    monkeypatch.setattr(
        "copaw.cli.task_cmd._run_task",
        AsyncMock(
            return_value={
                "status": "timeout",
                "response": "",
                "usage": {},
            },
        ),
    )

    result = CliRunner().invoke(cli, ["task", "-i", "hello"])
    assert result.exit_code == 1


def test_stdout_contains_valid_json(monkeypatch) -> None:
    from copaw.config.config import AgentProfileConfig

    monkeypatch.setattr(
        "copaw.config.config.load_agent_config",
        lambda _aid: AgentProfileConfig(id="default", name="Default"),
    )
    monkeypatch.setattr(
        "copaw.cli.task_cmd._run_task",
        AsyncMock(
            return_value={
                "status": "success",
                "elapsed_seconds": 1.5,
                "response": "hello",
                "usage": {},
            },
        ),
    )

    result = CliRunner().invoke(cli, ["task", "-i", "hello"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert "usage" in data
    assert "elapsed_seconds" in data


def test_resolve_effective_skills_env_override(tmp_path, monkeypatch) -> None:
    from copaw.agents.skills_manager import resolve_effective_skills

    skills_dir = tmp_path / "my_skills"
    skill_a = skills_dir / "skill-a"
    skill_b = skills_dir / "skill-b"
    no_skill = skills_dir / "not-a-skill"
    skill_a.mkdir(parents=True)
    skill_b.mkdir(parents=True)
    no_skill.mkdir(parents=True)
    (skill_a / "SKILL.md").write_text("---\nname: a\n---\n")
    (skill_b / "SKILL.md").write_text("---\nname: b\n---\n")

    monkeypatch.setenv("COPAW_SKILLS_DIR", str(skills_dir))

    result = resolve_effective_skills(tmp_path, "console")

    assert sorted(result) == ["skill-a", "skill-b"]


def test_resolve_effective_skills_env_not_set_uses_manifest(
    tmp_path,
    monkeypatch,
) -> None:
    from copaw.agents.skills_manager import resolve_effective_skills

    monkeypatch.delenv("COPAW_SKILLS_DIR", raising=False)

    result = resolve_effective_skills(tmp_path, "console")
    assert isinstance(result, list)


def test_tool_guard_env_var_recognized() -> None:
    import copaw.agents.tool_guard_mixin as tgm
    import inspect

    source = inspect.getsource(
        tgm.ToolGuardMixin._acting,  # pylint: disable=protected-access
    )
    assert "COPAW_TOOL_GUARD_ENABLED" in source
