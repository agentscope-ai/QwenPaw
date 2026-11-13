# -*- coding: utf-8 -*-
"""Stable lifecycle outcomes containing only public value types."""

from dataclasses import dataclass


@dataclass(frozen=True)
class InstallResult:
    plugin_id: str
    ok: bool
    status: str
    version: str
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class EnableResult:
    plugin_id: str
    enabled: bool
    ok: bool
    errors: tuple[str, ...] = ()
    quiescent: bool = True
    needs_restart: bool = False


@dataclass(frozen=True)
class UnloadResult:
    plugin_id: str
    mode: str
    clean: bool
    errors: tuple[str, ...]
    leftovers: tuple[str, ...]
    workspace_leaks: tuple[str, ...]
    quiescent: bool
    needs_restart: bool


@dataclass(frozen=True)
class ReloadResult:
    plugin_id: str
    ok: bool
    unchanged: bool
    errors: tuple[str, ...]
    generation: int
    needs_restart: bool


@dataclass(frozen=True)
class ConfigUpdateResult:
    plugin_id: str
    ok: bool
    unchanged: bool
    errors: tuple[str, ...]
    requires_confirmation: bool
    conflict: bool
    legacy_hooks: tuple[str, ...]
    needs_restart: bool
    quiescent: bool
