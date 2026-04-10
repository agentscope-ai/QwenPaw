# -*- coding: utf-8 -*-
"""Extensible hooks for `copaw doctor` (entry points + programmatic registration).

Plugins can expose a setuptools entry point in group ``copaw.doctor``::

    [project.entry-points."copaw.doctor"]
    my_pkg = "my_pkg.doctor:doctor_notes"

The callable must accept :class:`DoctorRunContext` and return a list of
informational strings (empty if nothing to report).

Alternatively, call :func:`register_doctor_contribution` at import time
(e.g. from a channel package).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib.metadata import entry_points as metadata_entry_points
from typing import TYPE_CHECKING, Any, Callable

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
    """Register a doctor extension (id should be unique, e.g. ``myplugin.cron``)."""
    _manual[contrib_id] = fn


def reset_doctor_registry_state() -> None:
    """Clear manual registrations and entry-point cache (for tests)."""
    _manual.clear()
    global _eps_cached
    _eps_cached = None


def _load_entry_point_functions() -> list[tuple[str, DoctorNotesFn]]:
    out: list[tuple[str, DoctorNotesFn]] = []
    try:
        eps = metadata_entry_points(group="copaw.doctor")
    except TypeError:
        eps = metadata_entry_points().select(group="copaw.doctor")
    for ep in eps:
        try:
            fn = ep.load()
        except Exception:
            logger.exception('copaw.doctor entry point "%s" failed to load', ep.name)
            continue
        if not callable(fn):
            logger.warning(
                'copaw.doctor entry point "%s" is not callable; skipped',
                ep.name,
            )
            continue
        out.append((ep.name, fn))
    return out


def _resolved_eps() -> list[tuple[str, DoctorNotesFn]]:
    global _eps_cached
    if _eps_cached is None:
        _eps_cached = _load_entry_point_functions()
    return _eps_cached


def run_extension_contributions(ctx: DoctorRunContext) -> list[tuple[str, list[str]]]:
    """Run manual registrations first (sorted by id), then setuptools entry points."""
    results: list[tuple[str, list[str]]] = []

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

    return results
