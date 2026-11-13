# -*- coding: utf-8 -*-
"""Host-selected execution contracts for one resolved plugin source version."""

from __future__ import annotations

from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
import hashlib
import json
from typing import TYPE_CHECKING, Callable, Mapping, Protocol

from .architecture import PluginManifest, PluginRecord, PluginType

if TYPE_CHECKING:
    from .execution.dependencies import (
        DependencyReadEvidence,
        DependencySnapshot,
    )


@dataclass(frozen=True)
class PluginDescription:
    """Static source metadata; only its backend interprets ``payload``."""

    manifest: PluginManifest
    source_path: Path
    requirements_path: Path | None
    payload: object
    source_identity: object | None = None
    requirements: tuple[str, ...] | None = None
    required_extras: tuple[str, ...] = ()

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
                (
                    tuple(
                        [str(item) for item in parsed.requirements]
                        + parsed.unsupported,
                    )
                    if parsed is not None
                    else ()
                ),
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
    returning PreparedDependencyTargets. admit_existing owns read eligibility;
    audit_dependencies remains complete write evidence. Static discovery
    needs neither hook.
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
    ) -> DependencySnapshot | DependencyReadEvidence | None:
        """Prepare/probe, optionally returning evidence already produced.

        Final admission calls admit_existing under exclusion. A separate
        preflight retains read eligibility before lifecycle/disk changes.
        """

    async def admit_existing(
        self,
        description,
        *,
        usage,
        token,
        snapshot=None,
    ) -> DependencySnapshot | DependencyReadEvidence | None:
        """Admit checked reads; strong snapshots remain exclusive to audits."""

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
    """A runtime backend and optional public registration for one source.

    Both definitions belong to the same plugin lifecycle. Their dependency
    admissions stay separate so a public command need not start its driver.
    """

    backend: ExecutionBackend
    description: PluginDescription
    registration: BackendBinding | None = None

    def refresh(self, source_path: Path, manifest: PluginManifest):
        """Describe current files while retaining the selected backend."""
        return BackendBinding(
            self.backend,
            self.backend.describe(
                Path(source_path),
                manifest.model_copy(deep=True),
            ),
            self.registration.refresh(source_path, manifest)
            if self.registration is not None and manifest.entry.backend
            else None,
        )

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
            self.registration.rebase(source_path, manifest)
            if self.registration is not None
            else None,
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
        if (
            self.registration is not None
            and candidate.registration is not None
        ):
            self.registration.validate_update(
                candidate.registration,
                in_place=in_place,
            )

    def capture_restore_state(self, record):
        return (
            self.backend.capture_restore_state(record),
            self.registration.capture_restore_state(record)
            if self.registration is not None
            else None,
        )

    def restore_state(self, state):
        if state is None:
            return
        runtime, registration = state
        self.backend.restore_state(runtime)
        if self.registration is not None:
            self.registration.restore_state(registration)

    async def load_definition(self, config, saved_definition=None):
        """Keep public registration alongside an executable runtime definition."""
        from .settings import is_plugin_enabled

        saved = saved_definition
        if isinstance(saved, PluginDefinition):
            saved = saved.runtime_definition
        result = await self.backend.load_definition(
            self.description,
            config,
            saved_definition=saved,
        )
        if (
            self.registration is not None
            and result.definition is not None
            and is_plugin_enabled(config)
        ):
            result = replace(
                result,
                definition=PluginDefinition(
                    result.definition,
                    self.registration,
                    saved_definition.public_definition
                    if isinstance(saved_definition, PluginDefinition)
                    else None,
                ),
            )
        return result

    async def admit_existing(self, *, usage, token, snapshot=None):
        return await self.backend.admit_existing(
            self.description,
            usage=usage,
            token=token,
            snapshot=snapshot,
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


@dataclass
class PluginDefinition:
    """Runtime and public definitions registered under one plugin owner.

    Public registration stays lightweight; authored call handlers import
    their runtime SDKs. The host retains the definition for re-registration.
    """

    runtime_definition: object
    public_binding: BackendBinding
    public_definition: object | None = None

    # TODO: Independent activation/failure domains and idle SDK cache release
    # need explicit capability resource scopes. Registration and rollback
    # currently cover the plugin; imported shared SDKs live with the process.


class BackendResolver:
    """Resolve runtime definitions and their public registration without imports."""

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
        """Describe all definitions owned by one installed plugin."""
        if manifest.entry.descriptor is None:
            return self.resolve_registration(source_path, manifest)
        manifest = manifest.model_copy(deep=True)
        backend = self.select(manifest)
        return BackendBinding(
            backend,
            backend.describe(Path(source_path), manifest),
            self.resolve_registration(source_path, manifest)
            if manifest.entry.backend
            else None,
        )

    def select(self, manifest):
        """Select the trusted adapter without hashing unrelated source trees."""
        backend = self._python_backend
        if manifest.entry.descriptor is not None:
            try:
                backend = self._descriptors[manifest.plugin_type]
            except KeyError as exc:
                raise ValueError(
                    f"No descriptor backend registered for {manifest.plugin_type.value}",
                ) from exc
        return backend

    def resolve_registration(
        self,
        source_path: Path,
        manifest: PluginManifest,
    ) -> BackendBinding:
        """Describe the public Python entry for an explicit consumer."""
        manifest = manifest.model_copy(deep=True)
        return BackendBinding(
            self._python_backend,
            self._python_backend.describe(Path(source_path), manifest),
        )


@contextmanager
def registration_scope(binding: BackendBinding):
    """Retain every definition's import custody through registration rollback."""
    with ExitStack() as scopes:
        scope = getattr(binding.backend, "registration_scope", None)
        if scope is not None:
            scopes.enter_context(scope(binding.description))
        if binding.registration is not None:
            scopes.enter_context(registration_scope(binding.registration))
        yield


def discovers_disabled(binding: BackendBinding) -> bool:
    """Older adapters keep the conservative disabled-discovery policy."""
    return getattr(binding.backend, "discover_disabled", False)


def probes_before_activation(binding: BackendBinding) -> bool:
    """Legacy Python registration is already its execution check."""
    return getattr(binding.backend, "probe_before_activation", False)
