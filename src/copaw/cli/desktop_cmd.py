# -*- coding: utf-8 -*-
"""CLI command: run CoPaw app on a free port in a native webview window."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import click

from ..constant import LOG_LEVEL_ENV

try:
    import webview
except ImportError:
    webview = None  # type: ignore[assignment]


def _find_free_port(host: str = "127.0.0.1") -> int:
    """Bind to port 0 and return the OS-assigned free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.listen(1)
        return sock.getsockname()[1]


def _wait_for_http(host: str, port: int, timeout_sec: float = 15.0) -> bool:
    """Return True when something accepts TCP on host:port."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                s.connect((host, port))
                return True
        except (OSError, socket.error):
            time.sleep(0.2)
    return False


@click.command("desktop")
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Bind host for the app server.",
)
@click.option(
    "--log-level",
    default="info",
    type=click.Choice(
        ["critical", "error", "warning", "info", "debug", "trace"],
        case_sensitive=False,
    ),
    show_default=True,
    help="Log level for the app process.",
)
def desktop_cmd(
    host: str,
    log_level: str,
) -> None:
    """Run CoPaw app on an auto-selected free port in a webview window.

    Starts the FastAPI app in a subprocess on a free port, then opens a
    native webview window loading that URL. Use for a dedicated desktop
    window without conflicting with an existing CoPaw app instance.

    Requires: pip install copaw[desktop] (pywebview).
    """
    if webview is None:
        click.echo(
            "Webview support not installed. Run: pip install copaw[desktop]",
            err=True,
        )
        sys.exit(1)

    port = _find_free_port(host)
    url = f"http://{host}:{port}"
    click.echo(f"Starting CoPaw app on {url} (port {port})")

    env = os.environ.copy()
    env[LOG_LEVEL_ENV] = log_level
    with subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "copaw.app._app:app",
            "--host",
            host,
            "--port",
            str(port),
            "--log-level",
            log_level,
        ],
        stdin=subprocess.DEVNULL,
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=env,
    ) as proc:
        if _wait_for_http(host, port):
            webview.create_window("CoPaw Desktop", url)
            webview.start()  # blocks until user closes the window
            proc.terminate()
            proc.wait()
            return  # normal exit after user closed window
        click.echo(
            "Server did not become ready in time; open manually: " + url,
            err=True,
        )
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            proc.wait()

    if proc.returncode != 0:
        sys.exit(proc.returncode or 1)
