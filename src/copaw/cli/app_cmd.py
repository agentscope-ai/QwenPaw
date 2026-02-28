# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os

import click
import uvicorn

from ..constant import LOG_LEVEL_ENV
from ..config.utils import write_last_api
from ..utils.logging import setup_logger, SuppressPathAccessLogFilter


@click.command("app")
@click.option(
    "--host",
    default="0.0.0.0",
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
    "--workers",
    default=1,
    type=int,
    show_default=True,
    help="Worker processes",
)
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
def app_cmd(
    host: str,
    port: int,
    reload: bool,
    workers: int,
    log_level: str,
    hide_access_paths: tuple[str, ...],
) -> None:
    """Run CoPaw FastAPI app."""
    # Warn user when listening on all interfaces (security awareness)
    if host == "0.0.0.0":
        click.echo(
            click.style(
                "⚠️  Warning: CoPaw is listening on all network interfaces "
                "(0.0.0.0). Other devices on your network can access this "
                "instance. Use --host 127.0.0.1 to restrict to localhost.",
                fg="yellow",
            )
        )

    # Persist last used host/port for other terminals
    write_last_api(host, port)
    os.environ[LOG_LEVEL_ENV] = log_level
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
        "copaw.app._app:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers,
        log_level=log_level,
    )
