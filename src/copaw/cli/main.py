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

_t = time.perf_counter()
from .app_cmd import app_cmd  # noqa: E402

_record(".app_cmd", time.perf_counter() - _t)

_t = time.perf_counter()
from .channels_cmd import channels_group  # noqa: E402

_record(".channels_cmd", time.perf_counter() - _t)

_t = time.perf_counter()
from .chats_cmd import chats_group  # noqa: E402

_record(".chats_cmd", time.perf_counter() - _t)

_t = time.perf_counter()
from .daemon_cmd import daemon_group  # noqa: E402

_record(".daemon_cmd", time.perf_counter() - _t)

_t = time.perf_counter()
from .clean_cmd import clean_cmd  # noqa: E402

_record(".clean_cmd", time.perf_counter() - _t)

_t = time.perf_counter()
from .cron_cmd import cron_group  # noqa: E402

_record(".cron_cmd", time.perf_counter() - _t)

_t = time.perf_counter()
from .env_cmd import env_group  # noqa: E402

_record(".env_cmd", time.perf_counter() - _t)

_t = time.perf_counter()
from .init_cmd import init_cmd  # noqa: E402

_record(".init_cmd", time.perf_counter() - _t)

_t = time.perf_counter()
from .providers_cmd import models_group  # noqa: E402

_record(".providers_cmd", time.perf_counter() - _t)

_t = time.perf_counter()
from .skills_cmd import skills_group  # noqa: E402

_record(".skills_cmd", time.perf_counter() - _t)

_t = time.perf_counter()
from .uninstall_cmd import uninstall_cmd  # noqa: E402

_record(".uninstall_cmd", time.perf_counter() - _t)

_t = time.perf_counter()
from .desktop_cmd import desktop_cmd  # noqa: E402

_record(".desktop_cmd", time.perf_counter() - _t)

_t = time.perf_counter()
from .update_cmd import update_cmd  # noqa: E402

_record(".update_cmd", time.perf_counter() - _t)

_t = time.perf_counter()
from .shutdown_cmd import shutdown_cmd  # noqa: E402

_record(".shutdown_cmd", time.perf_counter() - _t)

_t = time.perf_counter()
from .auth_cmd import auth_group  # noqa: E402

_record(".auth_cmd", time.perf_counter() - _t)

_total = time.perf_counter() - _t0_main
_init_timings.append(("(total imports)", _total))
logger.debug("%.3fs (total imports)", _total)


def log_init_timings() -> None:
    """Emit init timing debug lines after setup_logger(debug) in app_cmd."""
    for label, elapsed in _init_timings:
        logger.debug("%.3fs %s", elapsed, label)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
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


cli.add_command(app_cmd)
cli.add_command(channels_group)
cli.add_command(daemon_group)
cli.add_command(chats_group)
cli.add_command(clean_cmd)
cli.add_command(cron_group)
cli.add_command(env_group)
cli.add_command(init_cmd)
cli.add_command(models_group)
cli.add_command(skills_group)
cli.add_command(uninstall_cmd)
cli.add_command(desktop_cmd)
cli.add_command(update_cmd)
cli.add_command(shutdown_cmd)
cli.add_command(auth_group)
