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
from collections.abc import Mapping
from pathlib import Path

import click

from ..constant import LOG_LEVEL_ENV, WORKING_DIR
from ..utils.logging import setup_logger
from ..utils.port import get_stable_port

try:
    import webview
except ImportError:
    webview = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


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


def _wait_for_backend(
    host: str,
    port: int,
    timeout_sec: float = 300.0,
) -> bool:
    """Block until backend HTTP is accepting connections."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with socket.socket(
                socket.AF_INET,
                socket.SOCK_STREAM,
            ) as s:
                s.settimeout(2.0)
                s.connect((host, port))
                return True
        except (OSError, socket.error):
            time.sleep(1)
    return False


def _terminate_process(proc) -> bool:
    """Terminate the backend subprocess cleanly.

    Returns True if the process was intentionally terminated.
    """
    if proc and proc.poll() is None:
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
                except (ProcessLookupError, OSError) as e:
                    logger.debug(
                        f"kill() raised {e.__class__.__name__} "
                        f"(process already exited)",
                    )
        except (ProcessLookupError, OSError) as e:
            logger.debug(
                f"terminate() raised {e.__class__.__name__} "
                f"(process already exited)",
            )
        return True
    if proc:
        logger.info(
            f"Backend already exited with code {proc.returncode}",
        )
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
    """Run QwenPaw app on an auto-selected free port in a webview window.

    Starts the FastAPI app in a subprocess on a free port, then opens a
    native webview window loading that URL. Use for a dedicated desktop
    window without conflicting with an existing QwenPaw app instance.
    """
    setup_logger(log_level)

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
    manually_terminated = False

    try:
        # Release the held socket just before spawning the subprocess
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

        # Start stream readers on Windows
        if is_windows:
            for stream_in, stream_out in (
                (proc.stdout, sys.stdout),
                (proc.stderr, sys.stderr),
            ):
                t = threading.Thread(
                    target=_stream_reader,
                    args=(stream_in, stream_out),
                    daemon=True,
                )
                t.start()

        # ---- Show loading page immediately in webview ----
        loading_html = (
            Path(__file__).parent / "desktop_loading.html"
        ).resolve()
        loading_url = loading_html.as_uri()
        logger.info(
            "Creating webview window with loading page: %s",
            loading_url,
        )

        api = WebViewAPI()
        win = webview.create_window(
            "QwenPaw Desktop",
            loading_url,
            width=1280,
            height=800,
            text_select=True,
            js_api=api,
        )

        start_time = time.monotonic()

        def _backend_monitor() -> None:
            """Wait for backend HTTP ready, then navigate to it."""
            logger.info("Waiting for HTTP ready...")
            if not _wait_for_backend(host, port):
                logger.error("Server did not become ready in time.")
                try:
                    win.evaluate_js(
                        "if(window.setError)window.setError("
                        "'\u670d\u52a1\u542f\u52a8\u8d85\u65f6');",
                    )
                except Exception:
                    pass
                return

            elapsed = int(time.monotonic() - start_time)
            console_url = f"{url}/#_ls={elapsed}"
            logger.info(
                "Backend ready after %ds, navigating to %s",
                elapsed,
                console_url,
            )
            try:
                # Store elapsed seconds in sessionStorage for
                # the Console overlay to pick up
                win.evaluate_js(
                    f"try{{sessionStorage.setItem("
                    f"'qp_ls','{elapsed}')"
                    f"}}catch(e){{}}",
                )
                time.sleep(0.15)
                win.load_url(console_url)
            except Exception as exc:
                logger.error("load_url failed: %s", exc)
                try:
                    win.evaluate_js(
                        "if(window.setError)window.setError("
                        "'\u9875\u9762\u52a0\u8f7d\u5931\u8d25');",
                    )
                except Exception:
                    pass

        mon = threading.Thread(target=_backend_monitor, daemon=True)
        mon.start()

        # webview.start() blocks until the window is closed
        logger.info(
            "Calling webview.start() (blocks until closed)...",
        )
        webview_storage = str(WORKING_DIR / "webview_data")
        webview.start(
            private_mode=False,
            storage_path=webview_storage,
        )
        logger.info(
            "webview.start() returned (window closed).",
        )

        # Cleanup backend
        manually_terminated = _terminate_process(proc)

        # Report unexpected exit
        if proc and proc.returncode != 0 and not manually_terminated:
            logger.error(
                "Backend process exited unexpectedly with code "
                f"{proc.returncode}",
            )
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
