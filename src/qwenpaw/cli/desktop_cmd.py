# -*- coding: utf-8 -*-
"""CLI command: run QwenPaw app on a free port in a native webview window."""

# pylint:disable=too-many-branches,too-many-statements,consider-using-with
from __future__ import annotations

import ipaddress
import logging
import os
import pathlib
import socket
import subprocess
import sys
import threading
import traceback
import webbrowser
from collections.abc import Mapping

import click

from ..constant import LOG_LEVEL_ENV
from ..utils.logging import setup_logger

try:
    import webview
except ImportError:
    webview = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Maximum number of characters kept in the captured stderr ring buffer.
_MAX_STDERR_CHARS = 4000


class BackendProcessManager:
    """Manages the backend subprocess lifecycle and stderr capture.

    Thread-safe: all mutable state is guarded by a lock so the main
    thread, stream-reader threads, and pywebview JS callbacks can
    safely interact.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._host: str = "127.0.0.1"
        self._port: int = 0
        self._log_level: str = "info"
        self._stderr_buf: str = ""
        self._manually_terminated: bool = False

    # -- public properties ---------------------------------------------------

    @property
    def process(self) -> subprocess.Popen | None:
        with self._lock:
            return self._proc

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    @property
    def exit_code(self) -> int | None:
        with self._lock:
            return self._proc.returncode if self._proc else None

    @property
    def manually_terminated(self) -> bool:
        with self._lock:
            return self._manually_terminated

    @property
    def console_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def version_url(self) -> str:
        return f"http://{self._host}:{self._port}/api/version"

    # -- stderr capture ------------------------------------------------------

    def append_stderr(self, text: str) -> None:
        with self._lock:
            self._stderr_buf += text
            if len(self._stderr_buf) > _MAX_STDERR_CHARS:
                half = _MAX_STDERR_CHARS // 2
                head = self._stderr_buf[:half]
                tail = self._stderr_buf[-half:]
                self._stderr_buf = f"{head}\n[...stderr truncated...]\n{tail}"

    def get_stderr(self) -> str:
        with self._lock:
            return self._stderr_buf.strip()

    # -- lifecycle -----------------------------------------------------------

    def start(
        self,
        host: str,
        port: int,
        log_level: str,
    ) -> None:
        """Spawn the backend subprocess."""
        self._host = host
        self._port = port
        self._log_level = log_level

        env = os.environ.copy()
        env[LOG_LEVEL_ENV] = log_level

        is_windows = sys.platform == "win32"

        with self._lock:
            self._stderr_buf = ""
            self._manually_terminated = False
            self._proc = subprocess.Popen(
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

        if is_windows:
            threading.Thread(
                target=_stream_reader,
                args=(self._proc.stdout, sys.stdout),
                daemon=True,
            ).start()
            threading.Thread(
                target=_stderr_capture_reader,
                args=(self._proc.stderr, sys.stderr, self),
                daemon=True,
            ).start()

        logger.info(
            "Backend subprocess started (pid=%s, port=%s)",
            self._proc.pid,
            port,
        )

    def stop(self) -> None:
        """Terminate the backend subprocess gracefully."""
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                return
            self._manually_terminated = True

        logger.info("Terminating backend server...")
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
                except (ProcessLookupError, OSError) as exc:
                    logger.debug(
                        "kill() raised %s (process already exited)",
                        exc.__class__.__name__,
                    )
        except (ProcessLookupError, OSError) as exc:
            logger.debug(
                "terminate() raised %s (process already exited)",
                exc.__class__.__name__,
            )

    def restart(self) -> None:
        """Stop the current backend and start a fresh one."""
        self.stop()
        self.start(self._host, self._port, self._log_level)


class WebViewAPI:
    """API exposed to the webview for external links, file downloads,
    and backend lifecycle queries used by the loading page."""

    def __init__(self, backend: BackendProcessManager) -> None:
        self._backend = backend

    # -- Loading page callbacks ----------------------------------------------

    def check_backend_ready(self) -> dict:
        """Called by the loading page JS to poll backend readiness.

        Returns a dict with ``status`` (``ready`` | ``checking`` |
        ``error``) and, when ready, a ``url`` to navigate to.
        """
        import urllib.request

        if not self._backend.is_running:
            stderr = self._backend.get_stderr()
            return {
                "status": "error",
                "error": stderr or "Backend process exited unexpectedly.",
            }

        try:
            req = urllib.request.Request(
                self._backend.version_url,
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                if resp.status == 200:
                    return {
                        "status": "ready",
                        "url": self._backend.console_url,
                    }
        except Exception:
            pass

        return {"status": "checking"}

    def get_startup_error(self) -> str:
        """Return captured stderr from the backend process."""
        return self._backend.get_stderr()

    def restart_backend(self) -> None:
        """Kill the current backend and start a fresh one."""
        self._backend.restart()

    # -- Runtime callbacks (used after console is loaded) --------------------

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

        safe_name = re.sub(r'[<>:"/\\|?*]', "_", filename).strip(" .")

        try:
            result = webview.windows[0].create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=safe_name,
            )
            if not result:
                return False

            dest_path = result if isinstance(result, str) else result[0]

            request = urllib.request.Request(
                url,
                headers={
                    str(key): str(value)
                    for key, value in (headers or {}).items()
                    if value is not None
                },
            )

            with urllib.request.urlopen(request) as response:
                with open(dest_path, "wb") as f:
                    shutil.copyfileobj(response, f)

            return True
        except Exception:
            logger.exception("save_file failed")
            return False


def _validate_loopback_host(host: str) -> str:
    """Ensure *host* is a loopback address.

    The desktop backend must only bind to the local machine; binding to
    a non-loopback address would expose the API to the network.
    """
    if host in ("localhost", "127.0.0.1", "::1"):
        return host
    try:
        addr = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError(f"Invalid host: {host}") from exc
    if not addr.is_loopback:
        raise ValueError(
            f"Host {host!r} is not a loopback address; "
            "the desktop backend must only bind locally.",
        )
    return host


def _find_free_port(host: str = "127.0.0.1") -> int:
    """Bind to port 0 and return the OS-assigned free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.listen(1)
        return sock.getsockname()[1]


