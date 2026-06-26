# -*- coding: utf-8 -*-
"""CLI command: run QwenPaw app on a free port in a native webview window."""

# pylint:disable=too-many-branches,too-many-statements,consider-using-with,too-many-locals
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
from collections.abc import Callable, Mapping
from typing import Any

import click

from ..constant import LOG_LEVEL_ENV, WORKING_DIR
from ..utils.logging import setup_logger
from ..utils.port import get_stable_port

try:
    import webview
except ImportError:
    webview = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Shared state populated by desktop_preloader.py so the preloader splash
# can be reused instead of creating a second window.
preloader_splash: dict = {}


class WebViewAPI:
    """API exposed to the webview for external links and file downloads."""

    def open_external_link(self, url: str) -> None:
        """Open URL in system's default browser."""
        if not url.startswith(("http://", "https://")):
            return
        webbrowser.open(url)

    def save_file(
        self,
        url: str,
        filename: str,
        headers: Mapping[str, str] | None = None,
    ) -> bool:
        """Download a file from *url* and save it via a native save dialog.

        Shows the OS "Save As" dialog so the user can pick a destination,
        then downloads the file and writes it there.  This is the desktop
        equivalent of the browser's ``<a download>`` click pattern which
        pywebview/WebView2 does not support.

        Args:
            url: Full HTTP(S) URL of the file to download.
            filename: Default filename shown in the save dialog.
            headers: Optional request headers supplied by the web console.

        Returns:
            True if the file was saved successfully, False if the user
            cancelled the dialog or an error occurred.
        """
        import re
        import shutil
        import urllib.request

        if not url.startswith(("http://", "https://")):
            return False

        # Sanitize filename: remove characters illegal on Windows
        # (< > : " / \ | ? *) and trim leading/trailing whitespace/dots.
        # Colons are common in backup names like "Backup 2026-04-22 17:36".
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", filename).strip(" .")

        try:
            # Show native OS save dialog via pywebview
            result = webview.windows[0].create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=safe_name,
            )
            if not result:
                return False  # user cancelled

            dest_path = result if isinstance(result, str) else result[0]

            request = urllib.request.Request(
                url,
                headers={
                    str(key): str(value)
                    for key, value in (headers or {}).items()
                    if value is not None
                },
            )

            # Download from the local backend and write to chosen path
            with urllib.request.urlopen(request) as response:
                with open(dest_path, "wb") as f:
                    shutil.copyfileobj(response, f)

            return True
        except Exception:
            logger.exception("save_file failed")
            return False


def _show_splash():
    """Create splash window — delegates to shared _splash module."""
    from ._splash import show_splash

    return show_splash()


def _wait_for_http(
    host: str,
    port: int,
    timeout_sec: float = 300.0,
    progress_cb: Callable[..., Any] | None = None,
) -> bool:
    """Return True when something accepts TCP on host:port.

    If *progress_cb* is provided it is invoked every second so a splash
    screen can stay alive during the wait.
    """
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect((host, port))
                return True
        except (OSError, socket.error):
            if progress_cb:
                progress_cb()
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

    # Splash window: reuse preloader splash if available, otherwise create one.
    # This keeps visual feedback during backend startup.
    splash_callbacks = preloader_splash.get("callbacks")
    splash_start = preloader_splash.get("start_time")
    if splash_callbacks:
        splash_update, _, splash_destroy = (
            splash_callbacks[1],
            splash_callbacks[2],
            splash_callbacks[3],
        )
        if splash_start is None:
            splash_start = time.monotonic()
    else:
        _splash = _show_splash()
        splash_update, _, splash_destroy = (
            _splash[1],
            _splash[2],
            _splash[3],
        )
        splash_start = time.monotonic()

    # get_stable_port() returns (port, socket) — the socket is kept open
    # to hold the port until the subprocess is about to bind it, minimizing
    # the TOCTOU window.  We close it just before Popen so the child can
    # bind the same port.
    port_file = str(WORKING_DIR / "desktop_port")
    port, held_socket = get_stable_port(port_file, host)
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
        # Release the held socket just before spawning the subprocess so
        # the child can bind the same port.  This keeps the TOCTOU window
        # as small as possible (only between close() and the child's bind).
        if held_socket:
            held_socket.close()

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
            if _wait_for_http(host, port, progress_cb=splash_update):
                logger.info("HTTP ready, creating webview window...")
                # Pass elapsed time to Phase 2 overlay via URL hash.
                elapsed = int(time.monotonic() - splash_start)
                console_url = f"{url}/#_ls={elapsed}"
                api = WebViewAPI()
                webview.create_window(
                    "QwenPaw Desktop",
                    console_url,
                    width=1280,
                    height=800,
                    text_select=True,
                    js_api=api,
                )
                logger.info(
                    "Calling webview.start() (blocks until closed)...",
                )
                # Persist localStorage/cookies across restarts so the
                # user's agent selection, chat history, and preferences
                # survive window close.  Without storage_path, WebView2
                # may use a temp directory that is discarded on restart.
                webview_storage = str(WORKING_DIR / "webview_data")
                # Destroy splash just before webview takes over to avoid
                # a blank gap between the splash and the webview render.
                splash_destroy()
                webview.start(
                    private_mode=False,
                    storage_path=webview_storage,
                )  # blocks until user closes the window
                logger.info("webview.start() returned (window closed).")
            else:
                logger.error("Server did not become ready in time.")
                splash_destroy()
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
                "Backend process exited unexpectedly with code "
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
        try:
            splash_destroy()
        except Exception:
            pass
        raise
