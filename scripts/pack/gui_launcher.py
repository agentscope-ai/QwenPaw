# -*- coding: utf-8 -*-
# pylint:disable=unused-import
"""
Desktop GUI entry (macOS .app / Windows exe): start CoPaw server in background
and show Console in a native window (pywebview). Close window to quit.
Shared by scripts/pack/; used as entry point from macOS/Windows specs.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path
import uvicorn


def _desktop_support_dir() -> Path:
    """Default COPAW_WORKING_DIR for packaged app (macOS/Windows/other)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return Path(base) / "CoPaw"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CoPaw"
    return Path.home() / ".copaw"


_SUPPORT = _desktop_support_dir().resolve()
os.environ["COPAW_WORKING_DIR"] = str(_SUPPORT)

# Force PyInstaller to bundle reme (import is optional at runtime for dev).
try:
    import reme  # noqa: F401
except ImportError:
    pass


def _log(msg: str) -> None:
    """Write to stderr and to support-dir log for desktop runs."""
    print(msg, file=sys.stderr, flush=True)
    try:
        log_dir = _SUPPORT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "gui_launcher.log").open("a", encoding="utf-8") as f:
            f.write(msg.rstrip() + "\n")
    except OSError:
        pass


def _ensure_working_dir() -> None:
    """Create support dir and init config; COPAW_WORKING_DIR already set."""
    _SUPPORT.mkdir(parents=True, exist_ok=True)
    config = _SUPPORT / "config.json"
    if not config.is_file():
        from copaw.cli.init_cmd import init_cmd

        init_cmd.main(
            args=["--defaults", "--accept-security"],
            standalone_mode=False,
        )
    for name, default in (
        ("jobs.json", '{"version":1,"jobs":[]}'),
        ("chats.json", '{"version":1,"chats":[]}'),
    ):
        path = _SUPPORT / name
        if not path.is_file():
            path.write_text(default, encoding="utf-8")


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
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> None:
    _ensure_working_dir()
    _log(f"COPAW_WORKING_DIR={_SUPPORT}")

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
        (_SUPPORT / "last_base_url.txt").write_text(base_url, encoding="utf-8")
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