def _loading_page_url() -> str:
    """Return a ``file://`` URL pointing to the bundled loading page."""
    html = pathlib.Path(__file__).with_name("desktop_loading.html")
    if not html.exists():
        raise FileNotFoundError(f"loading page not found: {html}")
    return html.as_uri()


def _stream_reader(in_stream, out_stream) -> None:
    """Drain *in_stream* line-by-line into *out_stream* (stdout relay)."""
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


def _stderr_capture_reader(
    in_stream,
    out_stream,
    backend: BackendProcessManager,
) -> None:
    """Drain stderr into *out_stream* and capture into *backend*."""
    try:
        for line in iter(in_stream.readline, ""):
            if not line:
                break
            out_stream.write(line)
            out_stream.flush()
            backend.append_stderr(line)
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
    help="Bind host for the app server. Must be a loopback address.",
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

    Starts the FastAPI app in a subprocess on a free port, then
    immediately opens a native webview window with a loading page.
    The loading page polls the backend and navigates to the console
    once it is ready — giving instant visual feedback instead of
    blocking on HTTP readiness.
    """
    setup_logger(log_level)

    try:
        host = _validate_loopback_host(host)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    port = _find_free_port(host)
    url = f"http://{host}:{port}"
    click.echo(f"Starting QwenPaw app on {url} (port {port})")

    backend = BackendProcessManager()

    try:
        backend.start(host, port, log_level)

        loading_url = _loading_page_url()
        logger.info("Opening webview with loading page: %s", loading_url)

        api = WebViewAPI(backend)
        webview.create_window(
            "QwenPaw Desktop",
            loading_url,
            width=1280,
            height=800,
            text_select=True,
            js_api=api,
        )
        logger.info("Calling webview.start() (blocks until closed)...")
        webview.start(private_mode=False)
        logger.info("webview.start() returned (window closed).")
    except KeyboardInterrupt:
        logger.warning("KeyboardInterrupt in main, cleaning up...")
        raise
    except Exception as exc:
        logger.error("Exception: %r", exc)
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        raise
    finally:
        backend.stop()

        exit_code = backend.exit_code
        if (
            exit_code is not None
            and exit_code != 0
            and not backend.manually_terminated
        ):
            logger.error(
                "Backend process exited unexpectedly with code %s",
                exit_code,
            )
            if exit_code < 0:
                sys.exit(128 + abs(exit_code))
            else:
                sys.exit(exit_code or 1)
