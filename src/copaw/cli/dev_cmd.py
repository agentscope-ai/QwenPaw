# -*- coding: utf-8 -*-
"""``copaw dev`` – start backend + frontend dev servers simultaneously.

This command is intended for **source development only**. It:
  1. Starts the Python backend via uvicorn with ``--reload`` (hot-reload on
     Python file changes).
  2. Starts the Vite frontend dev server (``npm run dev``) with HMR.

Both processes share the same terminal session; their output is prefixed with
``[backend]`` and ``[frontend]`` to distinguish them. Press Ctrl+C to stop
both at once.

Requirements:
  - Run from the repository root (the directory containing ``console/``).
  - ``npm`` must be available on PATH.
  - Run ``pip install -e .`` before using this command.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import IO

import click

from ..constant import LOG_LEVEL_ENV
from ..config.utils import write_last_api
from ..utils.logging import setup_logger


def _stream(pipe: IO[bytes], prefix: str, color: str) -> None:
    """Read *pipe* line-by-line and write each line to stdout with *prefix*."""
    reset = "\033[0m"
    bold = "\033[1m"
    try:
        for raw in iter(pipe.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            click.echo(f"{bold}{color}{prefix}{reset} {line}")
    except Exception:  # noqa: BLE001  – pipe closed, process exited
        pass


def _validate_frontend(console_dir: Path) -> str:
    """Validate frontend prerequisites and return the resolved npm path."""
    if not (console_dir / "package.json").exists():
        click.secho(
            f"ERROR: {console_dir} is not a valid frontend project "
            "(package.json not found).\n"
            "Run this command from the repository root, or use "
            "`copaw app --reload` to start the backend only.",
            fg="red",
            err=True,
        )
        sys.exit(1)

    npm = shutil.which("npm")
    if npm is None:
        click.secho(
            "ERROR: npm not found on PATH. Install Node.js to use the "
            "frontend dev server, or run `copaw app --reload` for "
            "backend-only mode.",
            fg="red",
            err=True,
        )
        sys.exit(1)

    if not (console_dir / "node_modules").exists():
        click.secho(
            "[frontend] node_modules not found – running npm install …",
            fg="yellow",
        )
        result = subprocess.run([npm, "install"], cwd=console_dir, check=False)
        if result.returncode != 0:
            click.secho("ERROR: npm install failed.", fg="red", err=True)
            sys.exit(1)

    return npm


def _start_backend(
    host: str,
    port: int,
    log_level: str,
    cors_origins: str,
) -> "subprocess.Popen[bytes]":
    """Spawn the uvicorn backend process and return it."""
    backend_env = dict(os.environ)
    if cors_origins and not backend_env.get("COPAW_CORS_ORIGINS"):
        backend_env["COPAW_CORS_ORIGINS"] = cors_origins
    backend_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "copaw.app._app:app",
        "--host",
        host,
        "--port",
        str(port),
        "--reload",
        "--log-level",
        log_level,
    ]
    return subprocess.Popen(  # pylint: disable=consider-using-with
        backend_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=backend_env,
    )


def _start_frontend(
    npm: str,
    console_dir: Path,
    host: str,
    port: int,
    frontend_port: int,
) -> "subprocess.Popen[bytes]":
    """Spawn the Vite dev server process and return it."""
    # Use a routable host for the frontend proxy even if the backend binds
    # to a wildcard address like 0.0.0.0 or ::.
    backend_url_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    frontend_env = {
        **os.environ,
        "BACKEND_URL": f"http://{backend_url_host}:{port}",
    }
    frontend_cmd = [
        npm,
        "run",
        "dev",
        "--",
        "--port",
        str(frontend_port),
    ]
    return subprocess.Popen(  # pylint: disable=consider-using-with
        frontend_cmd,
        cwd=console_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=frontend_env,
    )


@click.command("dev")
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Backend bind host",
)
@click.option(
    "--port",
    default=8088,
    type=int,
    show_default=True,
    help="Backend bind port",
)
@click.option(
    "--frontend-port",
    default=5173,
    type=int,
    show_default=True,
    help="Vite dev server port",
)
@click.option(
    "--log-level",
    default="info",
    type=click.Choice(
        ["critical", "error", "warning", "info", "debug", "trace"],
        case_sensitive=False,
    ),
    show_default=True,
    help="Backend log level",
)
@click.option(
    "--no-frontend",
    is_flag=True,
    default=False,
    help="Start backend only (skip Vite dev server)",
)
def dev_cmd(
    host: str,
    port: int,
    frontend_port: int,
    log_level: str,
    no_frontend: bool,
) -> None:
    """Start backend + frontend dev servers with hot-reload.

    Run from the repository root (the directory containing console/).

    \b
    Backend:  http://localhost:8088  (uvicorn --reload)
    Frontend: http://localhost:5173  (vite dev, proxies /api → backend)
    """
    write_last_api(host, port)
    os.environ[LOG_LEVEL_ENV] = log_level
    setup_logger(log_level)

    console_dir = Path.cwd() / "console"
    use_frontend = not no_frontend

    npm = _validate_frontend(console_dir) if use_frontend else None

    cors_origins = (
        f"http://localhost:{frontend_port},http://127.0.0.1:{frontend_port}"
        if use_frontend
        else ""
    )

    backend_proc = _start_backend(host, port, log_level, cors_origins)
    procs: list[subprocess.Popen] = [backend_proc]

    frontend_proc: subprocess.Popen | None = None
    if use_frontend and npm is not None:
        frontend_proc = _start_frontend(
            npm,
            console_dir,
            host,
            port,
            frontend_port,
        )
        procs.append(frontend_proc)

    # Stream output on background threads (daemon – exit when main exits).
    assert backend_proc.stdout is not None
    threading.Thread(
        target=_stream,
        args=(backend_proc.stdout, "[backend]", "\033[36m"),
        daemon=True,
    ).start()
    if frontend_proc is not None:
        assert frontend_proc.stdout is not None
        threading.Thread(
            target=_stream,
            args=(frontend_proc.stdout, "[frontend]", "\033[32m"),
            daemon=True,
        ).start()

    click.echo("")
    click.secho("  CoPaw dev mode", bold=True)
    click.secho(
        f"  Backend  → http://{host}:{port}  (uvicorn --reload)",
        fg="cyan",
    )
    if use_frontend:
        click.secho(
            f"  Frontend → http://localhost:{frontend_port}  (vite --hmr)",
            fg="green",
        )
        click.secho(
            f"  Open http://localhost:{frontend_port} in your browser",
            fg="yellow",
        )
    else:
        click.secho(
            f"  Open http://{host}:{port} in your browser"
            " (serving built assets)",
            fg="yellow",
        )
    label = "both servers" if use_frontend else "the server"
    click.echo(f"  Press Ctrl+C to stop {label}.\n")

    # Event shared between the signal handler and the watchdog threads so that
    # only the first exit (deliberate or unexpected) triggers a shutdown.
    done = threading.Event()

    def _terminate_all() -> None:
        for p in procs:
            try:
                p.terminate()
            except Exception:  # noqa: BLE001
                pass

    def _shutdown(  # pylint: disable=unused-argument
        signum: int,
        frame: object,
    ) -> None:
        if done.is_set():
            return
        done.set()
        click.echo("\n\nShutting down…")
        _terminate_all()

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):  # SIGTERM is not available on Windows
        signal.signal(signal.SIGTERM, _shutdown)

    def _watch(proc: "subprocess.Popen[bytes]") -> None:
        """Wait for *proc* to exit; if it exits before *done* is set, it
        exited unexpectedly – terminate all sibling processes."""
        proc.wait()
        if not done.is_set():
            done.set()
            click.echo(
                "\n\nA dev server exited unexpectedly"
                " – shutting down remaining servers…",
            )
            _terminate_all()

    watchdog_threads = [
        threading.Thread(target=_watch, args=(p,), daemon=True) for p in procs
    ]
    for t in watchdog_threads:
        t.start()
    for t in watchdog_threads:
        t.join()

    click.secho("All dev servers stopped.", fg="yellow")
