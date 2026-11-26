# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Owned definitions and revocable host access through the teardown ledger."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from .errors import SDKError, StaleContextError
from .extensions import ExtensionPoint
from .dependency_requirements import resolve_optional_dependencies
from .resources import Registration


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
class _ContributionReference:
    """Internal reference whose admission is revoked with its registration."""

    table: dict
    key: tuple
    entry: _Contribution
    kind: str

    @property
    def plugin_id(self):
        return self.entry.context.plugin_id

    @property
    def id(self):
        return self.entry.spec.id

    def _guard(self):
        if self.table.get(self.key) is not self.entry:
            raise StaleContextError(
                f"{self.kind} registration has been released",
            )
        self.entry.context._guard()

    async def admit(self):
        """Check prerequisites before the consumer imports or calls code."""
        self._guard()
        await self.entry.admit()

    async def activate(self):
        """Prepare runtime hooks for invocation without installation effects."""
        sdk = self.entry.context
        loader = sdk._loader
        async with loader.plugin_lifecycle(self.plugin_id):
            self._guard()
            instance = sdk._instance
            if not instance.activated:
                await loader.run_plugin_startup_hooks(
                    self.plugin_id,
                    include_installation=False,
                )
                instance.activated = True

    @property
    def spec(self):
        """Read an admitted definition for synchronous implementation building."""
        self._guard()
        if self.entry.requires and not self.entry.admitted:
            raise SDKError(f"{self.kind} dependencies have not been admitted")
        return self.entry.spec

    @contextmanager
    def invocation(self):
        spec = self.spec
        with self.entry.context._instance.activity.invocation():
            yield spec


def get_cli(registry, plugin_id, contribution_id):
    """Resolve a registered command without importing its implementation."""
    key = (plugin_id, contribution_id)
    entry = registry.cli_contributions.get(key)
    if entry is None:
        return None
    return _ContributionReference(
        registry.cli_contributions,
        key,
        entry,
        "CLI",
    )


def get_extensions(registry, point, plugin_id=None):
    """Snapshot host references without loading or activating any provider."""
    point = _resolve_point(registry, point)
    return tuple(
        _ContributionReference(registry.extensions, key, entry, "Extension")
        for key, entry in registry.extensions.items()
        if key[0] == point.id and (plugin_id is None or key[1] == plugin_id)
    )
