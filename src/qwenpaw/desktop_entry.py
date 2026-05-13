# -*- coding: utf-8 -*-
"""Desktop entry point for Tauri sidecar auto-init + start backend."""
from __future__ import annotations

from collections.abc import Sequence
import os
import sys

import click

from qwenpaw.desktop_env import (
    DESKTOP_APP_ENV,
    DESKTOP_CORS_ORIGINS_ENV,
    DESKTOP_PORT_ENV,
)

DESKTOP_CORS_ORIGINS = (
    "tauri://localhost",
    "https://tauri.localhost",
    "http://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
)


def _ensure_desktop_cors_origins() -> None:
    origins = [
        origin.strip()
        for origin in os.environ.get(DESKTOP_CORS_ORIGINS_ENV, "").split(",")
        if origin.strip()
    ]
    for origin in DESKTOP_CORS_ORIGINS:
        if origin not in origins:
            origins.append(origin)
    os.environ[DESKTOP_CORS_ORIGINS_ENV] = ",".join(origins)


def _ensure_qwenpaw_constant_not_loaded() -> None:
    if "qwenpaw.constant" in sys.modules:
        raise RuntimeError(
            "qwenpaw.constant imported before desktop CORS origins were set",
        )


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
    os.environ.setdefault(DESKTOP_APP_ENV, "1")
    # Must run before importing qwenpaw modules: qwenpaw.constant snapshots
    # QWENPAW_CORS_ORIGINS at import time for FastAPI CORS setup.
    _ensure_qwenpaw_constant_not_loaded()
    _ensure_desktop_cors_origins()

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
    main()
