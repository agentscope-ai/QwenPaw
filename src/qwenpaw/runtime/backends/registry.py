# -*- coding: utf-8 -*-
"""In-memory harness declarations; enumeration never constructs a backend."""

# Registry entries and their host own the same private declaration state.
# pylint: disable=protected-access

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ...plugins.errors import SDKError, StaleContextError
from ...plugins.harnesses import HarnessCapabilities, HarnessSpec
from ...plugins.resources import Registration, ResourceOwner
from ...plugins.activity import PluginBusyError


@dataclass(frozen=True)
class BackendDescriptor:
    id: str
    label: str
    plugin_id: str
    capabilities: HarnessCapabilities | None = None
    registered: bool = False


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
        if (
            not self._admitted
            or self._registry._entries.get(self.spec.id) is not self
        ):
            raise StaleContextError(
                f"Harness {self.spec.id!r} has been released",
            )
        if self._guard is not None:
            self._guard()


class BackendRegistry:
    """Own each declaration by plugin generation and context identity."""

    def __init__(self, manifests: Callable[[], dict] | None = None):
        self._entries: dict[str, _BackendRegistration] = {}
        self._manifests = manifests or dict

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

    def get(self, backend_id: str) -> _BackendRegistration | None:
        entry = self._entries.get(backend_id)
        if entry is not None:
            entry.assert_active()
        return entry

    def descriptors(self) -> tuple[BackendDescriptor, ...]:
        rows = {
            entry.spec.id: BackendDescriptor(
                entry.spec.id,
                entry.spec.label,
                entry.owner.plugin_id,
                entry.spec.capabilities,
                True,
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
                rows.setdefault(
                    declared["id"],
                    BackendDescriptor(
                        declared["id"],
                        declared.get("label", declared["id"]),
                        plugin_id,
                    ),
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
