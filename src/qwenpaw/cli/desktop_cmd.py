# -*- coding: utf-8 -*-
"""CLI command: run QwenPaw app on a free port in a native webview window."""
# pylint:disable=too-many-branches,too-many-statements,consider-using-with
from __future__ import annotations

import logging
import os
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

WEBVIEW2_RUNTIME_DOWNLOAD_URL = (
    "https://developer.microsoft.com/en-us/microsoft-edge/webview2/"
)
WEBVIEW2_RUNTIME_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WINDOWS_WEBVIEW2_REGISTRY_LOCATIONS = (
    (
        "HKEY_LOCAL_MACHINE",
        (
            "SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\"
            f"{WEBVIEW2_RUNTIME_GUID}"
        ),
    ),
    (
        "HKEY_LOCAL_MACHINE",
        f"SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{WEBVIEW2_RUNTIME_GUID}",
    ),
    (
        "HKEY_CURRENT_USER",
        f"Software\\Microsoft\\EdgeUpdate\\Clients\\{WEBVIEW2_RUNTIME_GUID}",
    ),
)


class WebViewAPI:
    """API exposed to the webview for handling external links."""

    def open_external_link(self, url: str) -> None:
        """Open URL in system's default browser."""
        if not url.startswith(("http://", "https://")):
            return
        webbrowser.open(url)


def _parse_version_string(version: str | None) -> tuple[int, ...] | None:
    """Parse dotted numeric version strings like 123.0.2420.65."""
    if not version:
        return None
    parts = version.strip().split(".")
    if not parts or any(not part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _read_windows_registry_value(
    root_name: str,
    sub_key: str,
    value_name: str,
) -> str | None:
    """Read a string value from the Windows registry."""
    if sys.platform != "win32":
        return None

    try:
        import winreg
    except ImportError:
        return None

    try:
        root = getattr(winreg, root_name)
        with winreg.OpenKey(root, sub_key) as key:
            value, reg_type = winreg.QueryValueEx(key, value_name)
    except (AttributeError, OSError):
        return None

    if reg_type != winreg.REG_SZ or not isinstance(value, str):
        return None

    value = value.strip()
    return value or None


def _detect_windows_webview2_runtime_version() -> str | None:
    """Return the installed WebView2 Runtime version on Windows."""
    if sys.platform != "win32":
        return None

    for root_name, sub_key in WINDOWS_WEBVIEW2_REGISTRY_LOCATIONS:
        version = _read_windows_registry_value(root_name, sub_key, "pv")
        parsed = _parse_version_string(version)
        if parsed and any(parsed):
            return version

    return None


def _show_windows_message_box(title: str, message: str) -> None:
    """Display a native Windows error dialog when launched silently."""
    if sys.platform != "win32":
        return

    try:
        import ctypes

        mb_iconerror = 0x00000010
        mb_setforeground = 0x00010000
        ctypes.windll.user32.MessageBoxW(
            None,
            message,
            title,
            mb_iconerror | mb_setforeground,
        )
    except Exception:
        pass


def _abort_desktop_launch(message: str) -> None:
    """Exit the desktop launcher with a visible, actionable error."""
    logger.error(message)
    click.echo(f"Error: {message}", err=True)
    _show_windows_message_box("QwenPaw Desktop", message)
    raise SystemExit(1)


def _ensure_desktop_webview_available() -> None:
    """Fail fast if the desktop webview backend is unavailable."""
    if webview is None:
        _abort_desktop_launch(
            "pywebview is not available in this QwenPaw Desktop environment. "
            "Please reinstall QwenPaw Desktop.",
        )

    if sys.platform != "win32":
        return

    runtime_version = _detect_windows_webview2_runtime_version()
    if runtime_version:
        logger.info(f"Detected WebView2 Runtime {runtime_version}")
        return

    _abort_desktop_launch(
        "Microsoft Edge WebView2 Runtime was not detected. "
        "QwenPaw Desktop requires WebView2 on Windows and may otherwise "
        "fall back to an unsupported legacy renderer that shows a blank "
        "window. Install or repair WebView2 Runtime and try again.\n\n"
        f"Download: {WEBVIEW2_RUNTIME_DOWNLOAD_URL}\n\n"
        "If the issue persists, run 'QwenPaw Desktop (Debug)' and attach "
        "the terminal output.",
    )


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


def _start_desktop_window(url: str) -> None:
    """Create and start the embedded desktop window."""
    if webview is None:
        raise RuntimeError("pywebview is not available")

    api = WebViewAPI()
    webview.create_window(
        "QwenPaw Desktop",
        url,
        width=1280,
        height=800,
        text_select=True,
        js_api=api,
    )

    start_kwargs = {"private_mode": False}
    if sys.platform == "win32":
        # Force WebView2 so we fail fast instead of silently falling back
        # to MSHTML / IE, which cannot render the Vite-built frontend.
        start_kwargs["gui"] = "edgechromium"

    webview.start(**start_kwargs)


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
    """Run QwenPaw app on an auto-selected free port in a webview window.

    Starts the FastAPI app in a subprocess on a free port, then opens a
    native webview window loading that URL. Use for a dedicated desktop
    window without conflicting with an existing QwenPaw app instance.
    """
    # Setup logger for desktop command (separate from backend subprocess)
    setup_logger(log_level)
    _ensure_desktop_webview_available()

    port = _find_free_port(host)
    url = f"http://{host}:{port}"
    click.echo(f"Starting QwenPaw app on {url} (port {port})")
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
                "qwenpaw",
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
                try:
                    logger.info(
                        "Calling webview.start() (blocks until closed)...",
                    )
                    _start_desktop_window(url)
                    logger.info("webview.start() returned (window closed).")
                except Exception:
                    logger.exception("Failed to start embedded desktop window")
                    if sys.platform == "win32":
                        _abort_desktop_launch(
                            "Failed to start the embedded desktop window.\n\n"
                            "On Windows this usually means the WebView2 "
                            "Runtime is missing or damaged. Install or repair "
                            "WebView2 Runtime and try again.\n\n"
                            f"Download: {WEBVIEW2_RUNTIME_DOWNLOAD_URL}\n\n"
                            "If the issue persists, run "
                            "'QwenPaw Desktop (Debug)' and attach the terminal "
                            "output.",
                        )
                    else:
                        _abort_desktop_launch(
                            "Failed to start the embedded desktop window. "
                            "Run with '--log-level debug' and inspect the "
                            "terminal output for details.",
                        )
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
