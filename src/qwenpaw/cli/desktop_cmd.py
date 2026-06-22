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

import click

from ..constant import LOG_LEVEL_ENV, WORKING_DIR
from ..utils.logging import setup_logger
from ..utils.port import get_stable_port

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]

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


def _detect_dark_mode() -> bool:
    """Detect if the system is using dark mode (Windows 10/11)."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
    except Exception:
        return False


def _create_loading_window():
    """Create a tkinter loading window shown while the backend starts.

    Returns:
        Tuple of (root, progress_bar, loading_label, bg_color, fg_color).
    """
    dark = _detect_dark_mode()
    bg = "#1e1e1e" if dark else "#ffffff"
    fg = "#e0e0e0" if dark else "#404040"
    fg_secondary = "#a0a0a0" if dark else "#808080"
    fg_dim = "#606060" if dark else "#c0c0c0"

    root = tk.Tk()
    root.title("QwenPaw Desktop")
    root.geometry("600x400")
    root.resizable(False, False)
    root.configure(bg=bg)

    # Center on screen
    root.update_idletasks()
    x = root.winfo_screenwidth() // 2 - 300
    y = root.winfo_screenheight() // 2 - 200
    root.geometry(f"600x400+{x}+{y}")

    # Brand title
    tk.Label(
        root,
        text="QwenPaw",
        font=("Segoe UI", 32, "bold"),
        fg=fg,
        bg=bg,
    ).pack(pady=(80, 20))

    # Loading status text
    loading_label = tk.Label(
        root,
        text="\u6b63\u5728\u542f\u52a8...",
        font=("Segoe UI", 12),
        fg=fg_secondary,
        bg=bg,
    )
    loading_label.pack(pady=10)

    # Indeterminate progress bar
    style = ttk.Style(root)
    style.theme_use("default")
    pb_style = (
        "Dark.Horizontal.TProgressbar" if dark else "Horizontal.TProgressbar"
    )
    progress_bar = ttk.Progressbar(
        root,
        mode="indeterminate",
        length=400,
        style=pb_style,
    )
    progress_bar.pack(pady=20)
    progress_bar.start(30)

    # Ensure window is visible before returning
    root.deiconify()
    root.update_idletasks()

    return root, progress_bar, loading_label, bg, fg_dim


def _set_loading_text(root, label, text, color=None):
    """Thread-safe update of loading label text."""

    def _update():
        label.configure(text=text)
        if color:
            label.configure(fg=color)

    root.after(0, _update)


def _open_webview(url: str) -> None:
    """Create and run the pywebview main window."""
    logger.info("Creating webview window...")
    api = WebViewAPI()
    webview.create_window(
        "QwenPaw Desktop",
        url,
        width=1280,
        height=800,
        text_select=True,
        js_api=api,
    )
    logger.info("Calling webview.start() (blocks until closed)...")
    # Persist localStorage/cookies across restarts so the
    # user's agent selection, chat history, and preferences
    # survive window close.  Without storage_path, WebView2
    # may use a temp directory that is discarded on restart.
    webview_storage = str(WORKING_DIR / "webview_data")
    webview.start(
        private_mode=False,
        storage_path=webview_storage,
    )  # blocks until user closes the window
    logger.info("webview.start() returned (window closed).")


def _terminate_backend_process(proc):
    """Terminate the backend subprocess cleanly."""
    global _manually_terminated
    if proc and proc.poll() is None:
        logger.info("Terminating backend server...")
        _manually_terminated = True
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5.0)
                logger.info("Backend server terminated cleanly.")
            except subprocess.TimeoutExpired:
                logger.warning("Backend did not exit in 5s, force killing...")
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
    elif proc:
        logger.info(f"Backend already exited with code {proc.returncode}")


def _start_backend_and_wait(  # pylint: disable=R0917
    host,
    port,
    log_level,
    is_windows,
    env,
    proc_ref,
    loading_state,
    url,
):
    """Start backend subprocess and wait for HTTP readiness.

    Runs in a background thread. Updates loading window during wait
    and opens webview when backend is ready.

    Args:
        proc_ref: Single-element list; proc_ref[0] is set to the Popen
            object once the subprocess is created.
        loading_state: Dict with keys ``root``, ``progress_bar``,
            ``loading_label``, ``bg``, ``fg_dim``.
    """
    root = loading_state["root"]
    progress_bar = loading_state["progress_bar"]
    loading_label = loading_state["loading_label"]
    fg_dim = loading_state["fg_dim"]

    # Start backend subprocess
    held_socket = loading_state.get("held_socket")
    if held_socket:
        held_socket.close()

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
        proc_ref[0] = proc
    except Exception as exc:
        logger.exception("Failed to start backend subprocess")
        _set_loading_text(
            root,
            loading_label,
            f"\u542f\u52a8\u5931\u8d25: {exc}",
            "#ff4444",
        )
        root.after(0, progress_bar.stop)
        return

    # Start stream reader threads (Windows)
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

    # Poll for HTTP readiness
    logger.info("Waiting for HTTP ready...")
    start_time = time.monotonic()
    timeout_sec = 300.0
    ready = False

    while time.monotonic() - start_time < timeout_sec:
        # Check if process exited prematurely
        if proc.poll() is not None:
            break
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect((host, port))
                ready = True
                break
        except (OSError, socket.error):
            elapsed = int(time.monotonic() - start_time)
            _set_loading_text(
                root,
                loading_label,
                f"\u6b63\u5728\u542f\u52a8... ({elapsed}s)",
            )
            time.sleep(1)

    # Handle premature process exit
    if not ready and proc.poll() is not None:
        logger.error(
            f"Backend process exited prematurely with code "
            f"{proc.returncode}"
        )

        def _show_error():
            progress_bar.stop()
            loading_label.configure(
                text="\u542f\u52a8\u5931\u8d25\uff0c\u8bf7\u91cd\u8bd5",
                fg="#ff4444",
            )
            retry_btn = tk.Button(
                root,
                text="\u91cd\u8bd5",
                command=_do_retry,
                font=("Segoe UI", 12),
                width=12,
            )
            retry_btn.pack(pady=20)

        def _do_retry():
            proc_ref[0] = None
            loading_label.configure(
                text="\u6b63\u5728\u542f\u52a8...",
                fg=fg_dim,
            )
            progress_bar.start(30)
            # Remove retry button (last packed widget)
            for w in root.winfo_children():
                if isinstance(w, tk.Button):
                    w.destroy()
                    break
            t = threading.Thread(
                target=_start_backend_and_wait,
                args=(
                    host,
                    port,
                    log_level,
                    is_windows,
                    env,
                    proc_ref,
                    loading_state,
                    url,
                ),
                daemon=True,
            )
            t.start()

        root.after(0, _show_error)
        return

    # Backend is ready
    if ready:
        logger.info("HTTP ready, transitioning to webview...")
        _set_loading_text(
            root,
            loading_label,
            "\u542f\u52a8\u5b8c\u6210\uff0c\u6b63\u5728\u6253\u5f00...",
        )
        # Signal main thread that backend is ready, then close loading window
        loading_state["backend_ready"] = True
        time.sleep(0.3)  # brief pause to show status text
        root.after(0, root.destroy)  # close from main thread
    else:
        # Timeout
        logger.error("Server did not become ready in time.")
        loading_state["backend_ready"] = False

        def _show_timeout():
            progress_bar.stop()
            loading_label.configure(
                text="\u542f\u52a8\u8d85\u65f6\uff0c\u8bf7\u91cd\u8bd5",
                fg="#ff4444",
            )

        root.after(0, _show_timeout)


# Module-level state for backend process lifecycle
_proc_ref: list = []
_manually_terminated: bool = False


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

    # get_stable_port() returns (port, socket) 鈥?the socket is kept open
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

    try:
        # Show loading window immediately so the user sees feedback
        # while the backend starts in the background.
        (
            root,
            progress_bar,
            loading_label,
            bg,
            fg_dim,
        ) = _create_loading_window()

        proc_ref: list = [None]
        loading_state = {
            "root": root,
            "progress_bar": progress_bar,
            "loading_label": loading_label,
            "bg": bg,
            "fg_dim": fg_dim,
            "held_socket": held_socket,
        }

        backend_thread = threading.Thread(
            target=_start_backend_and_wait,
            args=(
                host,
                port,
                log_level,
                is_windows,
                env,
                proc_ref,
                loading_state,
                url,
            ),
            daemon=True,
        )
        backend_thread.start()

        root.mainloop()  # blocks until loading window is closed

        # If backend is ready, open webview on the main thread.
        # pywebview.start() MUST run on the main thread.
        if loading_state.get("backend_ready"):
            _open_webview(url)  # blocks until user closes the window

        # After webview closes, ensure backend process is cleaned up
        proc = proc_ref[0]
        _terminate_backend_process(proc)

        # Report unexpected backend exit
        if proc and proc.returncode != 0 and not _manually_terminated:
            logger.error(
                f"Backend process exited unexpectedly with code "
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
