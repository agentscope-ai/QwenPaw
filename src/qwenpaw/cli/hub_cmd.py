# -*- coding: utf-8 -*-
"""CLI entry point for QwenPaw Hub."""

from __future__ import annotations

from pathlib import Path

import click
from click.core import ParameterSource

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
    "--init-admin",
    "init_admin_username",
    metavar="USERNAME",
    help=(
        "Initialize the first administrator locally, then exit. "
        "The password is prompted securely."
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
@click.pass_context
def hub_cmd(
    context: click.Context,
    host: str,
    port: int,
    force_public: bool,
    init_admin_username: str | None,
    hub_config: Path | None,
    log_level: str,
    hide_access_paths: tuple[str, ...],
) -> None:
    """Run the multi-user QwenPaw Hub control plane."""
    if (
        init_admin_username is None
        and not is_loopback_host(host)
        and not force_public
    ):
        raise click.ClickException(
            "QwenPaw Hub refuses a non-loopback host by default. "
            "Use --force-public after initializing an administrator.",
        )

    if init_admin_username is not None:
        incompatible_options = [
            option
            for parameter, option in (
                ("host", "--host"),
                ("port", "--port"),
                ("force_public", "--force-public"),
                ("hub_config", "--config"),
                ("log_level", "--log-level"),
                ("hide_access_paths", "--hide-access-paths"),
            )
            if context.get_parameter_source(parameter)
            is not ParameterSource.DEFAULT
        ]
        if incompatible_options:
            formatted = ", ".join(incompatible_options)
            raise click.ClickException(
                f"--init-admin cannot be combined with {formatted}.",
            )

        from ..hub.auth import HubDatabaseBusyError
        from ..hub.bootstrap import (
            ensure_admin_initialization_available,
            initialize_hub_admin,
        )

        try:
            ensure_admin_initialization_available()
            password = click.prompt(
                "Administrator password",
                hide_input=True,
                confirmation_prompt=True,
            )
            user = initialize_hub_admin(init_admin_username, password)
        except (HubDatabaseBusyError, PermissionError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f"Administrator {user.username!r} initialized.")
        return

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
