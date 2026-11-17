# -*- coding: utf-8 -*-
"""In-memory harness declarations; enumeration never constructs a backend."""

# Registry entries and their host own the same private declaration state.
# pylint: disable=protected-access

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Callable

from ...plugins.errors import SDKError, StaleContextError
from ...plugins.harnesses import HarnessCapabilities, HarnessSpec
from ...plugins.resources import Registration, ResourceOwner
from ...plugins.activity import PluginBusyError
from ...plugins.tools import ConfigField


@dataclass(frozen=True)
class BackendDescriptor:
    id: str
    label: str
    plugin_id: str
    capabilities: HarnessCapabilities | None = None
    registered: bool = False
    status: str = "disabled"
    config_fields: tuple[ConfigField, ...] = ()


@dataclass
class _BackendRegistration:
    owner: ResourceOwner
    spec: HarnessSpec
    _registry: BackendRegistry = field(repr=False)
    _guard: Callable[[], None] | None = field(default=None, repr=False)
    _context: object = field(default=None, repr=False)
    _runtimes: set = field(default_factory=set, repr=False)
    _admitted: bool = True

    def assert_active(self):
        self._registry._validate(self)


class BackendRegistry:
    """Own each declaration by plugin generation and context identity."""

    def __init__(
        self,
        manifests: Callable[[], dict] | None = None,
        states: Callable[[], dict] | None = None,
    ):
        self._entries: dict[str, _BackendRegistration] = {}
        self._manifests = manifests or dict
        self._states = states or dict

    def register(
        self,
        owner: ResourceOwner,
        spec: HarnessSpec,
    ) -> Registration:
        occupant = self._entries.get(spec.id)
        if occupant is not None:
            raise SDKError(
                f"Harness {spec.id!r} is owned by plugin "
                f"{occupant.owner.plugin_id!r}",
            )
        entry = _BackendRegistration(owner, spec, self)
        self._entries[spec.id] = entry

        async def release():
            if self._entries.get(spec.id) is entry:
                if entry._context is not None:
                    pending = entry._context._instance.activity._pending()
                    if pending:
                        raise PluginBusyError(owner.plugin_id, len(pending))
                entry._admitted = False
                for runtime in tuple(entry._runtimes):
                    await runtime._close_entry(entry)
                del self._entries[spec.id]

        return Registration(
            release,
            owner=owner,
            description=f"harness:{spec.id}",
            _bounded=False,
        )

    def _bind_owner(
        self,
        owner: ResourceOwner,
        guard: Callable[[], None],
        context=None,
    ):
        for entry in self._entries.values():
            if entry.owner == owner:
                entry._guard = guard
                entry._context = context

    def _validate(self, entry, *, owner: ResourceOwner | None = None):
        if (
            not entry._admitted
            or self._entries.get(entry.spec.id) is not entry
        ):
            raise StaleContextError(
                f"Harness {entry.spec.id!r} has been released",
            )
        if owner is not None and entry.owner != owner:
            raise StaleContextError(
                f"Harness {entry.spec.id!r} owner has been replaced",
            )
        if entry._context is None or entry._guard is None:
            raise StaleContextError(
                f"Harness {entry.spec.id!r} context is not bound",
            )
        resources = getattr(entry._context, "resources", None)
        if getattr(resources, "owner", None) != entry.owner:
            raise StaleContextError(
                f"Harness {entry.spec.id!r} context owner does not match",
            )
        entry._guard()

    def require(
        self,
        backend_id: str,
        *,
        owner: ResourceOwner | None = None,
    ) -> _BackendRegistration:
        entry = self._entries.get(backend_id)
        if entry is None:
            raise SDKError(
                f"backend_unavailable: Backend {backend_id!r} is unavailable",
            )
        self._validate(entry, owner=owner)
        return entry

    def _descriptor(self, backend_id, label, plugin_id, entry=None):
        status = "disabled"
        if entry is not None:
            try:
                self._validate(entry)
                status = "available"
            except SDKError:
                instance = getattr(entry._context, "_instance", None)
                if instance is not None and instance.state.value == "failed":
                    status = "failed"
        if status == "disabled" and self._states().get(plugin_id) == "failed":
            status = "failed"
        return BackendDescriptor(
            id=backend_id,
            label=label,
            plugin_id=plugin_id,
            capabilities=(
                deepcopy(entry.spec.capabilities)
                if entry is not None
                else None
            ),
            registered=entry is not None,
            status=status,
            config_fields=(
                deepcopy(entry.spec.config_fields) if entry is not None else ()
            ),
        )

    def describe(
        self,
        backend_id: str,
        *,
        plugin_id: str | None = None,
    ) -> BackendDescriptor | None:
        entry = self._entries.get(backend_id)
        if entry is not None and (
            plugin_id is None or entry.owner.plugin_id == plugin_id
        ):
            return self._descriptor(
                entry.spec.id,
                entry.spec.label,
                entry.owner.plugin_id,
                entry,
            )
        for declared_plugin, manifest in self._manifests().items():
            if plugin_id is not None and declared_plugin != plugin_id:
                continue
            declarations = (manifest.get("meta") or {}).get("harnesses")
            if not isinstance(declarations, list):
                continue
            for declared in declarations:
                if (
                    isinstance(declared, dict)
                    and declared.get("id") == backend_id
                ):
                    return self._descriptor(
                        backend_id,
                        declared.get("label", backend_id),
                        declared_plugin,
                    )
        return None

    def descriptors(self) -> tuple[BackendDescriptor, ...]:
        rows = {
            entry.spec.id: self._descriptor(
                entry.spec.id,
                entry.spec.label,
                entry.owner.plugin_id,
                entry,
            )
            for entry in self._entries.values()
        }
        for plugin_id, manifest in self._manifests().items():
            declarations = (manifest.get("meta") or {}).get("harnesses")
            if not isinstance(declarations, list):
                continue
            for declared in declarations:
                if not isinstance(declared, dict) or not isinstance(
                    declared.get("id"),
                    str,
                ):
                    continue
                if declared["id"] not in rows:
                    rows[declared["id"]] = self._descriptor(
                        declared["id"],
                        declared.get("label", declared["id"]),
                        plugin_id,
                    )
        return tuple(rows[key] for key in sorted(rows))

    def unregister_owner(self, owner: ResourceOwner) -> None:
        self._entries = {
            key: entry
            for key, entry in self._entries.items()
            if entry.owner != owner
        }

    def validate_manifest(self, owner: ResourceOwner, manifest: dict) -> None:
        declared = (manifest.get("meta") or {}).get("harnesses")
        if declared is None:
            return
        if not isinstance(declared, list) or not all(
            isinstance(row, dict) and isinstance(row.get("id"), str)
            for row in declared
        ):
            raise SDKError("meta.harnesses must declare harness IDs")
        expected = {row["id"] for row in declared}
        actual = {
            entry.spec.id
            for entry in self._entries.values()
            if entry.owner == owner
        }
        if len(expected) != len(declared) or expected != actual:
            raise SDKError(
                "Harness registrations do not match manifest for "
                f"{owner.plugin_id!r}: declared={sorted(expected)}, "
                f"registered={sorted(actual)}",
            )
