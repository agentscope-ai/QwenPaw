# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

import click

logger = logging.getLogger(__name__)


def _read_instruction(raw: str) -> str:
    """Return instruction text; read from file if *raw* is a valid path."""
    p = Path(raw)
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return raw


async def _run_task(
    instruction: str,
    agent_config,
    agent_id: str,
    max_iters: int,
    timeout: int,
    output_dir: str | None,
) -> dict:
    from agentscope.message import Msg
    from ..agents.react_agent import CoPawAgent

    agent_config.running.max_iters = max_iters

    workspace_dir: Path | None = None
    if agent_config.workspace_dir:
        workspace_dir = Path(agent_config.workspace_dir).expanduser()

    agent = CoPawAgent(
        agent_config=agent_config,
        enable_memory_manager=False,
        request_context={
            "session_id": "headless-task",
            "user_id": "headless",
            "channel": "console",
            "agent_id": agent_id,
        },
        workspace_dir=workspace_dir,
    )

    t0 = time.monotonic()
    try:
        response = await asyncio.wait_for(
            agent.reply([Msg(name="user", role="user", content=instruction)]),
            timeout=timeout,
        )
        elapsed = time.monotonic() - t0
        result: dict = {
            "status": "success",
            "elapsed_seconds": round(elapsed, 2),
            "response": response.get_text_content() if response else "",
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
    from ..providers.models import ModelSlotConfig
    from ..utils.logging import setup_logger

    setup_logger("info")

    instruction_text = _read_instruction(instruction)
    if not instruction_text.strip():
        click.echo("Error: instruction is empty.", err=True)
        sys.exit(1)

    if no_guard:
        os.environ["COPAW_TOOL_GUARD_ENABLED"] = "false"

    if skills_dir:
        os.environ["COPAW_SKILLS_DIR"] = str(Path(skills_dir).resolve())

    try:
        agent_config = load_agent_config(agent_id)
    except ValueError as exc:
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

    result = asyncio.run(
        _run_task(
            instruction=instruction_text,
            agent_config=agent_config,
            agent_id=agent_id,
            max_iters=max_iters,
            timeout=timeout,
            output_dir=output_dir,
        ),
    )

    click.echo(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] == "success" else 1)
