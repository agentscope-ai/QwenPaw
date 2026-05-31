# -*- coding: utf-8 -*-
"""Tests for the ``qwenpaw task`` headless CLI command."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from click.testing import CliRunner

from qwenpaw.cli.main import cli
from qwenpaw.cli.task_cmd import _read_instruction


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
        "qwenpaw.config.config.load_agent_config",
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
    from qwenpaw.config.config import AgentProfileConfig

    fake_config = AgentProfileConfig(id="default", name="Default")
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _aid: fake_config,
    )
    monkeypatch.setattr(
        "qwenpaw.cli.task_cmd._run_task",
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
    from qwenpaw.config.config import AgentProfileConfig

    fake_config = AgentProfileConfig(id="default", name="Default")
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _aid: fake_config,
    )
    monkeypatch.setattr(
        "qwenpaw.cli.task_cmd._run_task",
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
    from qwenpaw.config.config import AgentProfileConfig

    out_dir = tmp_path / "results"

    fake_config = AgentProfileConfig(id="default", name="Default")
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
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

    monkeypatch.setattr("qwenpaw.cli.task_cmd._run_task", _fake_run_task)

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
    from qwenpaw.config.config import AgentProfileConfig

    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _aid: AgentProfileConfig(id="default", name="Default"),
    )
    monkeypatch.setattr(
        "qwenpaw.cli.task_cmd._run_task",
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
    from qwenpaw.config.config import AgentProfileConfig

    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
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

    monkeypatch.setattr("qwenpaw.cli.task_cmd._run_task", _fake_run_task)

    result = CliRunner().invoke(cli, ["task", "-i", "hello"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert "usage" in data
    assert "elapsed_seconds" in data
    assert "_headless_tool_guard" not in captured_ctx
    assert "_headless_skills_dir" not in captured_ctx


# ── Full CLI → request_context → component e2e ──────────────────────


def test_e2e_cli_no_guard_and_skills_dir(monkeypatch, tmp_path):
    """Full chain: CLI flags → _run_task kwargs.

    Verifies ``--no-guard`` propagates via ``request_context``,
    ``--skills-dir`` is forwarded as a dedicated ``skills_dir`` kwarg
    (no longer embedded in ``request_context``), and neither flag
    pollutes environment variables.
    """
    from qwenpaw.config.config import AgentProfileConfig

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
        "qwenpaw.config.config.load_agent_config",
        lambda _aid: fake_config,
    )

    captured: dict = {}

    async def _spy_run_task(**kwargs):
        ctx = kwargs["request_context"]
        captured["request_context"] = dict(ctx)
        captured["skills_dir"] = kwargs.get("skills_dir")
        captured["env_tool_guard"] = os.environ.get(
            "QWENPAW_TOOL_GUARD_ENABLED",
        )
        captured["env_skills_dir"] = os.environ.get("QWENPAW_SKILLS_DIR")
        captured["guard_bypassed"] = (
            ctx.get("_headless_tool_guard", "true").lower() == "false"
        )
        return {
            "status": "success",
            "response": "ok",
            "elapsed_seconds": 0.01,
            "usage": {},
        }

    monkeypatch.setattr("qwenpaw.cli.task_cmd._run_task", _spy_run_task)

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
    assert "_headless_skills_dir" not in ctx
    assert ctx["session_id"] == "headless-task"
    assert ctx["agent_id"] == "e2e"
    assert captured["skills_dir"] == str(skills_dir)
    assert captured["env_tool_guard"] is None
    assert captured["env_skills_dir"] is None
    assert captured["guard_bypassed"] is True
    data = json.loads(result.output)
    assert data["status"] == "success"


# ── _isolated_skills_workspace ───────────────────────────────────────


def test_isolated_workspace_creates_overlay(tmp_path):
    """Overlay workspace symlinks skills and pre-populates manifest."""
    from qwenpaw.cli.task_cmd import _isolated_skills_workspace
    from qwenpaw.agents.skill_system import resolve_effective_skills

    skills_dir = tmp_path / "ext_skills"
    (skills_dir / "alpha").mkdir(parents=True)
    (skills_dir / "alpha" / "SKILL.md").write_text("# alpha\n")
    (skills_dir / "beta").mkdir(parents=True)
    (skills_dir / "beta" / "SKILL.md").write_text("# beta\n")
    (skills_dir / "not-a-skill").mkdir(parents=True)

    base_ws = tmp_path / "real_workspace"
    base_ws.mkdir()
    (base_ws / "AGENTS.md").write_text("agent prompt")

    with _isolated_skills_workspace(
        str(skills_dir),
        base_ws,
    ) as overlay:
        assert overlay is not None
        assert overlay != base_ws

        assert (overlay / "skills").is_symlink()
        assert (overlay / "skills").resolve() == skills_dir.resolve()

        manifest_path = overlay / "skill.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert "alpha" in manifest["skills"]
        assert "beta" in manifest["skills"]
        assert "not-a-skill" not in manifest["skills"]
        assert manifest["skills"]["alpha"]["enabled"] is True

        assert (overlay / "AGENTS.md").is_symlink()
        assert (overlay / "AGENTS.md").read_text() == "agent prompt"

        resolved = resolve_effective_skills(overlay, "console")
        assert sorted(resolved) == ["alpha", "beta"]

    assert not overlay.exists()


def test_isolated_workspace_none_without_skills_dir(tmp_path):
    """Without skills_dir the context manager yields base_workspace as-is."""
    from qwenpaw.cli.task_cmd import _isolated_skills_workspace

    base_ws = tmp_path / "ws"
    base_ws.mkdir()

    with _isolated_skills_workspace(None, base_ws) as result:
        assert result == base_ws


def test_isolated_workspace_does_not_pollute_real_workspace(tmp_path):
    """Real workspace must have zero new files after overlay teardown."""
    from qwenpaw.cli.task_cmd import _isolated_skills_workspace

    skills_dir = tmp_path / "skills_src"
    (skills_dir / "s1").mkdir(parents=True)
    (skills_dir / "s1" / "SKILL.md").write_text("# s1\n")

    real_ws = tmp_path / "workspace"
    real_ws.mkdir()
    original_contents = set(real_ws.iterdir())

    with _isolated_skills_workspace(str(skills_dir), real_ws):
        pass

    assert set(real_ws.iterdir()) == original_contents
