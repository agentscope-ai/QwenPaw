# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import sys
import time

import click

# On Windows, force UTF-8 for stdout/stderr so cron and other commands
# can handle Chinese and other non-ASCII (Linux is UTF-8 by default).
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

# pylint: disable=wrong-import-position

logger = logging.getLogger(__name__)
# Store init timings so app_cmd can re-log after setting log level to debug.
_init_timings: list[tuple[str, float]] = []
_t0_main = time.perf_counter()
_init_timings.append(("main.py loaded", 0.0))


def _record(label: str, elapsed: float) -> None:
    _init_timings.append((label, elapsed))
    logger.debug("%.3fs %s", elapsed, label)


# Timed imports below: order and placement are intentional (E402/C0413).
_t = time.perf_counter()
from ..config.utils import read_last_api  # noqa: E402

_record("..config.utils", time.perf_counter() - _t)

_t = time.perf_counter()
from ..__version__ import __version__  # noqa: E402

_record("..__version__", time.perf_counter() - _t)

_total = time.perf_counter() - _t0_main
_init_timings.append(("(total imports)", _total))
logger.debug("%.3fs (total imports)", _total)


def log_init_timings() -> None:
    """Emit init timing debug lines after setup_logger(debug) in app_cmd."""
    for label, elapsed in _init_timings:
        logger.debug("%.3fs %s", elapsed, label)


class LazyGroup(click.Group):
    """Click group that supports lazy loading of subcommands."""

    def __init__(self, *args, lazy_subcommands=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.lazy_subcommands = lazy_subcommands or {}

    def list_commands(self, ctx):
        """Return all command names (both eager and lazy)."""
        base = super().list_commands(ctx)
        return sorted(set(base) | set(self.lazy_subcommands.keys()))

    def get_command(self, ctx, cmd_name):
        """Get command, loading lazily if needed."""
        # Try eager commands first
        cmd = super().get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd

        # Try lazy commands
        if cmd_name in self.lazy_subcommands:
            module_path, attr_name, label = self.lazy_subcommands[cmd_name]
            _t = time.perf_counter()
            try:
                module = __import__(module_path, fromlist=[attr_name])
                cmd = getattr(module, attr_name)
                _record(label, time.perf_counter() - _t)
                # Cache for next time
                self.add_command(cmd, cmd_name)
                return cmd
            except Exception as e:
                logger.error(f"Failed to load command '{cmd_name}': {e}")
                return None

        return None


@click.group(
    cls=LazyGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
    lazy_subcommands={
        "app": ("copaw.cli.app_cmd", "app_cmd", ".app_cmd"),
        "channels": (
            "copaw.cli.channels_cmd",
            "channels_group",
            ".channels_cmd",
        ),
        "channel": (
            "copaw.cli.channels_cmd",
            "channels_group",
            ".channels_cmd",
        ),
        "daemon": ("copaw.cli.daemon_cmd", "daemon_group", ".daemon_cmd"),
        "chats": ("copaw.cli.chats_cmd", "chats_group", ".chats_cmd"),
        "chat": ("copaw.cli.chats_cmd", "chats_group", ".chats_cmd"),
        "clean": ("copaw.cli.clean_cmd", "clean_cmd", ".clean_cmd"),
        "cron": ("copaw.cli.cron_cmd", "cron_group", ".cron_cmd"),
        "env": ("copaw.cli.env_cmd", "env_group", ".env_cmd"),
        "init": ("copaw.cli.init_cmd", "init_cmd", ".init_cmd"),
        "models": (
            "copaw.cli.providers_cmd",
            "models_group",
            ".providers_cmd",
        ),
        "skills": ("copaw.cli.skills_cmd", "skills_group", ".skills_cmd"),
        "uninstall": (
            "copaw.cli.uninstall_cmd",
            "uninstall_cmd",
            ".uninstall_cmd",
        ),
        "desktop": ("copaw.cli.desktop_cmd", "desktop_cmd", ".desktop_cmd"),
        "update": ("copaw.cli.update_cmd", "update_cmd", ".update_cmd"),
        "shutdown": (
            "copaw.cli.shutdown_cmd",
            "shutdown_cmd",
            ".shutdown_cmd",
        ),
        "auth": ("copaw.cli.auth_cmd", "auth_group", ".auth_cmd"),
        "agents": ("copaw.cli.agents_cmd", "agents_group", ".agents_cmd"),
        "agent": ("copaw.cli.agents_cmd", "agents_group", ".agents_cmd"),
    },
)
@click.version_option(version=__version__, prog_name="CoPaw")
@click.option("--host", default=None, help="API Host")
@click.option(
    "--port",
    default=None,
    type=int,
    help="API Port",
)
@click.pass_context
def cli(ctx: click.Context, host: str | None, port: int | None) -> None:
    """CoPaw CLI."""
    # default from last run if not provided
    last = read_last_api()
    if host is None or port is None:
        if last:
            host = host or last[0]
            port = port or last[1]

    # final fallback
    host = host or "127.0.0.1"
    port = port or 8088

    ctx.ensure_object(dict)
    ctx.obj["host"] = host
    ctx.obj["port"] = port
