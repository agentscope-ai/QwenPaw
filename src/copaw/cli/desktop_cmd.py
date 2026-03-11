# -*- coding: utf-8 -*-
"""CLI command: run CoPaw app on a free port in a native webview window."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

import click

from ..constant import LOG_LEVEL_ENV

try:
    import webview
except ImportError:
    webview = None  # type: ignore[assignment]


class WebViewAPI:
    """API exposed to the webview for handling external links."""

    def open_external_link(self, url: str) -> None:
        """Open URL in system's default browser."""
        if not url.startswith(("http://", "https://")):
            return
        webbrowser.open(url)


def _find_free_port(host: str = "127.0.0.1") -> int:
    """Bind to port 0 and return the OS-assigned free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.listen(1)
        return sock.getsockname()[1]


def _wait_for_http(host: str, port: int, timeout_sec: float = 300.0) -> bool:
    """Return True when something accepts TCP on host:port."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect((host, port))
                return True
        except (OSError, socket.error):
            time.sleep(1)
    return False


def _log_desktop(msg: str) -> None:
    """Print to stderr and flush (for desktop.log when launched from .app)."""
    print(msg, file=sys.stderr)
    sys.stderr.flush()


def _stream_reader(in_stream, out_stream) -> None:
    """Read from in_stream line by line and write to out_stream.

    Used on Windows to prevent subprocess buffer blocking. Runs in a
    background thread to continuously drain the subprocess output.
    """
    try:
        for line in iter(in_stream.readline, ""):
            if not line:
                break
            out_stream.write(line)
            out_stream.flush()
    except Exception:
        pass
    finally:
        try:
            in_stream.close()
        except Exception:
            pass


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
    """

    port = _find_free_port(host)
    url = f"http://{host}:{port}"
    click.echo(f"Starting CoPaw app on {url} (port {port})")
    _log_desktop("[desktop] Server subprocess starting...")

    env = os.environ.copy()
    env[LOG_LEVEL_ENV] = log_level

    if "SSL_CERT_FILE" in env:
        cert_file = env["SSL_CERT_FILE"]
        if os.path.exists(cert_file):
            _log_desktop(f"[desktop] SSL certificate: {cert_file}")
        else:
            _log_desktop(
                f"[desktop] WARNING: SSL_CERT_FILE set but not found: "
                f"{cert_file}",
            )
    else:
        _log_desktop("[desktop] WARNING: SSL_CERT_FILE not set")

    is_windows = sys.platform == "win32"
    try:
        with subprocess.Popen(
            [
                sys.executable,
                "-m",
                "copaw",
                "app",
                "--host",
                host,
                "--port",
                str(port),
                "--log-level",
                log_level,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if is_windows else sys.stdout,
            stderr=subprocess.PIPE if is_windows else sys.stderr,
            env=env,
            bufsize=1,
            universal_newlines=True,
        ) as proc:
            if is_windows:
                stdout_thread = threading.Thread(
                    target=_stream_reader,
                    args=(proc.stdout, sys.stdout),
                    daemon=True,
                )
                stderr_thread = threading.Thread(
                    target=_stream_reader,
                    args=(proc.stderr, sys.stderr),
                    daemon=True,
                )
                stdout_thread.start()
                stderr_thread.start()
            _log_desktop("[desktop] Waiting for HTTP ready...")
            if _wait_for_http(host, port):
                _log_desktop(
                    "[desktop] HTTP ready, creating webview window...",
                )
                api = WebViewAPI()
                webview.create_window(
                    "CoPaw Desktop",
                    url,
                    width=1280,
                    height=800,
                    text_select=True,
                    js_api=api,
                )
                _log_desktop(
                    "[desktop] Calling webview.start() "
                    "(blocks until closed)...",
                )
                webview.start(
                    private_mode=False,
                )  # blocks until user closes the window
                _log_desktop(
                    "[desktop] webview.start() returned (window closed).",
                )
                proc.terminate()
                proc.wait()
                return  # normal exit after user closed window
            _log_desktop("[desktop] Server did not become ready in time.")
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
    except Exception as e:
        _log_desktop(f"[desktop] Exception: {e!r}")
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        raise
