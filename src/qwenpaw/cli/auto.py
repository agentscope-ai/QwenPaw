# -*- coding: utf-8 -*-
"""Auto-generated CLI subcommands from ``@api_action``.

``auto_group`` is a :class:`_LazyAutoGroup` registered lazily in
``cli/main.py``.  On first access (``list_commands`` / ``get_command``)
it imports every :class:`ManagerBase` subclass listed in
``_MANAGER_CLASSES``, reads their ``_api_actions`` class attributes,
and registers a Click subcommand for each action whose ``methods``
include ``"cli"``.

Unlike the HTTP and slash generators which run inside the server
process during FastAPI lifespan, the CLI runs in a **separate
process** that has no access to the ``ManagerRegistry`` or any
live ``Manager`` instance.  The generated subcommands therefore
work as HTTP clients — they send requests to the running server
using the ``http_path`` and ``http_method`` from ``ApiActionSpec``.

"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

import click

from .http import client, print_json

logger = logging.getLogger(__name__)

_MANAGER_CLASSES: list[str] = [
    "qwenpaw.app.crons.manager:CronManager",
]


def _ensure_daemon_alive(base_url: str) -> None:
    """HEAD ``/healthz`` and abort if the daemon is not reachable."""
    try:
        with client(base_url) as c:
            r = c.head("/version")
            r.raise_for_status()
    except Exception:
        click.echo(
            f"Error: QwenPaw daemon is not reachable at {base_url}. "
            "Start it with `qwenpaw app` first.",
            err=True,
        )
        sys.exit(2)


def _base_url(ctx: click.Context, base_url: str | None) -> str:
    if base_url:
        return base_url.rstrip("/")
    host = (ctx.obj or {}).get("host", "127.0.0.1")
    port = (ctx.obj or {}).get("port", 8088)
    return f"http://{host}:{port}"


def _add_command(
    group: click.Group,
    cmd_name: str,
    help_text: str,
    spec: Any,
    prefix: str,
) -> None:
    """Register one Click subcommand for *spec*."""

    @group.command(cmd_name, help=help_text)
    @click.option(
        "--base-url",
        default=None,
        help="Override API URL.",
    )
    @click.option(
        "--data",
        default=None,
        help="JSON body for POST.",
    )
    @click.option(
        "--path-params",
        default=None,
        help='JSON mapping for path placeholders, e.g. \'{"job_id":"abc"}\'.',
    )
    @click.pass_context
    def _cmd(
        ctx: click.Context,
        base_url: str | None,
        data: str | None,
        path_params: str | None,
        _spec: Any = spec,
        _prefix: str = prefix,
    ) -> None:
        base = _base_url(ctx, base_url)
        _ensure_daemon_alive(base)
        path = _spec.http_path or f"/{_prefix}/{_spec.name}"
        if path_params:
            try:
                params = json.loads(path_params)
            except json.JSONDecodeError as exc:
                raise click.UsageError(
                    f"--path-params must be valid JSON: {exc}",
                ) from exc
            try:
                path = path.format(**params)
            except KeyError as exc:
                raise click.UsageError(
                    f"Missing path parameter: {exc}",
                ) from exc
        elif "{" in path:
            raise click.UsageError(
                f"Path {path!r} has placeholders; "
                f"provide --path-params JSON mapping.",
            )
        with client(base) as c:
            if _spec.http_method.upper() == "GET":
                r = c.get(path)
            else:
                body = json.loads(data) if data else {}
                r = c.request(
                    _spec.http_method.upper(),
                    path,
                    json=body,
                )
            r.raise_for_status()
            print_json(r.json())


def _load_manager_classes() -> list[type]:
    """Import and return all ManagerBase subclasses in _MANAGER_CLASSES."""
    classes: list[type] = []
    for dotted in _MANAGER_CLASSES:
        module_path, cls_name = dotted.rsplit(":", 1)
        try:
            mod = __import__(module_path, fromlist=[cls_name])
            classes.append(getattr(mod, cls_name))
        except Exception:
            logger.debug(
                "Failed to load manager class %s",
                dotted,
                exc_info=True,
            )
    return classes


class _LazyAutoGroup(click.Group):
    """Click group that populates subcommands on first access.

    Scans ``_MANAGER_CLASSES`` for ``@api_action(methods={..,"cli"})``
    specs and registers a Click subcommand for each one.
    """

    _loaded: bool = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        for mgr_cls in _load_manager_classes():
            prefix = getattr(mgr_cls, "endpoint_prefix", "") or ""
            for spec in getattr(mgr_cls, "_api_actions", []):
                if "cli" not in spec.methods:
                    continue
                cmd_name = spec.cli_command or (
                    f"{prefix}-{spec.name}" if prefix else spec.name
                )
                help_text = f"Auto: {mgr_cls.__name__}.{spec.name}"
                _add_command(self, cmd_name, help_text, spec, prefix)

    def list_commands(self, ctx: click.Context) -> list[str]:
        self._ensure_loaded()
        return super().list_commands(ctx)

    def get_command(
        self,
        ctx: click.Context,
        cmd_name: str,
    ) -> click.Command | None:
        self._ensure_loaded()
        return super().get_command(ctx, cmd_name)


@click.group("auto", cls=_LazyAutoGroup)
def auto_group() -> None:
    """Auto-generated commands from @api_action declarations."""


__all__ = ["auto_group"]
