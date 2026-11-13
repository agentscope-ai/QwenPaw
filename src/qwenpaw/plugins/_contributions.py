# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Owned definitions and revocable host access through the teardown ledger."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .errors import SDKError, StaleContextError
from .extensions import ExtensionPoint
from .dependency_requirements import resolve_optional_dependencies
from .resources import Registration

if TYPE_CHECKING:
    from .registry import PluginRegistry


def _require(context, capability):
    context._guard()
    if capability not in context._api.manifest.get("sdk", {}).get(
        "capabilities",
        (),
    ):
        raise SDKError(f"Missing {capability} capability")


@dataclass
class _Contribution:
    """A definition and its invocation prerequisites, owned by one plugin."""

    context: object
    spec: object
    requires: tuple[str, ...] = ()
    admitted: bool = False

    async def admit(self):
        self.context._guard()
        if self.requires and not self.admitted:
            with self.context._instance.activity.invocation():
                await self.context._loader.admit_contribution(
                    self.context.plugin_id,
                    self.requires,
                )
            self.admitted = True


# TODO: Consider ctx.when(service, callback) registration scopes for live
# plugin-service prerequisites. A scope must own its contributions, coordinate
# in-flight calls on revocation and restore registrations when services return.
# Keep package prerequisites statically discoverable for installation.
def _store(context, spec, table, key, kind, requires):
    if requires:
        _require(context, "dependencies")
    resolve_optional_dependencies(
        context._api.manifest.get("optional_dependencies", {}),
        requires,
    )
    if not isinstance(getattr(spec, "id", None), str) or not spec.id.strip():
        raise SDKError("Contribution ID must not be empty")
    if key in table:
        raise SDKError(f"Duplicate {kind} ID: {spec.id}")
    entry = _Contribution(context, spec, tuple(requires))
    table[key] = entry

    def release():
        if table.get(key) is entry:
            table.pop(key)

    context._instance.record_runtime(f"{kind}:{spec.id}", release, kind=kind)
    return Registration(
        release,
        owner=context.resources.owner,
        description=f"{kind}:{spec.id}",
    )


def register_cli(context, spec):
    from .cli import CliSpec

    _require(context, "cli")
    if not isinstance(spec, CliSpec) or not callable(spec.build):
        raise SDKError("Expected CliSpec with a callable implementation")
    declared = {row["id"]: row for row in context._api.manifest.get("cli", ())}
    if spec.id not in declared:
        raise SDKError(f"Undeclared CLI ID: {spec.id}")
    return _store(
        context,
        spec,
        context._api._registry.cli_contributions,
        (context.plugin_id, spec.id),
        "cli",
        declared[spec.id].get("requires", ()),
    )


def _resolve_point(registry, point):
    if not isinstance(point, ExtensionPoint):
        raise SDKError("Expected ExtensionPoint")
    supported = registry.extension_points.get(point.id)
    if supported is None or supported.spec_type is not point.spec_type:
        raise SDKError(f"Unsupported extension point: {point.id}")
    return supported


def register_extension(context, point, spec):
    _require(context, "extensions")
    registry = context._api._registry
    point = _resolve_point(registry, point)
    if not isinstance(spec, point.spec_type):
        raise SDKError(f"Expected {point.spec_type.__name__} for {point.id}")
    declarations = context._api.manifest.get("extensions", ())
    declared = next(
        (
            item
            for item in declarations
            if item.get("point") == point.id
            and item.get("id") == getattr(spec, "id", None)
        ),
        None,
    )
    if declared is None:
        raise SDKError(f"Undeclared extension contribution: {point.id}")
    return _store(
        context,
        spec,
        registry.extensions,
        (point.id, context.plugin_id, getattr(spec, "id", None)),
        f"extension:{point.id}",
        declared.get("requires", ()),
    )


@dataclass(frozen=True)
class _Extension:
    """Internal reference whose admission is revoked with its registration."""

    registry: PluginRegistry
    key: tuple
    entry: _Contribution

    @property
    def plugin_id(self):
        return self.key[1]

    @property
    def id(self):
        return self.key[2]

    async def admit(self):
        """Check prerequisites before the consumer imports or calls code."""
        if self.registry.extensions.get(self.key) is not self.entry:
            raise StaleContextError("Extension registration has been released")
        await self.entry.admit()

    @contextmanager
    def invocation(self):
        if self.registry.extensions.get(self.key) is not self.entry:
            raise StaleContextError("Extension registration has been released")
        sdk, spec = self.entry.context, self.entry.spec
        sdk._guard()
        if self.entry.requires and not self.entry.admitted:
            raise SDKError("Extension dependencies have not been admitted")
        with sdk._instance.activity.invocation():
            yield spec


def get_extensions(registry, point):
    """Snapshot host references without loading or activating any provider."""
    point = _resolve_point(registry, point)
    return tuple(
        _Extension(registry, key, entry)
        for key, entry in registry.extensions.items()
        if key[0] == point.id
    )
