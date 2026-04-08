# -*- coding: utf-8 -*-
"""Tests for the ``copaw task`` headless CLI command."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from copaw.cli.main import cli
from copaw.cli.task_cmd import _read_instruction


# ── _read_instruction ────────────────────────────────────────────────


def test_read_instruction_returns_raw_text() -> None:
    assert _read_instruction("do something") == "do something"


def test_read_instruction_reads_file_content(tmp_path) -> None:
    md = tmp_path / "task.md"
    md.write_text("# Instruction\nDo the thing.", encoding="utf-8")
    assert _read_instruction(str(md)) == "# Instruction\nDo the thing."


def test_read_instruction_nonexistent_path_returns_raw() -> None:
    result = _read_instruction("/nonexistent/path/to/file.md")
    assert result == "/nonexistent/path/to/file.md"


# ── CLI surface ──────────────────────────────────────────────────────


def test_task_command_registered_in_cli() -> None:
    result = CliRunner().invoke(cli, ["task", "--help"])
    assert result.exit_code == 0
    for flag in (
        "--instruction",
        "--model",
        "--no-guard",
        "--skills-dir",
        "--output-dir",
        "--max-iters",
        "--timeout",
        "--agent-id",
    ):
        assert flag in result.output


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


# ── --model flag ─────────────────────────────────────────────────────


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


# ── --output-dir ─────────────────────────────────────────────────────


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


# ── Exit codes & stdout ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "status",
    ["error", "timeout"],
)
def test_exit_code_one_on_failure(monkeypatch, status) -> None:
    from copaw.config.config import AgentProfileConfig

    monkeypatch.setattr(
        "copaw.config.config.load_agent_config",
        lambda _aid: AgentProfileConfig(id="default", name="Default"),
    )
    monkeypatch.setattr(
        "copaw.cli.task_cmd._run_task",
        AsyncMock(
            return_value={
                "status": status,
                "response": "",
                "usage": {},
            },
        ),
    )

    result = CliRunner().invoke(cli, ["task", "-i", "hello"])
    assert result.exit_code == 1


def test_stdout_json_and_default_context(monkeypatch) -> None:
    """Happy-path: valid JSON on stdout, exit 0, no headless overrides."""
    from copaw.config.config import AgentProfileConfig

    monkeypatch.setattr(
        "copaw.config.config.load_agent_config",
        lambda _aid: AgentProfileConfig(id="default", name="Default"),
    )

    captured_ctx: dict = {}

    async def _fake_run_task(**kwargs):
        captured_ctx.update(kwargs["request_context"])
        return {
            "status": "success",
            "elapsed_seconds": 1.5,
            "response": "hello",
            "usage": {},
        }

    monkeypatch.setattr("copaw.cli.task_cmd._run_task", _fake_run_task)

    result = CliRunner().invoke(cli, ["task", "-i", "hello"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert "usage" in data
    assert "elapsed_seconds" in data
    assert "_headless_tool_guard" not in captured_ctx
    assert "_headless_skills_dir" not in captured_ctx


# ── ToolGuardMixin behavior ─────────────────────────────────────────


class _FakeActingBase:
    """Provides ``_acting`` that ToolGuardMixin.super() resolves to."""

    def __init__(self):
        self.acting_called = False

    async def _acting(self, _tool_call):
        self.acting_called = True
        return {"output": "executed"}


def _build_guarded_agent(request_context: dict):
    from copaw.agents.tool_guard_mixin import ToolGuardMixin

    class _GuardInstance(ToolGuardMixin, _FakeActingBase):
        pass

    inst = _GuardInstance()
    inst._request_context = dict(  # pylint: disable=protected-access
        request_context,
    )
    return inst


async def test_tool_guard_bypassed_via_request_context():
    """_acting delegates directly to super when _headless_tool_guard=false."""
    agent = _build_guarded_agent({"_headless_tool_guard": "false"})

    tool_call = {"id": "tc_1", "name": "execute_shell_command", "input": {}}
    result = await agent._acting(tool_call)  # pylint: disable=protected-access

    assert agent.acting_called is True
    assert result == {"output": "executed"}


async def test_tool_guard_not_bypassed_without_flag():
    """Without _headless_tool_guard, the mixin runs its guard logic."""
    agent = _build_guarded_agent({"session_id": "s1"})

    tool_call = {"id": "tc_2", "name": "execute_shell_command", "input": {}}
    with patch(
        "copaw.security.tool_guard.engine.get_guard_engine",
    ) as mock_engine_fn:
        mock_engine = MagicMock()
        mock_engine.enabled = True
        mock_engine.is_denied.return_value = False
        mock_engine.is_guarded.return_value = False
        mock_engine.guard.return_value = None
        mock_engine_fn.return_value = mock_engine

        with patch("copaw.app.approvals.get_approval_service"):
            result = await agent._acting(  # pylint: disable=protected-access
                tool_call,
            )

    assert agent.acting_called is True
    assert result == {"output": "executed"}


# ── Full CLI → request_context → component e2e ──────────────────────


def test_e2e_cli_no_guard_and_skills_dir(monkeypatch, tmp_path):
    """Full chain: CLI flags → request_context → components.

    Verifies both ``--no-guard`` and ``--skills-dir`` propagate via
    ``request_context``, resolve correctly at the component level,
    and do **not** pollute environment variables.
    """
    from copaw.config.config import AgentProfileConfig
    from copaw.agents.skills_manager import resolve_effective_skills

    skills_dir = tmp_path / "my_skills"
    skill_sub = skills_dir / "e2e-skill"
    skill_sub.mkdir(parents=True)
    (skill_sub / "SKILL.md").write_text(
        "---\nname: e2e-skill\ndescription: test\n---\n",
    )

    fake_config = AgentProfileConfig(
        id="e2e",
        name="E2E",
        workspace_dir=str(tmp_path / "workspace"),
    )
    (tmp_path / "workspace").mkdir()
    monkeypatch.setattr(
        "copaw.config.config.load_agent_config",
        lambda _aid: fake_config,
    )

    captured: dict = {}

    async def _spy_run_task(**kwargs):
        ctx = kwargs["request_context"]
        captured["request_context"] = dict(ctx)
        captured["env_tool_guard"] = os.environ.get(
            "COPAW_TOOL_GUARD_ENABLED",
        )
        captured["env_skills_dir"] = os.environ.get("COPAW_SKILLS_DIR")
        resolved = resolve_effective_skills(
            tmp_path,
            ctx.get("channel", "console"),
            skills_dir_override=ctx.get("_headless_skills_dir"),
        )
        captured["resolved_skills"] = [Path(p).name for p in resolved]
        captured["guard_bypassed"] = (
            ctx.get("_headless_tool_guard", "true").lower() == "false"
        )
        return {
            "status": "success",
            "response": "ok",
            "elapsed_seconds": 0.01,
            "usage": {},
        }

    monkeypatch.setattr("copaw.cli.task_cmd._run_task", _spy_run_task)

    result = CliRunner().invoke(
        cli,
        [
            "task",
            "-i",
            "do the thing",
            "--no-guard",
            "--skills-dir",
            str(skills_dir),
            "--agent-id",
            "e2e",
        ],
    )

    assert result.exit_code == 0, result.output

    ctx = captured["request_context"]
    assert ctx["_headless_tool_guard"] == "false"
    assert ctx["_headless_skills_dir"] == str(skills_dir.resolve())
    assert ctx["session_id"] == "headless-task"
    assert ctx["agent_id"] == "e2e"
    assert captured["env_tool_guard"] is None
    assert captured["env_skills_dir"] is None
    assert captured["resolved_skills"] == ["e2e-skill"]
    assert captured["guard_bypassed"] is True
    data = json.loads(result.output)
    assert data["status"] == "success"
