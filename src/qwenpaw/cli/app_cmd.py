# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os

import click
import uvicorn

from ..app.auth import is_auth_enabled
from ..browser.control_link.chrome.protocol import NM_MAX_INBOUND_BYTES
from ..config.utils import write_last_api
from ..constant import LOG_LEVEL_ENV
from ..utils.http import is_loopback_host, probe_host_for_bind_host
from ..utils.logging import SuppressPathAccessLogFilter, setup_logger
from ..utils.platform import warn_unelevated_sandbox

logger = logging.getLogger(__name__)


def _format_bind_address(host: str, port: int) -> str:
    """Return a readable bind address for startup logs."""
    normalized_host = host.strip()
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"
    return f"{normalized_host}:{port}"


def _warn_if_auth_off_non_loopback_bind(host: str, port: int) -> None:
    """Warn when QwenPaw is reachable beyond loopback without auth."""
    if is_auth_enabled() or is_loopback_host(host):
        return

    bind_address = _format_bind_address(host, port)
    warning = f"""
============================================================
SECURITY NOTICE: QwenPaw is bound to {bind_address} without authentication.

Anyone who can reach this address may access QwenPaw APIs without login.

Recommended:
  - Restrict access to a trusted network interface or protected environment.
  - Enable authentication with QWENPAW_AUTH_ENABLED=true if untrusted users or
    processes may reach this address.
============================================================
""".strip()
    if logger.isEnabledFor(logging.WARNING):
        logger.warning("\n%s", warning)
    else:
        click.echo(warning, err=True)


def configure_server_process(
    host: str,
    port: int,
    log_level: str,
    hide_access_paths: tuple[str, ...],
    *,
    reload: bool = False,
) -> None:
    """Configure shared process state for an HTTP server command."""
    write_last_api(probe_host_for_bind_host(host), port)
    os.environ[LOG_LEVEL_ENV] = log_level
    if reload:
        os.environ["QWENPAW_RELOAD_MODE"] = "1"

    setup_logger(log_level)
    if log_level in ("debug", "trace"):
        from .main import log_init_timings

        log_init_timings()

    paths = [path for path in hide_access_paths if path]
    if paths:
        logging.getLogger("uvicorn.access").addFilter(
            SuppressPathAccessLogFilter(paths),
        )
    warn_unelevated_sandbox()


@click.command("app")
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Bind host",
)
@click.option(
    "--port",
    default=8088,
    type=int,
    show_default=True,
    help="Bind port",
)
@click.option("--reload", is_flag=True, help="Enable auto-reload (dev only)")
@click.option(
    "--log-level",
    default="info",
    type=click.Choice(
        ["critical", "error", "warning", "info", "debug", "trace"],
        case_sensitive=False,
    ),
    show_default=True,
    help="Log level",
)
@click.option(
    "--hide-access-paths",
    multiple=True,
    default=("/console/push-messages", "/console/inbox/events"),
    show_default=True,
    help="Path substrings to hide from uvicorn access log (repeatable).",
)
@click.option(
    "--workers",
    type=int,
    default=None,
    help="[DEPRECATED] Number of worker processes. "
    "This option is deprecated and will be removed in a future version. "
    "QwenPaw always uses 1 worker.",
)
def app_cmd(
    host: str,
    port: int,
    reload: bool,
    workers: int,  # pylint: disable=unused-argument
    log_level: str,
    hide_access_paths: tuple[str, ...],
) -> None:
    """Run QwenPaw FastAPI app."""
    # NOTE: the server intentionally runs UNPRIVILEGED. The Windows
    # restricted-token sandbox no longer requires the whole server to be
    # elevated (which PR #5931 forced via ShellExecuteW("runas"), breaking
    # headless / VBS launchers with a surprise UAC prompt and a detached,
    # un-closable window). If sandbox is enabled but the process is not
    # admin, warn_unelevated_sandbox() below will log a warning about
    # reduced isolation before the server starts.

    if workers is not None:
        click.echo(
            "⚠️  WARNING: --workers option is deprecated and will be removed "
            "in a future version.",
            err=True,
        )
        click.echo(
            "   QwenPaw always uses 1 worker for stability. "
            "Your specified value will be ignored.",
            err=True,
        )
        click.echo(err=True)

    configure_server_process(
        host,
        port,
        log_level,
        hide_access_paths,
        reload=reload,
    )
    _warn_if_auth_off_non_loopback_bind(host, port)

    uvicorn.run(
        "qwenpaw.app._app:app",
        host=host,
        port=port,
        reload=reload,
        workers=1,
        log_level=log_level,
        # Bound shutdown so workspace SSE connections cannot block exit.
        timeout_graceful_shutdown=5,
        # Chrome Native Messaging inbound limit; this server-wide value is a
        # protocol fact rather than a user-configurable WebSocket capacity.
        ws_max_size=NM_MAX_INBOUND_BYTES,
    )
