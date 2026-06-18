# -*- coding: utf-8 -*-
"""Terminal coding mode — interactive REPL for project-based chat.

Ponytail: no abstraction unless forced. File manipulation over config API.
Stdlib over deps. Subprocess for daemon lifecycle.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import click

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config helpers — direct file manipulation, no config API
# ---------------------------------------------------------------------------


def _agent_config_path(agent_id: str) -> Path:
    """Return agent.json path for *agent_id*."""
    base = Path(
        os.environ.get(
            "QWENPAW_WORKSPACE_DIR",
            Path.home() / ".qwenpaw" / "workspaces",
        ),
    )
    return base / agent_id / "agent.json"


def _ensure_coding_mode(agent_id: str) -> bool:
    """Enable ``running.coding_mode.enabled`` in agent.json if not already.

    Returns True if config was modified.
    """
    config_path = _agent_config_path(agent_id)
    if not config_path.is_file():
        return False

    raw = config_path.read_text(encoding="utf-8")
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError:
        return False

    # Ponytail: no deep-get helper, just inline access
    running = cfg.get("running")
    if running is None:
        cfg["running"] = {}
        running = cfg["running"]
    cm = running.get("coding_mode")
    if cm is None:
        running["coding_mode"] = {}
        cm = running["coding_mode"]
    if cm.get("enabled") is True:
        return False  # already on

    cm["enabled"] = True
    config_path.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return True


# ---------------------------------------------------------------------------
# Daemon lifecycle
# ---------------------------------------------------------------------------


def _port_open(host: str, port: int, tries: int = 1) -> bool:
    """Return True when *host:port* accepts TCP connections."""
    for _ in range(tries):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect((host, port))
            s.close()
            return True
        except (OSError, ConnectionRefusedError):
            if tries > 1:
                time.sleep(1)
    return False


def _ensure_daemon(host: str, port: int) -> bool:
    """Start daemon in background if not running. Returns readiness."""
    if _port_open(host, port):
        return True

    click.echo("Daemon not running. Starting qwenpaw app …", err=True)

    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        [
            sys.executable,
            "-m",
            "qwenpaw.cli.main",
            "app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # Windows: detach so Ctrl+C in terminal doesn't kill daemon
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        if sys.platform == "win32"
        else 0,
    )

    # Wait up to 30 s
    if not _port_open(host, port, tries=15):
        click.echo(
            "Failed to start daemon. Try manually:\n"
            f"  qwenpaw app --host {host} --port {port}",
            err=True,
        )
        return False

    click.echo(f"Daemon ready on {host}:{port} (PID {proc.pid}).", err=True)
    return True


# ---------------------------------------------------------------------------
# SSE streaming
# ---------------------------------------------------------------------------


def _stream(
    base_url: str,
    payload: dict[str, Any],
    agent_id: str,
    timeout: int,
) -> str:
    """POST to /agent/process, stream SSE delta chunks, return full text."""
    import httpx

    accumulated = ""
    headers = {
        "Content-Type": "application/json",
        "X-Agent-Id": agent_id,
    }

    try:
        with httpx.Client(base_url=base_url, timeout=timeout) as client:
            with client.stream(
                "POST",
                "/agent/process",
                json=payload,
                headers=headers,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    # Strip SSE framing
                    if line.startswith("data: "):
                        data = line[6:]
                    elif line.startswith("data:"):
                        data = line[5:]
                    else:
                        continue

                    data = data.strip()
                    if not data or data == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    # Assumes OpenAI-compatible delta format
                    delta = (
                        chunk.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content", "")
                    )
                    if delta:
                        click.echo(delta, nl=False)
                        sys.stdout.flush()
                        accumulated += delta

    except httpx.TimeoutException:
        click.echo(
            "\n⚠️  Response timed out. Increase --timeout or try again.",
            err=True,
        )
    except httpx.ConnectError:
        click.echo(
            f"\nError: daemon unreachable at {base_url}.",
            err=True,
        )
    except httpx.HTTPStatusError as exc:
        click.echo(
            f"\nHTTP {exc.response.status_code}: {exc.response.text}",
            err=True,
        )
    except Exception as exc:
        click.echo(f"\nUnexpected error: {exc}", err=True)

    click.echo()
    return accumulated


# ---------------------------------------------------------------------------
# Send & receive
# ---------------------------------------------------------------------------


def _chat(
    base_url: str,
    agent_id: str,
    session_id: str,
    text: str,
    project_dir: str,
    timeout: int,
) -> str:
    """Send user message, stream assistant response, return full text."""
    payload: dict[str, Any] = {
        "session_id": session_id,
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": text}],
            },
        ],
        "request_context": {
            "source": "terminal",
            "project_dir": project_dir,
        },
    }
    click.echo()
    return _stream(base_url, payload, agent_id, timeout)


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@click.command("terminal")
@click.option(
    "--project-dir",
    "-p",
    default=None,
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project directory (default: current working directory)",
)
@click.option(
    "--agent",
    "-a",
    default=None,
    help="Agent ID (default: 'default')",
)
@click.option(
    "--timeout",
    "-t",
    default=600,
    type=int,
    help="Response timeout in seconds (default: 600)",
)
@click.option(
    "--no-daemon-autostart",
    is_flag=True,
    help="Do not auto-start daemon; fail if not running",
)
@click.pass_context
def terminal_cmd(
    ctx: click.Context,
    project_dir: str | None,
    agent: str | None,
    timeout: int,
    no_daemon_autostart: bool,
) -> None:
    """Start an interactive coding-mode terminal.

    Connects to a running QwenPaw daemon and opens an interactive chat
    REPL with coding mode enabled for the specified project directory.
    """
    host = ctx.obj["host"]
    port = ctx.obj["port"]
    base_url = f"http://{host}:{port}/api"
    resolved_agent = agent or "default"

    # Resolve project dir
    project_dir = str(
        Path(project_dir).resolve() if project_dir else Path.cwd().resolve(),
    )

    # 1 — ensure coding mode is enabled in agent config
    if _ensure_coding_mode(resolved_agent):
        click.echo(
            f"Enabled coding_mode for agent '{resolved_agent}'.",
            err=True,
        )

    # 2 — ensure daemon is running (unless opted out)
    if no_daemon_autostart:
        if not _port_open(host, port):
            click.echo(
                f"Daemon not reachable at {host}:{port}.\n"
                "  qwenpaw app --host {host} --port {port}",
                err=True,
            )
            sys.exit(1)
    elif not _ensure_daemon(host, port):
        sys.exit(1)

    session_id = f"terminal:{resolved_agent}:{uuid.uuid4().hex[:12]}"

    click.echo(
        "\n╔══════════════════════════════════════════════════╗\n"
        "║  QwenPaw Terminal — Coding Mode                ║\n"
        f"║  Project : {project_dir}\n"
        f"║  Agent   : {resolved_agent}\n"
        f"║  Server  : {host}:{port}\n"
        "╠══════════════════════════════════════════════════╣\n"
        "║  Commands:                                     ║\n"
        "║    /clear    — Clear session context            ║\n"
        "║    /exit     — Exit terminal                    ║\n"
        "║    Ctrl+C    — Stop generation                  ║\n"
        "╚══════════════════════════════════════════════════╝",
    )

    while True:
        try:
            text = click.prompt(
                "\nYou",
                prompt_suffix=" > ",
                err=False,
            ).strip()
        except (EOFError, KeyboardInterrupt):
            click.echo("\nGoodbye!")
            break

        if not text:
            continue
        if text == "/exit":
            click.echo("Goodbye!")
            break
        if text == "/clear":
            session_id = f"terminal:{resolved_agent}:{uuid.uuid4().hex[:12]}"
            click.echo("Session cleared.")
            continue

        _chat(base_url, resolved_agent, session_id, text, project_dir, timeout)
