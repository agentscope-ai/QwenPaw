# -*- coding: utf-8 -*-
"""CLI command: run CoPaw app on a free port in a native webview window."""
from __future__ import annotations

import os
import signal
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


def _pid_exists(pid: int) -> bool:
    """Return True if *pid* exists and is accessible."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_packaged_desktop_backend(cmd: str) -> bool:
    """Return True when a process command matches packaged desktop backend."""
    return (
        ".app/Contents/Resources/env/bin/python" in cmd
        and "-m uvicorn" in cmd
        and "copaw.app._app:app" in cmd
    )


def _list_stale_desktop_backend_pids() -> list[int]:
    """Collect stale packaged desktop backend process IDs."""
    try:
        ps_out = subprocess.check_output(
            ["ps", "-axo", "pid=,command="],
            text=True,
        )
    except Exception:
        return []

    current_pid = os.getpid()
    stale_pids: list[int] = []
    for raw in ps_out.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        pid_str, cmd = parts
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        if pid == current_pid:
            continue
        if _is_packaged_desktop_backend(cmd):
            stale_pids.append(pid)

    return stale_pids


def _terminate_processes(pids: list[int]) -> list[int]:
    """Send SIGTERM to processes and return the ones signaled successfully."""
    cleaned: list[int] = []
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            cleaned.append(pid)
        except ProcessLookupError:
            continue
        except Exception:
            continue
    return cleaned


def _kill_surviving_processes(pids: list[int]) -> None:
    """Force kill any process that remains alive after the grace period."""
    for pid in pids:
        if _pid_exists(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass


def _cleanup_stale_desktop_backends() -> list[int]:
    """Terminate stale packaged desktop backend processes.

    We only target packaged app backends (inside ``*.app`` bundle)
    to avoid affecting source/development processes like
    ``python -m copaw app --reload``.
    """
    if sys.platform == "win32":
        # Packaged desktop backend process pattern below is
        # macOS/Linux-specific.
        return []

    stale_pids = _list_stale_desktop_backend_pids()
    cleaned = _terminate_processes(stale_pids)

    if cleaned:
        # Give processes a short grace period for graceful shutdown.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if all(not _pid_exists(pid) for pid in cleaned):
                break
            time.sleep(0.1)

        _kill_surviving_processes(cleaned)

    return cleaned


def _log_ssl_certificate_status(env: dict[str, str]) -> None:
    """Log SSL certificate configuration for desktop launches."""
    if "SSL_CERT_FILE" in env:
        cert_file = env["SSL_CERT_FILE"]
        if os.path.exists(cert_file):
            _log_desktop(f"[desktop] SSL certificate: {cert_file}")
        else:
            _log_desktop(
                f"[desktop] WARNING: SSL_CERT_FILE set but not found: "
                f"{cert_file}",
            )
        return

    _log_desktop("[desktop] WARNING: SSL_CERT_FILE not set")


def _start_windows_stream_threads(proc: subprocess.Popen) -> None:
    """Start background threads draining subprocess output on Windows."""
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


def _serve_desktop_window(
    proc: subprocess.Popen,
    host: str,
    port: int,
    url: str,
) -> None:
    """Wait for backend readiness and run the blocking desktop webview."""
    webview_module = webview
    if webview_module is None:
        raise click.ClickException(
            "pywebview is required to run CoPaw desktop mode",
        )

    _log_desktop("[desktop] Waiting for HTTP ready...")
    if _wait_for_http(host, port):
        _log_desktop(
            "[desktop] HTTP ready, creating webview window...",
        )
        api = WebViewAPI()
        webview_module.create_window(
            "CoPaw Desktop",
            url,
            width=1280,
            height=800,
            text_select=True,
            js_api=api,
        )
        _log_desktop(
            "[desktop] Calling webview.start() (blocks until closed)...",
        )
        webview_module.start(
            private_mode=False,
        )
        _log_desktop(
            "[desktop] webview.start() returned (window closed).",
        )
        proc.terminate()
        proc.wait()
        return

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

    cleaned = _cleanup_stale_desktop_backends()
    if cleaned:
        _log_desktop(
            f"[desktop] Cleaned stale desktop backend process(es): {cleaned}",
        )

    port = _find_free_port(host)
    url = f"http://{host}:{port}"
    click.echo(f"Starting CoPaw app on {url} (port {port})")
    _log_desktop("[desktop] Server subprocess starting...")

    env = os.environ.copy()
    env[LOG_LEVEL_ENV] = log_level
    _log_ssl_certificate_status(env)

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
                _start_windows_stream_threads(proc)
            _serve_desktop_window(proc, host, port, url)

        if proc.returncode != 0:
            sys.exit(proc.returncode or 1)
    except Exception as e:
        _log_desktop(f"[desktop] Exception: {e!r}")
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        raise
