# -*- coding: utf-8 -*-
from __future__ import annotations

import ipaddress
import logging
import os
import socket
import sys

import click
import uvicorn

from ..constant import LOG_LEVEL_ENV, EnvVarLoader
from ..config.utils import write_last_api
from ..utils.logging import setup_logger, SuppressPathAccessLogFilter


_LOOPBACK_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})


def _host_is_loopback(host: str) -> bool:
    """Return True when *host* binds only to a loopback interface.

    Accepts IPv4/IPv6 literals and a small allowlist of well-known
    loopback hostnames. Anything that resolves to a non-loopback
    address — including ``0.0.0.0``, ``::``, and arbitrary public
    interfaces or hostnames — returns False.
    """
    if not host:
        return False
    if host.lower() in _LOOPBACK_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    # Hostname: only treat as loopback if every resolved address is loopback.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            if not ipaddress.ip_address(addr).is_loopback:
                return False
        except ValueError:
            return False
    return True


def _enforce_unauth_public_bind_safety(
    host: str,
    allow_unauth_public: bool,
) -> None:
    """Refuse non-loopback bind when no auth gate is configured.

    QwenPaw's HTTP gateway can invoke host-affecting tools (shell
    commands, file IO, etc.). Authentication is opt-in via
    ``QWENPAW_AUTH_ENABLED``; binding to a non-loopback address with
    auth disabled effectively exposes a tool-enabled agent on the
    network with no gate. We refuse this configuration unless the
    operator explicitly opts in via ``--allow-unauth-public`` or the
    ``QWENPAW_ALLOW_UNAUTH_PUBLIC`` env var.
    """
    if _host_is_loopback(host):
        return

    # Lazy import to avoid pulling app stack into CLI startup.
    from ..app.auth import is_auth_enabled

    if is_auth_enabled():
        return

    env_override = EnvVarLoader.get_str(
        "QWENPAW_ALLOW_UNAUTH_PUBLIC", ""
    ).strip().lower() in ("true", "1", "yes")
    if allow_unauth_public or env_override:
        click.echo(
            "⚠️  WARNING: binding to a non-loopback address "
            f"({host}) with authentication disabled.",
            err=True,
        )
        click.echo(
            "   The QwenPaw HTTP gateway exposes tool-enabled agents that "
            "can run shell commands, read files, and call external APIs.",
            err=True,
        )
        click.echo(
            "   Anyone who can reach this port can drive those tools. "
            "Make sure auth is enforced upstream (reverse proxy, VPN, "
            "Tailscale, security group) before exposing this port.",
            err=True,
        )
        click.echo(err=True)
        return

    click.echo(
        f"❌ Refusing to bind to non-loopback host '{host}' with "
        "authentication disabled.",
        err=True,
    )
    click.echo(err=True)
    click.echo(
        "QwenPaw's HTTP gateway can invoke host-affecting tools (shell "
        "commands, file IO, external APIs). Exposing it on a non-loopback "
        "interface without an authentication gate would let anyone who "
        "reaches the port drive those tools.",
        err=True,
    )
    click.echo(err=True)
    click.echo("To proceed, choose one of the following:", err=True)
    click.echo(err=True)
    click.echo(
        "  1. (recommended) Bind to loopback and put a reverse proxy / "
        "Tailscale / VPN in front:",
        err=True,
    )
    click.echo("       qwenpaw app --host 127.0.0.1 --port <PORT>", err=True)
    click.echo(err=True)
    click.echo("  2. Enable QwenPaw's built-in authentication:", err=True)
    click.echo("       export QWENPAW_AUTH_ENABLED=true", err=True)
    click.echo(
        "       qwenpaw app --host <HOST> --port <PORT>   " "# then register at /login",
        err=True,
    )
    click.echo(err=True)
    click.echo(
        "  3. Override the safety check (only if auth is enforced "
        "upstream by a reverse proxy / VPN you control):",
        err=True,
    )
    click.echo(
        "       qwenpaw app --host <HOST> --port <PORT> " "--allow-unauth-public",
        err=True,
    )
    click.echo(
        "       # or set QWENPAW_ALLOW_UNAUTH_PUBLIC=true in the service "
        "environment.",
        err=True,
    )
    click.echo(err=True)
    sys.exit(2)


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
    default=("/console/push-messages",),
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
@click.option(
    "--allow-unauth-public",
    is_flag=True,
    default=False,
    help="Allow binding to a non-loopback address even when "
    "QWENPAW_AUTH_ENABLED is not set. Only use this when an upstream "
    "reverse proxy or VPN enforces authentication. Can also be set via "
    "the QWENPAW_ALLOW_UNAUTH_PUBLIC environment variable.",
)
def app_cmd(
    host: str,
    port: int,
    reload: bool,
    workers: int,  # pylint: disable=unused-argument
    log_level: str,
    hide_access_paths: tuple[str, ...],
    allow_unauth_public: bool,
) -> None:
    """Run QwenPaw FastAPI app."""
    # Handle deprecated --workers parameter
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

    _enforce_unauth_public_bind_safety(host, allow_unauth_public)

    # Persist last used host/port for other terminals
    if host == "0.0.0.0":
        write_last_api("127.0.0.1", port)
    else:
        write_last_api(host, port)
    os.environ[LOG_LEVEL_ENV] = log_level

    # Signal reload mode to browser_control.py for Windows
    # compatibility: use sync Playwright + ThreadPool only when reload=True
    if reload:
        os.environ["QWENPAW_RELOAD_MODE"] = "1"
    else:
        os.environ.pop("QWENPAW_RELOAD_MODE", None)

    setup_logger(log_level)
    if log_level in ("debug", "trace"):
        from .main import log_init_timings

        log_init_timings()

    paths = [p for p in hide_access_paths if p]
    if paths:
        logging.getLogger("uvicorn.access").addFilter(
            SuppressPathAccessLogFilter(paths),
        )

    uvicorn.run(
        "qwenpaw.app._app:app",
        host=host,
        port=port,
        reload=reload,
        workers=1,
        log_level=log_level,
    )
