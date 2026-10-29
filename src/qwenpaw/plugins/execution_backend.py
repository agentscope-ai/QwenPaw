# -*- coding: utf-8 -*-
"""Host-selected execution contracts for one resolved plugin source version."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
import hashlib
import json
from typing import TYPE_CHECKING, Callable, Mapping, Protocol

from .architecture import PluginManifest, PluginRecord, PluginType

if TYPE_CHECKING:
    from .execution.dependencies import DependencySnapshot


@dataclass(frozen=True)
class PluginDescription:
    """Static source metadata; only its backend interprets ``payload``."""

    manifest: PluginManifest
    source_path: Path
    requirements_path: Path | None
    payload: object
    source_identity: object | None = None
    requirements: tuple[str, ...] | None = None

    def __post_init__(self):
        if self.requirements is None:
            from .dependency_gate import parse_requirements_file

            parsed = (
                parse_requirements_file(self.requirements_path)
                if self.requirements_path is not None
                else None
            )
            object.__setattr__(
                self,
                "requirements",
                tuple(
                    [str(item) for item in parsed.requirements]
                    + parsed.unsupported,
                )
                if parsed is not None
                else (),
            )

    def dependency_declaration(self):
        """Pinned dependency identity, independent of staging path changes."""
        from .dependency_usage import DependencyDeclaration

        revision = self.source_identity
        if revision is None:
            revision = hashlib.sha256(
                json.dumps(
                    [self.manifest.model_dump(mode="json"), self.requirements],
                    sort_keys=True,
                ).encode(),
            ).hexdigest()
        return DependencyDeclaration(
            self.manifest.id,
            str(revision),
            self.requirements,
            None,
        )


@dataclass(frozen=True)
class DefinitionResult:
    """Definition and execution status, before lifecycle registration."""

    definition: object | None
    enabled: bool = True
    status: str = "registered"
    diagnostics: tuple[str, ...] = ()
    dependency_snapshot: object | None = None


@dataclass(frozen=True)
class PreparedDependencyTargets:
    """Coordination hints and a synchronous, I/O-free freshness check."""

    targets: tuple[Path, ...]
    validate: Callable[[], None]


class ExecutionBackend(Protocol):
    """Execution behavior without directory commits or lifecycle ownership.

    Executable admission uses optional async prepare_dependency_targets,
    returning PreparedDependencyTargets. Missing hints never replace the
    required audit_dependencies evidence. Static discovery needs neither hook.
    Optional dependency_environment(description, snapshot) selects host-owned
    installer policy independently of actual consumer audit evidence.
    Optional validate_config_update(description, config) checks eligibility
    without execution before configuration teardown, including disabled rows.
    """

    probe_before_activation: bool
    """Whether explicit activation/configuration needs a separate probe."""

    discover_disabled: bool
    """Whether disabled discovery may safely catalogue a static definition."""

    def registration_scope(
        self,
        description: PluginDescription,
    ) -> AbstractContextManager:
        """Retain execution custody through definition loading and register."""

    def describe(
        self,
        source_path: Path,
        manifest: PluginManifest,
    ) -> PluginDescription:
        """Read static metadata without starting or importing components."""

    async def prepare(
        self,
        description: PluginDescription,
        *,
        allow_install: bool,
        probe: bool,
        wheels: tuple = (),
        owns_dependency_env: bool = True,
    ) -> DependencySnapshot | None:
        """Prepare/probe, optionally returning evidence already produced.

        Final admission always audits under exclusion. Callers needing a
        separate preflight retain that audit before lifecycle/disk changes.
        """

    async def load_definition(
        self,
        description: PluginDescription,
        config: Mapping,
        *,
        saved_definition: object | None = None,
    ) -> DefinitionResult:
        """Obtain a definition without invoking its ``register(api)``."""

    async def before_activate(self, description: PluginDescription) -> None:
        """Check execution prerequisites before lifecycle activation."""

    def validate_update(
        self,
        old: PluginDescription,
        candidate: PluginDescription,
        *,
        in_place: bool,
    ) -> None:
        """Check execution-specific update constraints."""

    def capture_restore_state(self, record: PluginRecord) -> object | None:
        """Capture backend execution state for transaction recovery."""

    def restore_state(self, state: object | None) -> None:
        """Restore previously captured backend execution state."""


@dataclass(frozen=True)
class BackendBinding:
    """A fixed backend and its description for one source version."""

    backend: ExecutionBackend
    description: PluginDescription

    def rebase(self, source_path: Path, manifest: PluginManifest):
        """Rebuild paths with the pinned backend and verify source identity."""
        if manifest != self.description.manifest:
            raise RuntimeError("Plugin manifest changed during transaction")
        # Protocol methods provide signatures, not implementation bodies.
        # pylint: disable=assignment-from-no-return
        description = self.backend.describe(
            Path(source_path),
            manifest.model_copy(deep=True),
        )
        # pylint: enable=assignment-from-no-return
        if (
            self.description.source_identity is not None
            and description.source_identity != self.description.source_identity
        ):
            raise RuntimeError(
                "Plugin source identity changed during transaction",
            )
        return BackendBinding(
            self.backend,
            replace(description, requirements=self.description.requirements),
        )

    def validate_update(self, candidate, *, in_place):
        """Reject backend changes before execution or directory mutation."""
        if self.backend is not candidate.backend:
            for binding in (self, candidate):
                binding.backend.validate_update(
                    binding.description,
                    binding.description,
                    in_place=False,
                )
            raise RuntimeError(
                "Plugin execution backend switching is not supported",
            )
        self.backend.validate_update(
            self.description,
            candidate.description,
            in_place=in_place,
        )

    async def prepare(
        self,
        *,
        allow_install,
        probe,
        wheels=(),
        owns_dependency_env=True,
    ):
        """Pass the optional ownership override only when requested."""
        override = (
            {} if owns_dependency_env else {"owns_dependency_env": False}
        )
        return await self.backend.prepare(
            self.description,
            allow_install=allow_install,
            probe=probe,
            wheels=wheels,
            **override,
        )


class BackendResolver:
    """Select once from entry shape and trusted host-registered adapters."""

    def __init__(self, python_backend: ExecutionBackend):
        self._python_backend = python_backend
        self._descriptors: dict[PluginType, ExecutionBackend] = {}

    def register_descriptor(
        self,
        plugin_type: PluginType,
        backend: ExecutionBackend,
    ) -> None:
        """Register a host adapter without replacing existing choices."""
        plugin_type = PluginType(plugin_type)
        if plugin_type in self._descriptors:
            raise ValueError(
                f"Descriptor backend already registered: {plugin_type.value}",
            )
        self._descriptors[plugin_type] = backend

    def resolve(
        self,
        source_path: Path,
        manifest: PluginManifest,
    ) -> BackendBinding:
        """Describe a snapshot without consulting executable plugin code."""
        manifest = manifest.model_copy(deep=True)
        backend = self._python_backend
        if manifest.entry.descriptor is not None:
            if manifest.entry.backend is not None:
                raise ValueError(
                    "descriptor and backend entries are mutually exclusive",
                )
            try:
                backend = self._descriptors[manifest.plugin_type]
            except KeyError as exc:
                raise ValueError(
                    "No descriptor backend registered for "
                    f"{manifest.plugin_type.value}",
                ) from exc
        return BackendBinding(
            backend,
            backend.describe(Path(source_path), manifest),
        )


def registration_scope(binding: BackendBinding):
    """Default for host adapters predating scoped registration."""
    scope = getattr(binding.backend, "registration_scope", None)
    return scope(binding.description) if scope is not None else nullcontext()


def discovers_disabled(binding: BackendBinding) -> bool:
    """Older adapters keep the conservative disabled-discovery policy."""
    return getattr(binding.backend, "discover_disabled", False)


def probes_before_activation(binding: BackendBinding) -> bool:
    """Legacy Python registration is already its execution check."""
    return getattr(binding.backend, "probe_before_activation", False)
