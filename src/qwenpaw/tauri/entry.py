# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,wrong-import-order
"""Tauri sidecar entry point for starting the Python backend."""
from __future__ import annotations

import time

# Keep this before heavier imports so startup timing includes module import cost.
_STARTUP_STARTED_AT = time.perf_counter()
_STARTUP_LAST_AT = _STARTUP_STARTED_AT

from collections.abc import Sequence  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import multiprocessing as mp  # noqa: E402
import os  # noqa: E402
import socket  # noqa: E402
import sys  # noqa: E402

import click  # noqa: E402

from qwenpaw.tauri.env import (  # noqa: E402
    DESKTOP_APP_ENV,
    DESKTOP_CORS_ORIGINS_ENV,
    DESKTOP_READY_PREFIX,
    ensure_desktop_cors_origins,
)
from qwenpaw.tauri.sidecar_logging import install_sidecar_logging  # noqa: E402

logger = logging.getLogger(__name__)


def _emit_startup_timing(phase: str, **details: object) -> None:
    global _STARTUP_LAST_AT

    now = time.perf_counter()
    elapsed_ms = round((now - _STARTUP_STARTED_AT) * 1000.0, 1)
    delta_ms = round((now - _STARTUP_LAST_AT) * 1000.0, 1)
    _STARTUP_LAST_AT = now

    payload = {
        "component": "tauri.entry",
        "phase": phase,
        "elapsed_ms": elapsed_ms,
        "delta_ms": delta_ms,
        **details,
    }
    line = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    print(f"QWENPAW_BACKEND_TIMING {line}", flush=True)
    logger.info("Desktop startup timing: %s", payload)


_emit_startup_timing("module_loaded")


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
    _emit_startup_timing("backend_server_start", log_level=log_level)
    import uvicorn

    _emit_startup_timing("uvicorn_imported")
    from qwenpaw.config.utils import write_last_api
    from qwenpaw.constant import LOG_LEVEL_ENV, WORKING_DIR
    from qwenpaw.utils.logging import (
        SuppressPathAccessLogFilter,
        setup_logger,
    )
    from qwenpaw.utils.port import get_stable_port, write_port_file
    _emit_startup_timing("backend_dependencies_imported")

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
    _emit_startup_timing(
        "backend_logger_configured",
        normalized_log_level=normalized_log_level,
    )
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
    _emit_startup_timing("uvicorn_config_created")
    if reused_socket:
        backend_socket = reused_socket
        _emit_startup_timing("socket_reused", port=port)
    else:
        backend_socket = config.bind_socket()
        _emit_startup_timing("socket_bound")
    try:
        port = _socket_port(backend_socket)
        write_port_file(port_file, port)
        write_last_api(host, port)
        _emit_startup_timing("last_api_written", port=port)
        _emit_backend_ready(port)
        _emit_startup_timing("ready_signal_emitted", port=port)
        _emit_startup_timing("uvicorn_server_starting", port=port)
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
    _emit_startup_timing("main_started")
    _ensure_utf8_stdio()
    _emit_startup_timing("stdio_configured")
    _install_desktop_runtime()
    _emit_startup_timing("desktop_runtime_installed")

    from qwenpaw.constant import LOG_LEVEL_ENV, WORKING_DIR

    _emit_startup_timing("constants_imported")
    install_sidecar_logging(WORKING_DIR / "desktop.log")
    _emit_startup_timing("sidecar_logging_installed")
    _install_certifi_env()
    _emit_startup_timing("certifi_env_installed")

    # Auto-initialize if no config exists
    config_path = WORKING_DIR / "config.json"
    _emit_startup_timing("config_checked", exists=config_path.exists())
    if not config_path.exists():
        from qwenpaw.cli.init_cmd import init_cmd

        _emit_startup_timing("initialization_starting")
        _run_click_command(
            init_cmd,
            args=["--defaults", "--accept-security"],
            label="initialization",
        )
        _emit_startup_timing("initialization_finished")

    _run_backend_server(os.environ.get(LOG_LEVEL_ENV, "info"))


if __name__ == "__main__":
    mp.freeze_support()
    main()
