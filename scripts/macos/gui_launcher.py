# -*- coding: utf-8 -*-
"""
macOS .app GUI entry: start CoPaw server in background and show Console in a
native window (pywebview). Close window to quit server and app.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
import uvicorn

# Set working dir before any copaw import (constant.WORKING_DIR is read at import).
_SUPPORT = os.path.abspath(
    os.path.expanduser("~/Library/Application Support/CoPaw"),
)
os.environ["COPAW_WORKING_DIR"] = _SUPPORT


def _log(msg: str) -> None:
    """Write to stderr and to support-dir log for .app runs."""
    print(msg, file=sys.stderr, flush=True)
    support = os.path.expanduser("~/Library/Application Support/CoPaw")
    log_dir = os.path.join(support, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(
            os.path.join(log_dir, "gui_launcher.log"),
            "a",
            encoding="utf-8",
        ) as f:
            f.write(msg.rstrip() + "\n")
            f.flush()
    except OSError:
        pass


# Create support dir and init config; COPAW_WORKING_DIR already set at top.
def _ensure_working_dir() -> None:
    support = _SUPPORT
    os.makedirs(support, exist_ok=True)
    config = os.path.join(support, "config.json")
    if not os.path.isfile(config):
        from copaw.cli.init_cmd import init_cmd

        init_cmd.main(
            args=["--defaults", "--accept-security"],
            standalone_mode=False,
        )
    # Ensure data files exist so backend APIs return valid structure (not 404/500).
    for name in ("jobs.json", "chats.json"):
        path = os.path.join(support, name)
        if not os.path.isfile(path):
            with open(path, "w", encoding="utf-8") as f:
                if name == "jobs.json":
                    f.write('{"version":1,"jobs":[]}')
                else:
                    f.write('{"version":1,"chats":[]}')


def _wait_for_server(url: str, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.2)
    return False


def _run_server(server: "uvicorn.Server") -> None:
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(server.serve())
    finally:
        loop.close()


def _pick_free_port() -> int:
    """Bind to 127.0.0.1:0 and return the chosen port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> None:
    _ensure_working_dir()
    support = os.environ.get("COPAW_WORKING_DIR", "")
    _log(f"COPAW_WORKING_DIR={support}")

    from copaw.utils.logging import setup_logger

    setup_logger("info")
    port = _pick_free_port()
    config = uvicorn.Config(
        "copaw.app._app:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(
        target=_run_server,
        args=(server,),
        daemon=True,
    )
    thread.start()

    base_url = f"http://127.0.0.1:{port}/"
    if not _wait_for_server(base_url):
        _log(f"CoPaw server failed to start (port {port}).")
        server.should_exit = True
        sys.exit(1)
    try:
        with open(
            os.path.join(support, "last_base_url.txt"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(base_url)
    except OSError:
        pass

    import webview

    webview.create_window(
        "CoPaw",
        base_url,
        width=1200,
        height=800,
        min_size=(800, 600),
        resizable=True,
    )
    webview.start()
    server.should_exit = True


if __name__ == "__main__":
    try:
        main()
    except Exception:  # pylint: disable=broad-except
        _log(traceback.format_exc())
        raise
