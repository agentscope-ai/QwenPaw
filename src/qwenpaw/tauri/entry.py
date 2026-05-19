# -*- coding: utf-8 -*-
"""Tauri sidecar entry point for starting the Python backend."""
from __future__ import annotations

from collections.abc import Sequence
import multiprocessing as mp
import os
import sys

import click

from qwenpaw.desktop_env import DESKTOP_APP_ENV
from qwenpaw.tauri.env import (
    DESKTOP_CORS_ORIGINS_ENV,
    DESKTOP_PORT_ENV,
    ensure_desktop_cors_origins,
)


def _ensure_qwenpaw_app_not_loaded() -> None:
    if "qwenpaw.app._app" in sys.modules:
        raise RuntimeError(
            "qwenpaw app imported before desktop CORS origins were set",
        )


def _sync_loaded_qwenpaw_constant_cors_origins() -> None:
    constant_module = sys.modules.get("qwenpaw.constant")
    if constant_module is not None:
        constant_module.CORS_ORIGINS = os.environ.get(
            DESKTOP_CORS_ORIGINS_ENV,
            "",
        ).strip()


def _ensure_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _install_desktop_runtime() -> None:
    os.environ.setdefault(DESKTOP_APP_ENV, "1")
    # Must run before importing the FastAPI app: it applies CORS middleware
    # from qwenpaw.constant.CORS_ORIGINS at import time.
    _ensure_qwenpaw_app_not_loaded()
    ensure_desktop_cors_origins()
    _sync_loaded_qwenpaw_constant_cors_origins()


def _run_click_command(
    command: click.Command,
    args: Sequence[str],
    label: str,
) -> None:
    try:
        command.main(args=args, standalone_mode=False)
    except click.ClickException as exc:
        message = f"desktop {label} failed: {exc.format_message()}"
        print(message, file=sys.stderr)
        raise RuntimeError(message) from exc
    except click.Abort as exc:
        message = f"desktop {label} aborted"
        print(message, file=sys.stderr)
        raise RuntimeError(message) from exc
    except SystemExit as exc:
        message = f"desktop {label} exited with code {exc.code}"
        print(message, file=sys.stderr)
        raise RuntimeError(message) from exc


def main() -> None:
    _ensure_utf8_stdio()
    _install_desktop_runtime()

    from qwenpaw.cli.init_cmd import init_cmd
    from qwenpaw.cli.app_cmd import app_cmd
    from qwenpaw.constant import WORKING_DIR

    port = os.environ.get(DESKTOP_PORT_ENV)
    if not port:
        raise RuntimeError(
            f"{DESKTOP_PORT_ENV} not set; "
            "this entry must be launched by the Tauri shell.",
        )

    # Auto-initialize if no config exists
    config_path = WORKING_DIR / "config.json"
    if not config_path.exists():
        _run_click_command(
            init_cmd,
            args=["--defaults", "--accept-security"],
            label="initialization",
        )

    # Start the backend server. Use standalone_mode=False so exceptions
    # propagate back to main() for consistent error handling.
    _run_click_command(
        app_cmd,
        args=["--host", "127.0.0.1", "--port", port, "--no-write-last-api"],
        label="backend startup",
    )


if __name__ == "__main__":
    mp.freeze_support()
    main()
