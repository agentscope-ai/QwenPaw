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
from typing import Any, Iterator

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

        skill_entries: dict = {}
        if resolved.is_dir():
            for p in sorted(resolved.iterdir()):
                if p.is_dir() and (p / "SKILL.md").exists():
                    skill_entries[p.name] = {
                        "enabled": True,
                        "channels": ["all"],
                        "source": "headless",
                    }
        (tmp_path / "skill.json").write_text(
            json.dumps(
                {
                    "schema_version": "workspace-skill-manifest.v1",
                    "version": 1,
                    "skills": skill_entries,
                },
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


def _response_text(response: Any) -> str:
    """Extract the final assistant text from a runtime response."""
    output = getattr(response, "output", None) or []
    if not output:
        return ""
    content = getattr(output[-1], "content", None) or []
    text_parts = []
    for item in content:
        item_type = getattr(item, "type", None)
        if getattr(item_type, "value", item_type) != "text":
            continue
        if text := getattr(item, "text", ""):
            text_parts.append(text)
    return "\n".join(text_parts).strip()


def _response_usage(response: Any) -> dict:
    """Return the runtime's token usage as a plain dictionary."""
    usage = getattr(response, "usage", None)
    if isinstance(usage, dict):
        return dict(usage)
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return {}


async def _run_task(  # pylint: disable=too-many-statements
    instruction: str,
    agent_config,
    request_context: dict[str, Any],
    max_iters: int,
    timeout: int,
    output_dir: str | None,
    skills_dir: str | None = None,
) -> dict:
    from ..agents.acp.meta import ACP_EPHEMERAL_META_KEY
    from ..app.app_services import AppServiceManager
    from ..app.workspace.bootstrap_factory import WorkspaceBootstrapFactory
    from ..app.workspace.workspace import Workspace
    from ..constant import WORKING_DIR
    from ..runtime import Runtime
    from ..schemas import AgentRequest, AgentResponse, RunStatus

    runtime_config = agent_config.model_copy(deep=True)
    runtime_config.running.max_iters = max_iters
    runtime_config.running.loop.iteration.max_iterations = max_iters

    base_workspace: Path | None = None
    if agent_config.workspace_dir:
        base_workspace = Path(agent_config.workspace_dir).expanduser()

    app_services = None
    workspace_instance = None
    app_services_started = False
    workspace_started = False
    t0 = time.monotonic()

    with _isolated_skills_workspace(
        skills_dir,
        base_workspace,
    ) as workspace_dir:
        resolved_workspace_dir = workspace_dir or base_workspace or WORKING_DIR
        runtime_request_context = dict(request_context)
        runtime_request_context[ACP_EPHEMERAL_META_KEY] = True

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
            agent_id=request_context.get("agent_id", "default"),
            request_context=runtime_request_context,
        )
        try:
            app_services = AppServiceManager()
            await app_services.start()
            app_services_started = True

            workspace_instance = Workspace(
                agent_id=request_context.get("agent_id", "default"),
                workspace_dir=str(resolved_workspace_dir),
            )
            workspace_instance.bootstrap_plugins(
                **WorkspaceBootstrapFactory.build_bootstrap_kwargs(
                    app_services,
                ),
            )
            workspace_instance.set_app_services(app_services)
            await workspace_instance.start(headless=True)
            workspace_started = True

            runtime = Runtime(
                workspace=workspace_instance,
                app_services=app_services,
                agent_config_override=runtime_config,
            )

            async def _consume_response() -> AgentResponse:
                final_response = None
                async for event in runtime.run(req):
                    if isinstance(event, AgentResponse) and event.status in {
                        RunStatus.Completed,
                        RunStatus.Failed,
                    }:
                        final_response = event
                if final_response is None:
                    raise RuntimeError(
                        "Task runtime produced no final response",
                    )
                return final_response

            response = await asyncio.wait_for(
                _consume_response(),
                timeout=timeout,
            )
            elapsed = time.monotonic() - t0
            result: dict = {
                "status": "success",
                "elapsed_seconds": round(elapsed, 2),
                "response": _response_text(response),
                "usage": _response_usage(response),
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
            if workspace_started and workspace_instance is not None:
                try:
                    await workspace_instance.stop(final=True)
                except Exception:
                    logger.warning(
                        "Failed to stop headless task workspace",
                        exc_info=True,
                    )
            if app_services_started and app_services is not None:
                try:
                    await app_services.stop()
                except Exception:
                    logger.warning(
                        "Failed to stop headless task services",
                        exc_info=True,
                    )

    result.setdefault("usage", {})

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

    request_context: dict[str, Any] = {
        "session_id": "headless-task",
        "user_id": "headless",
        "channel": "console",
        "agent_id": agent_id,
    }
    if no_guard:
        request_context["approval_level"] = "off"

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
