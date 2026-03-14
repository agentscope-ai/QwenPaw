# -*- coding: utf-8 -*-
"""CLI command: run CoPaw app on a free port in a native webview window."""
# pylint:disable=too-many-branches,too-many-statements,consider-using-with
from __future__ import annotations

import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser

import click

from ..constant import LOG_LEVEL_ENV
from ..utils.logging import setup_logger

try:
    import webview
except ImportError:
    webview = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


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


def _cleanup_stale_desktop_backends() -> list[int]:
    """Terminate stale packaged desktop backend processes.

    We only target packaged app backends (inside ``*.app`` bundle) to avoid
    affecting source/development processes like ``python -m copaw app --reload``.
    """
    if sys.platform == "win32":
        # Packaged desktop backend process pattern below is macOS/Linux-specific.
        return []

    stale_pids: list[int] = []
    try:
        ps_out = subprocess.check_output(
            ["ps", "-axo", "pid=,command="],
            text=True,
        )
    except Exception:
        return []

    current_pid = os.getpid()
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

        # Only clean stale desktop-packaged backend processes.
        if (
            ".app/Contents/Resources/env/bin/python" in cmd
            and "-m uvicorn" in cmd
            and "copaw.app._app:app" in cmd
        ):
            stale_pids.append(pid)

    cleaned: list[int] = []
    for pid in stale_pids:
        try:
            os.kill(pid, signal.SIGTERM)
            cleaned.append(pid)
        except ProcessLookupError:
            continue
        except Exception:
            continue

    if cleaned:
        # Give processes a short grace period for graceful shutdown.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if all(not _pid_exists(pid) for pid in cleaned):
                break
            time.sleep(0.1)

        # Force kill any survivors.
        for pid in cleaned:
            if _pid_exists(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass

    return cleaned


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
    # Setup logger for desktop command (separate from backend subprocess)
    setup_logger(log_level)

    cleaned = _cleanup_stale_desktop_backends()
    if cleaned:
        _log_desktop(
            f"[desktop] Cleaned stale desktop backend process(es): {cleaned}",
        )

    port = _find_free_port(host)
    url = f"http://{host}:{port}"
    click.echo(f"Starting CoPaw app on {url} (port {port})")
    logger.info("Server subprocess starting...")

    env = os.environ.copy()
    env[LOG_LEVEL_ENV] = log_level

    if "SSL_CERT_FILE" in env:
        cert_file = env["SSL_CERT_FILE"]
        if os.path.exists(cert_file):
            logger.info(f"SSL certificate: {cert_file}")
        else:
            logger.warning(
                f"SSL_CERT_FILE set but not found: {cert_file}",
            )
    else:
        logger.warning("SSL_CERT_FILE not set on environment")

    is_windows = sys.platform == "win32"
    proc = None
    manually_terminated = (
        False  # Track if we intentionally terminated the process
    )
    try:
        proc = subprocess.Popen(
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
        )
        try:
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
            logger.info("Waiting for HTTP ready...")
            if _wait_for_http(host, port):
                logger.info("HTTP ready, creating webview window...")
                api = WebViewAPI()
                webview.create_window(
                    "CoPaw Desktop",
                    url,
                    width=1280,
                    height=800,
                    text_select=True,
                    js_api=api,
                )
                logger.info(
                    "Calling webview.start() (blocks until closed)...",
                )
                webview.start(
                    private_mode=False,
                )  # blocks until user closes the window
                logger.info("webview.start() returned (window closed).")
            else:
                logger.error("Server did not become ready in time.")
                click.echo(
                    "Server did not become ready in time; open manually: "
                    + url,
                    err=True,
                )
                try:
                    proc.wait()
                except KeyboardInterrupt:
                    pass  # will be handled in finally
        finally:
            # Ensure backend process is always cleaned up
            # Wrap all cleanup operations to handle race conditions:
            # - Process may exit between poll() and terminate()
            # - terminate()/kill() may raise ProcessLookupError/OSError
            # - We must not let cleanup exceptions mask the original error
            if proc and proc.poll() is None:  # process still running
                logger.info("Terminating backend server...")
                manually_terminated = (
                    True  # Mark that we're intentionally terminating
                )
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5.0)
                        logger.info("Backend server terminated cleanly.")
                    except subprocess.TimeoutExpired:
                        logger.warning(
                            "Backend did not exit in 5s, force killing...",
                        )
                        try:
                            proc.kill()
                            proc.wait()
                            logger.info("Backend server force killed.")
                        except (ProcessLookupError, OSError) as e:
                            # Process already exited, which is fine
                            logger.debug(
                                f"kill() raised {e.__class__.__name__} "
                                f"(process already exited)",
                            )
                except (ProcessLookupError, OSError) as e:
                    # Process already exited between poll() and terminate()
                    logger.debug(
                        f"terminate() raised {e.__class__.__name__} "
                        f"(process already exited)",
                    )
            elif proc:
                logger.info(
                    f"Backend already exited with code {proc.returncode}",
                )

        # Only report errors if process exited unexpectedly
        # (not manually terminated)
        # On Windows, terminate() doesn't use signals so exit codes vary
        # (1, 259, etc.)
        # On Unix/Linux/macOS, terminate() sends SIGTERM (exit code -15)
        # Using a flag is more reliable than checking specific exit codes
        if proc and proc.returncode != 0 and not manually_terminated:
            logger.error(
                f"Backend process exited unexpectedly with code "
                f"{proc.returncode}",
            )
            # Follow POSIX convention for exit codes:
            # - Negative (signal): 128 + signal_number
            # - Positive (normal): use as-is
            # Example: -15 (SIGTERM) -> 143 (128+15), -11 (SIGSEGV) ->
            # 139 (128+11)
            if proc.returncode < 0:
                sys.exit(128 + abs(proc.returncode))
            else:
                sys.exit(proc.returncode or 1)
    except KeyboardInterrupt:
        logger.warning("KeyboardInterrupt in main, cleaning up...")
        raise
    except Exception as e:
        logger.error(f"Exception: {e!r}")
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        raise
