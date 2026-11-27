# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import click

logger = logging.getLogger(__name__)


_SKILL_FS_NAMES = {"skills", "skill", "skill.json", ".skill.json.lock"}


@contextmanager
def _isolated_skills_workspace(
    skills_dir: str | None,
    base_workspace: Path | None,
) -> Iterator[Path | None]:
    """Create a temporary overlay workspace when *skills_dir* is given.

    The overlay symlinks the external skills directory as ``skills/`` and
    pre-populates a manifest with every discovered skill enabled.  Non-skill
    files from *base_workspace* are symlinked so that prompt/bootstrap files
    remain accessible.  All manifest writes land in the temporary directory,
    keeping the real workspace untouched.
    """
    if not skills_dir:
        yield base_workspace
        return

    with tempfile.TemporaryDirectory(prefix="qwenpaw_headless_") as tmp:
        tmp_path = Path(tmp)
        resolved = Path(skills_dir).resolve()
        (tmp_path / "skills").symlink_to(resolved)

        from ..agents.skill_system.store import (
            get_workspace_skill_manifest_path,
            manifest_for_external_skills,
        )

        get_workspace_skill_manifest_path(tmp_path).write_text(
            json.dumps(
                manifest_for_external_skills(resolved),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        if base_workspace and base_workspace.is_dir():
            for item in base_workspace.iterdir():
                if item.name in _SKILL_FS_NAMES or item.name.startswith(
                    ".skill_",
                ):
                    continue
                target = tmp_path / item.name
                if not target.exists():
                    target.symlink_to(item)

        yield tmp_path


def _read_instruction(raw: str) -> str:
    """Return instruction text; read from file if *raw* is a valid path."""
    p = Path(raw)
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return raw


async def _run_task(
    instruction: str,
    agent_config,
    request_context: dict[str, str],
    max_iters: int,
    timeout: int,
    output_dir: str | None,
    skills_dir: str | None = None,
) -> dict:
    from agentscope.message import UserMsg

    from ..runtime.builder import AgentBuilder
    from ..runtime.hooks import HookContext
    from ..schemas import AgentRequest

    agent_config = agent_config.model_copy(deep=True)
    agent_config.running.max_iters = max_iters

    base_workspace: Path | None = None
    if agent_config.workspace_dir:
        base_workspace = Path(agent_config.workspace_dir).expanduser()

    with _isolated_skills_workspace(skills_dir, base_workspace) as workspace:
        req = AgentRequest(
            input=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": instruction}],
                },
            ],
            session_id=request_context.get("session_id", "headless-task"),
            user_id=request_context.get("user_id", "headless"),
            channel=request_context.get("channel", "console"),
            request_context=dict(request_context),
        )
        session_id = req.session_id or ""
        # TODO: Give headless tasks a runtime-owned workspace scope for tools
        # and services. Reuse workspace setup and teardown when that scope is
        # available; the CLI should only supply request options and output.
        ctx = HookContext(
            request=req,
            session_id=session_id,
            agent_id=request_context.get("agent_id", "default"),
            root_session_id=session_id,
            root_agent_id=request_context.get("agent_id", "default"),
            workspace_dir=workspace,
            workspace=None,
            app_services=None,
            agent_config=agent_config,
            session_state=None,
        )
        builder = AgentBuilder()
        agent = await builder.build(ctx)

        t0 = time.monotonic()
        try:
            response = await asyncio.wait_for(
                agent.reply(
                    [UserMsg(name="user", content=instruction)],
                ),
                timeout=timeout,
            )
            elapsed = time.monotonic() - t0
            result: dict = {
                "status": "success",
                "elapsed_seconds": round(elapsed, 2),
                "response": (response.get_text_content() if response else ""),
            }
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - t0
            result = {
                "status": "timeout",
                "elapsed_seconds": round(elapsed, 2),
                "timeout_seconds": timeout,
                "response": "",
            }
        except Exception as exc:
            elapsed = time.monotonic() - t0
            result = {
                "status": "error",
                "elapsed_seconds": round(elapsed, 2),
                "error": str(exc),
                "response": "",
            }
        finally:
            await agent.close()

    usage: dict = {}
    try:
        model = getattr(agent, "model", None)
        if model is not None:
            monitor = getattr(model, "monitor", None)
            if monitor is not None:
                metrics = (
                    monitor.get_metrics()
                    if callable(getattr(monitor, "get_metrics", None))
                    else {}
                )
                usage["input_tokens"] = metrics.get("prompt_tokens", 0)
                usage["output_tokens"] = metrics.get("completion_tokens", 0)
                usage["cost_usd"] = metrics.get("cost_usd")
    except Exception:
        logger.debug("Failed to extract token usage", exc_info=True)
    result["usage"] = usage

    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return result


@click.command("task")
@click.option(
    "-i",
    "--instruction",
    required=True,
    help="Task instruction text or path to a .md file.",
)
@click.option(
    "-m",
    "--model",
    default=None,
    help="Model override (e.g. 'anthropic/claude-sonnet-4-5').",
)
@click.option(
    "--max-iters",
    default=30,
    type=int,
    show_default=True,
    help="Max ReAct loop iterations.",
)
@click.option(
    "-t",
    "--timeout",
    default=900,
    type=int,
    show_default=True,
    help="Max execution time in seconds.",
)
@click.option(
    "--no-guard",
    is_flag=True,
    default=False,
    help="Disable tool guard security checks.",
)
@click.option(
    "--skills-dir",
    default=None,
    type=click.Path(exists=True, file_okay=False),
    help="Direct skills directory path (bypasses manifest).",
)
@click.option(
    "--output-dir",
    default=None,
    type=click.Path(file_okay=False),
    help="Directory for execution logs and result.json.",
)
@click.option(
    "--agent-id",
    default="default",
    show_default=True,
    help="Agent ID to use.",
)
def task_cmd(
    instruction: str,
    model: str | None,
    max_iters: int,
    timeout: int,
    no_guard: bool,
    skills_dir: str | None,
    output_dir: str | None,
    agent_id: str,
) -> None:
    """Run a single task instruction headlessly (no web server)."""
    from ..config.config import load_agent_config
    from ..config.config import ModelSlotConfig
    from ..exceptions import ConfigurationException
    from ..utils.logging import setup_logger

    setup_logger("info")

    instruction_text = _read_instruction(instruction)
    if not instruction_text.strip():
        click.echo("Error: instruction is empty.", err=True)
        sys.exit(1)

    try:
        agent_config = load_agent_config(agent_id)
    except (ConfigurationException, ValueError) as exc:
        click.echo(f"Error loading agent config: {exc}", err=True)
        sys.exit(1)

    if model:
        parts = model.split("/", 1)
        if len(parts) == 2:
            agent_config.active_model = ModelSlotConfig(
                provider_id=parts[0],
                model=parts[1],
            )
        else:
            agent_config.active_model = ModelSlotConfig(
                provider_id="",
                model=model,
            )

    request_context: dict[str, str] = {
        "session_id": "headless-task",
        "user_id": "headless",
        "channel": "console",
        "agent_id": agent_id,
    }
    if no_guard:
        request_context["_headless_tool_guard"] = "false"

    result = asyncio.run(
        _run_task(
            instruction=instruction_text,
            agent_config=agent_config,
            request_context=request_context,
            max_iters=max_iters,
            timeout=timeout,
            output_dir=output_dir,
            skills_dir=skills_dir,
        ),
    )

    click.echo(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] == "success" else 1)
