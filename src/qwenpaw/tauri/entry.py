# -*- coding: utf-8 -*-
"""Tauri sidecar entry point for starting the Python backend."""
from __future__ import annotations

from collections.abc import Sequence
import json
import logging
import multiprocessing as mp
import os
import socket
import sys

import click

from qwenpaw.tauri.env import (
    DESKTOP_APP_ENV,
    DESKTOP_CORS_ORIGINS_ENV,
    DESKTOP_READY_PREFIX,
    ensure_desktop_cors_origins,
)
from qwenpaw.tauri.sidecar_logging import install_sidecar_logging

logger = logging.getLogger(__name__)


def _argv_looks_like_package_manager() -> bool:
    """Detect being invoked as if this binary were a Python interpreter.

    The frozen backend is sometimes mistakenly used as ``sys.executable`` to
    run ``-m pip``; since it ignores such argv and just starts another server,
    that path recursively re-launches the backend (issue #5209). Reject it.
    """
    args = sys.argv[1:]
    if not args:
        return False
    flat = set(args)
    return "-m" in flat or "pip" in flat or "--target" in flat


def _install_windows_no_window_guard() -> None:
    """On the Windows desktop build, suppress console windows for child
    processes — including third-party plugins that shell out to commands
    like ``tasklist`` without passing ``CREATE_NO_WINDOW`` themselves.
    """
    if os.name != "nt":
        return
    if not (
        getattr(sys, "frozen", False)
        or os.environ.get(DESKTOP_APP_ENV) == "1"
    ):
        return
    import subprocess

    if getattr(subprocess.Popen, "_qwenpaw_no_window", False):
        return

    create_no_window = 0x08000000
    create_new_console = 0x00000010
    original_init = subprocess.Popen.__init__

    def _init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        flags = kwargs.get("creationflags", 0) or 0
        # Respect callers that explicitly want a visible new console.
        if not flags & create_new_console:
            kwargs["creationflags"] = flags | create_no_window
        startupinfo = kwargs.get("startupinfo") or subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = startupinfo
        return original_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _init  # type: ignore[method-assign]
    subprocess.Popen._qwenpaw_no_window = True  # type: ignore[attr-defined]


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


def _install_certifi_env() -> None:
    if os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi
    except Exception:
        logger.debug(
            "certifi is unavailable; leaving SSL bundle env unset",
            exc_info=True,
        )
        return

    cert_file = certifi.where()
    if not cert_file or not os.path.isfile(cert_file):
        logger.debug(
            "certifi returned an invalid certificate path: %r",
            cert_file,
        )
        return
    os.environ.setdefault("SSL_CERT_FILE", cert_file)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", cert_file)
    os.environ.setdefault("CURL_CA_BUNDLE", cert_file)


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
        if exc.code in (None, 0):
            return
        message = f"desktop {label} exited with code {exc.code}"
        print(message, file=sys.stderr)
        raise RuntimeError(message) from exc


def _emit_backend_ready(port: int) -> None:
    payload = json.dumps({"port": port}, separators=(",", ":"))
    print(f"{DESKTOP_READY_PREFIX} {payload}", flush=True)


def _run_backend_server(log_level: str) -> None:
    import uvicorn

    from qwenpaw.config.utils import write_last_api
    from qwenpaw.constant import LOG_LEVEL_ENV, WORKING_DIR
    from qwenpaw.utils.logging import (
        SuppressPathAccessLogFilter,
        setup_logger,
    )
    from qwenpaw.utils.port import get_stable_port, write_port_file

    host = "127.0.0.1"
    normalized_log_level = log_level.lower()
    if normalized_log_level not in {
        "critical",
        "error",
        "warning",
        "info",
        "debug",
        "trace",
    }:
        normalized_log_level = "info"

    os.environ[LOG_LEVEL_ENV] = normalized_log_level
    os.environ.pop("QWENPAW_RELOAD_MODE", None)
    setup_logger(normalized_log_level)
    if normalized_log_level in ("debug", "trace"):
        from qwenpaw.cli.main import log_init_timings

        log_init_timings()

    logging.getLogger("uvicorn.access").addFilter(
        SuppressPathAccessLogFilter(["/console/push-messages"]),
    )

    # Reuse the previous port so localStorage origin stays stable across
    # restarts, preserving user preferences (selected agent, etc.).
    port_file = str(WORKING_DIR / "desktop_port")
    port, reused_socket = get_stable_port(port_file, host)

    config = uvicorn.Config(
        "qwenpaw.app._app:app",
        host=host,
        port=0,
        reload=False,
        workers=1,
        log_level=normalized_log_level,
    )

    if reused_socket:
        backend_socket = reused_socket
    else:
        backend_socket = config.bind_socket()

    try:
        port = _socket_port(backend_socket)
        write_port_file(port_file, port)
        write_last_api(host, port)
        _emit_backend_ready(port)
        uvicorn.Server(config).run(sockets=[backend_socket])
    except Exception:
        backend_socket.close()
        raise


def _socket_port(sock: socket.socket) -> int:
    address = sock.getsockname()
    if not isinstance(address, tuple) or len(address) < 2:
        raise RuntimeError(f"unexpected backend socket address: {address!r}")
    return int(address[1])


def main() -> None:
    if _argv_looks_like_package_manager():
        print(
            "qwenpaw-backend is the desktop backend, not a Python "
            "interpreter; refusing package-manager arguments: "
            f"{sys.argv[1:]}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    _ensure_utf8_stdio()
    _install_windows_no_window_guard()
    _install_desktop_runtime()

    from qwenpaw.constant import LOG_LEVEL_ENV, WORKING_DIR

    install_sidecar_logging(WORKING_DIR / "desktop.log")
    _install_certifi_env()

    # Auto-initialize if no config exists
    config_path = WORKING_DIR / "config.json"
    if not config_path.exists():
        from qwenpaw.cli.init_cmd import init_cmd

        _run_click_command(
            init_cmd,
            args=["--defaults", "--accept-security"],
            label="initialization",
        )

    _run_backend_server(os.environ.get(LOG_LEVEL_ENV, "info"))


if __name__ == "__main__":
    mp.freeze_support()
    main()
