# -*- coding: utf-8 -*-
"""CLI entry point for QwenPaw Hub."""

from __future__ import annotations

from pathlib import Path

import click

from ..utils.http import is_loopback_host
from .app_cmd import configure_server_process


@click.command("hub")
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
@click.option(
    "--force-public",
    is_flag=True,
    help=(
        "Allow Hub to bind beyond loopback after an administrator "
        "has been initialized."
    ),
)
@click.option(
    "--config",
    "hub_config",
    type=click.Path(
        path_type=Path,
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    help="Hub startup configuration file.",
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
    default=("/console/push-messages", "/console/inbox/events"),
    show_default=True,
    help="Path substrings to hide from uvicorn access log (repeatable).",
)
def hub_cmd(
    host: str,
    port: int,
    force_public: bool,
    hub_config: Path | None,
    log_level: str,
    hide_access_paths: tuple[str, ...],
) -> None:
    """Run the multi-user QwenPaw Hub control plane."""
    if not is_loopback_host(host) and not force_public:
        raise click.ClickException(
            "QwenPaw Hub refuses a non-loopback host by default. "
            "Use --force-public after initializing an administrator.",
        )

    configure_server_process(
        host,
        port,
        log_level,
        hide_access_paths,
    )

    try:
        from ..hub.control_app import run_hub_app
    except ModuleNotFoundError as exc:
        if exc.name != "docker":
            raise
        raise click.ClickException(
            f"QwenPaw Hub dependency {exc.name!r} is not installed. "
            f"Install qwenpaw[hub] to provide {exc.name!r} and try again.",
        ) from exc

    try:
        run_hub_app(
            host=host,
            port=port,
            log_level=log_level,
            config_path=hub_config,
            force_public=force_public,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
