# -*- coding: utf-8 -*-
"""Run Doctor checks from manual registrations, entry points and SDK plugins.

Manual checks and the qwenpaw.doctor / copaw.doctor entry points receive
DoctorRunContext. Installed SDK contributions receive DoctorContext.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from copy import deepcopy
from dataclasses import dataclass
from functools import partial
from importlib.metadata import entry_points as metadata_entry_points
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import urlsplit

import click
import httpx

from ..plugins.doctor import DOCTOR, DoctorContext, DoctorResult
from ..plugins.errors import SDKError
from ..utils.io_utils import run_sync_io
from ..utils.runtime_api import async_api_client

if TYPE_CHECKING:
    from ..config.config import Config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DoctorRunContext:
    """Context passed to doctor extension callables."""

    cfg: "Config"
    raw_cfg: dict[str, Any] | None
    cli_base_url: str
    timeout: float
    deep: bool


DoctorNotesFn = Callable[[DoctorRunContext], list[str]]

_manual: dict[str, DoctorNotesFn] = {}
_eps_cached: list[tuple[str, DoctorNotesFn]] | None = None


def register_doctor_contribution(contrib_id: str, fn: DoctorNotesFn) -> None:
    """Register an extension (id should be unique, e.g. ``myplugin.cron``)."""
    _manual[contrib_id] = fn


def reset_doctor_registry_state() -> None:
    """Clear manual registrations and entry-point cache (for tests)."""
    _manual.clear()
    global _eps_cached
    _eps_cached = None


def _entry_points_for_group(group: str):
    try:
        return metadata_entry_points(group=group)
    except TypeError:
        return metadata_entry_points().select(group=group)


def _load_entry_point_functions() -> list[tuple[str, DoctorNotesFn]]:
    out: list[tuple[str, DoctorNotesFn]] = []
    seen: set[str] = set()
    for group in ("qwenpaw.doctor", "copaw.doctor"):
        for ep in _entry_points_for_group(group):
            if ep.name in seen:
                continue
            try:
                fn = ep.load()
            except Exception:
                logger.exception(
                    '%s entry point "%s" failed to load',
                    group,
                    ep.name,
                )
                continue
            if not callable(fn):
                logger.warning(
                    '%s entry point "%s" is not callable; skipped',
                    group,
                    ep.name,
                )
                continue
            seen.add(ep.name)
            out.append((ep.name, fn))
    return out


def _resolved_eps() -> list[tuple[str, DoctorNotesFn]]:
    global _eps_cached
    if _eps_cached is None:
        _eps_cached = _load_entry_point_functions()
    return _eps_cached


async def _get_runtime(context, path):
    target = urlsplit(path)
    if target.scheme or target.netloc or path.startswith("/"):
        raise SDKError("Runtime API path must be relative")
    try:
        async with async_api_client(
            context.cli_base_url.rstrip("/") + "/api/",
        ) as client:
            response = await client.get(path, timeout=context.timeout)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SDKError(f"Runtime API read failed: {exc}") from exc


async def _run_doctor_check(contribution, call):
    await contribution.admit()
    with contribution.invocation() as spec:
        if inspect.iscoroutinefunction(spec.check):
            notes = await spec.check(call)
        else:
            notes = await run_sync_io(spec.check, call)
        if inspect.isawaitable(notes):
            notes = await notes
        if not isinstance(notes, list) or not all(
            isinstance(note, (str, DoctorResult)) for note in notes
        ):
            raise TypeError(
                "Diagnostic must return notes or DoctorResult values",
            )
        return notes


def doctor_contributions(context):
    """Report CLI discovery issues and run each enabled plugin's checks."""
    from .doctor_checks import selected_provider_ids
    from .plugin_cli import catalog_for, missing_cli_root_messages
    from .plugin_session import session_for

    ctx = click.get_current_context(silent=True)
    if ctx is None:
        return []
    catalog = catalog_for(ctx)
    result = [
        (issue.source_path.name, [f"(discovery error) {issue.message}"])
        for issue in catalog.issues
    ]
    for message in missing_cli_root_messages(ctx, catalog):
        result.append(("cli", [message]))
    for path, mounts in catalog.mounts.items():
        if len(mounts) > 1:
            result.append(("cli", [f"CLI path conflict: {' '.join(path)}"]))

    selected = None
    for manifest, source in catalog.enabled_plugins:
        if not manifest.declares_extension(DOCTOR.id):
            continue
        session = session_for(ctx)
        try:
            session.load_registration(manifest, source)
            if selected is None:
                selected = session.run(
                    run_sync_io(selected_provider_ids, context.cfg),
                )
            checks = session.loader.registry.get_extensions(
                DOCTOR,
                plugin_id=manifest.id,
            )
        except (click.Abort, click.exceptions.Exit):
            raise
        except Exception as exc:  # noqa: BLE001
            reason = str(exc) or type(exc).__name__
            result.append((manifest.id, [f"(extension error) {reason}"]))
            continue
        for check in checks:
            try:
                call = DoctorContext(
                    config=context.cfg.model_dump(mode="json")
                    if context.cfg is not None
                    else None,
                    raw_config=deepcopy(context.raw_cfg),
                    base_url=context.cli_base_url,
                    timeout=context.timeout,
                    deep=context.deep,
                    _get_runtime=partial(_get_runtime, context),
                    selected_providers=selected,
                )
                notes = session.run(
                    asyncio.wait_for(
                        _run_doctor_check(check, call),
                        timeout=call.timeout,
                    ),
                )
            except (click.Abort, click.exceptions.Exit):
                raise
            except Exception as exc:  # noqa: BLE001
                reason = str(exc) or type(exc).__name__
                notes = [f"(extension error) {reason}"]
            result.append((f"{manifest.id}:{check.id}", notes))
    return result


def run_extension_contributions(
    ctx: DoctorRunContext,
) -> list[tuple[str, list[str | DoctorResult]]]:
    """Run manual checks, entry points, then installed SDK checks."""
    results: list[tuple[str, list[str | DoctorResult]]] = []
    lines: list[str | DoctorResult]

    for cid in sorted(_manual):
        fn = _manual[cid]
        try:
            raw = fn(ctx)
            lines = list(raw) if raw is not None else []
        except Exception as exc:  # pylint: disable=broad-exception-caught
            lines = [f"(extension error) {exc}"]
        results.append((cid, lines))

    for name, fn in sorted(_resolved_eps(), key=lambda x: x[0]):
        try:
            raw = fn(ctx)
            lines = list(raw) if raw is not None else []
        except Exception as exc:  # pylint: disable=broad-exception-caught
            lines = [f"(entry point {name!r} error) {exc}"]
        results.append((f"ep:{name}", lines))

    return results + doctor_contributions(ctx)
