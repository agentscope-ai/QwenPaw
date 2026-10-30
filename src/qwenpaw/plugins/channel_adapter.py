# -*- coding: utf-8 -*-
"""Host-owned static Channel definitions; no executable plugin discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
from typing import Any, Callable, Mapping
from contextlib import asynccontextmanager, nullcontext

from .execution_backend import (
    DefinitionResult,
    PluginDescription,
    PreparedDependencyTargets,
)

from ..channel_protocol.artifacts import code_root_digest
from ..channel_protocol.outbound_budget import (
    DEFAULT_SEND_TIMEOUT,
    validate_send_timeout,
    validate_send_timeouts,
)
from ..channel_protocol.requirements import canonicalize_requirements
from ..channel_protocol.shared import (
    SharedChannelDescriptor,
    _read_requirements,
)
from .architecture import PluginManifest, PluginType

CHANNEL_RUNTIME_NOT_INTEGRATED = "channel_runtime_not_integrated"


class ChannelRuntimeNotIntegratedError(RuntimeError):
    """A descriptor operation was refused before transaction work began."""


def _contained_file(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.resolve().is_relative_to(root):
        raise ValueError("Channel file escapes code root")
    if any(
        part.is_symlink() for part in (path, *path.parents) if part != root
    ):
        raise ValueError("Channel files cannot use symlinks")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


@dataclass(frozen=True)
class ChannelRuntimeSettings:
    """Trusted host execution policy; never read from channel configuration."""

    python_executable: str
    support_root: Path
    qwenpaw_version: str
    selected_channels: frozenset[str] | None = frozenset()
    dependency_paths: tuple[Path, ...] = ()
    # Includes dependency-origin validation and the platform SDK's import.
    startup_timeout: float = 10.0
    shutdown_timeout: float = 2.0
    admission_timeout: float = 30.0
    dependency_install_target: Path | None = None
    runtime_identity: Mapping[str, Any] | None = None
    connection_timeout: float | None = None
    send_timeout: float = DEFAULT_SEND_TIMEOUT
    send_timeouts: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self):
        validate_send_timeout(self.send_timeout)
        object.__setattr__(
            self,
            "send_timeouts",
            validate_send_timeouts(self.send_timeouts),
        )
        if self.connection_timeout is not None and (
            type(self.connection_timeout) not in (int, float)
            or not math.isfinite(self.connection_timeout)
            or self.connection_timeout <= 0
        ):
            raise ValueError("Connection timeout must be finite and positive")
        if (
            min(
                self.startup_timeout,
                self.shutdown_timeout,
                self.admission_timeout,
            )
            <= 0
        ):
            raise ValueError("Channel timeouts must be positive")

    def send_timeout_for(self, channel_key: str) -> float:
        return self.send_timeouts.get(channel_key, self.send_timeout)

    def allows(self, channel_key: str) -> bool:
        """None admits descriptors; an explicit collection is a whitelist."""
        return (
            self.selected_channels is None
            or channel_key in self.selected_channels
        )


@dataclass(frozen=True)
class PreparedProxyConfig:
    """Detached execution values prepared before reserving runtime resources."""

    description: Any
    config: dict[str, Any]
    private_env: dict[str, str]


@dataclass(frozen=True)
class ChannelDescription:
    """One plugin's metadata and source identity, without loading a driver."""

    plugin_id: str
    version: str
    descriptor: SharedChannelDescriptor
    descriptor_path: Path
    code_root: Path
    requirements_path: Path
    requirements: tuple[str, ...]
    source_revision: str
    name: str
    description: str

    def prepare_proxy_config(
        self,
        config: Mapping[str, Any],
        *,
        workspace_dir: Path | None = None,
        config_source: str = "config",
        no_text_debounce: bool = True,
        private_env: Mapping[str, str] | None = None,
        legacy_references: Mapping | None = None,
        working_dir: Path | None = None,
        legacy_state_dir: Path | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> PreparedProxyConfig:
        """Read, validate and project host context without runtime mutation."""
        from .channel_config import (
            channel_config_dict,
            validate_channel_config,
        )
        from ..app.channels.catalog import clean_channel_config
        from ..app.channels.process_supervisor import LaunchSpec

        working_dir = Path.cwd() if working_dir is None else working_dir
        environment = dict(os.environ) if environment is None else environment
        if config_source not in {"config", "env"}:
            raise ValueError("CONFIG_SOURCE_INVALID")
        raw = channel_config_dict(config)
        if config_source == "config":
            from ..config.channel_config_compat import normalize_channel_config

            raw = normalize_channel_config(
                self.descriptor.channel_key,
                raw,
                dictionary=not hasattr(config, "model_dump"),
            )
        raw = clean_channel_config(
            raw,
            self.descriptor.config_schema,
        )
        raw["no_text_debounce"] = no_text_debounce
        values = validate_channel_config(self.descriptor.config_schema, raw)
        controls = LaunchSpec.__dataclass_fields__.keys() - {
            "config",
            "enabled",
        }
        values = {
            key: value for key, value in values.items() if key not in controls
        }
        from .execution.bootstrap import validate_private_environment
        from .official_channel_catalog import official_channel_for_plugin

        private_environment = validate_private_environment(
            {} if private_env is None else private_env,
        )
        official = official_channel_for_plugin(self.plugin_id)
        official_owner = official is not None and (
            official["channel_key"] == self.descriptor.channel_key
        )
        from .official_execution_context import prepare_official_execution

        legacy_root = legacy_state_dir
        if official_owner and legacy_root is None:
            from ..constant import WORKING_DIR

            legacy_root = WORKING_DIR
        values, selected = prepare_official_execution(
            self.descriptor.channel_key,
            values,
            official=official if official_owner else None,
            working_dir=working_dir,
            legacy_state_dir=legacy_root,
            environment=environment,
            workspace_dir=workspace_dir,
            legacy_references=legacy_references,
        )
        private_environment = validate_private_environment(
            {**selected, **private_environment},
        )
        return PreparedProxyConfig(self, values, private_environment)

    def create_proxy(
        self,
        process,
        config: Mapping[str, Any],
        *,
        python_executable: str,
        support_root: Path,
        instance_id: str,
        generation: int,
        qwenpaw_version: str,
        dependency_paths: tuple[Path, ...] = (),
        runtime_identity=None,
        workspace_dir: Path | None = None,
        on_reply_sent=None,
        display_config=None,
        no_text_debounce: bool = True,
        startup_timeout: float = 5.0,
        shutdown_timeout: float = 2.0,
        config_source: str = "config",
        connection_timeout: float | None = None,
        send_timeout: float = DEFAULT_SEND_TIMEOUT,
        prepared_config: PreparedProxyConfig,
    ):
        """Construct an unstarted proxy from explicitly prepared host values."""
        from ..app.channels.isolated_proxy import IsolatedChannelProxy
        from ..app.channels.process_supervisor import LaunchSpec

        if prepared_config.description is not self:
            raise ValueError("CHANNEL_PREPARATION_STALE")
        values = prepared_config.config
        environment = prepared_config.private_env
        spec = LaunchSpec(
            python_executable=python_executable,
            support_root=Path(support_root),
            code_root=self.code_root,
            descriptor_path=self.descriptor_path,
            source_revision=self.source_revision,
            descriptor=self.descriptor,
            requirements=self.requirements,
            channel_key=self.descriptor.channel_key,
            instance_id=instance_id,
            generation=generation,
            qwenpaw_version=qwenpaw_version,
            config=values,
            dependency_paths=dependency_paths,
            runtime_identity=runtime_identity,
            enabled=values["enabled"],
            startup_timeout=startup_timeout,
            shutdown_timeout=shutdown_timeout,
            send_timeout=send_timeout,
            private_env=environment,
            plugin_id=self.plugin_id,
            workspace_id=(
                str(Path(workspace_dir).resolve())
                if workspace_dir is not None
                else None
            ),
        )
        return IsolatedChannelProxy(
            process,
            launch_spec=spec,
            descriptor=self.descriptor,
            workspace_dir=workspace_dir,
            on_reply_sent=on_reply_sent,
            display_config=display_config,
            connection_timeout=connection_timeout,
        )


def describe_channel(
    source_path: Path,
    manifest: PluginManifest,
) -> ChannelDescription:
    """Validate source metadata without loading implementation code."""
    if (
        manifest.plugin_type != PluginType.CHANNEL
        or not manifest.entry.descriptor
    ):
        raise ValueError("Channel descriptor entry is required")
    root = Path(source_path).resolve()
    descriptor_path = _contained_file(root, manifest.entry.descriptor)
    descriptor = SharedChannelDescriptor.load(descriptor_path)
    from ..channel_protocol.shared import validate_channel_contract
    from .channel_config import validate_channel_config_schema

    validate_channel_contract(descriptor.channel_key, descriptor.capabilities)
    validate_channel_config_schema(descriptor.config_schema)
    from ..app.channels.registry import BUILTIN_CHANNEL_KEYS
    from .official_channel_catalog import (
        official_channel_owners,
        official_channel_for_plugin,
    )

    key = descriptor.channel_key
    owner = official_channel_owners().get(key)
    if key in BUILTIN_CHANNEL_KEYS or (owner and owner != manifest.id):
        occupying = "builtin" if key in BUILTIN_CHANNEL_KEYS else owner
        raise ValueError(
            f"Channel '{key}' owner '{occupying}' conflicts with "
            f"plugin '{manifest.id}'",
        )
    official = official_channel_for_plugin(manifest.id)
    if official is not None and official["channel_key"] != key:
        raise ValueError(
            f"Channel descriptor owner '{manifest.id}' must use "
            f"channel '{official['channel_key']}'",
        )
    requirements_path = _contained_file(
        root,
        (descriptor_path.parent / descriptor.requirements_file)
        .relative_to(root)
        .as_posix(),
    )
    if requirements_path != root / "requirements.txt":
        raise ValueError("Channel requirements must live at the plugin root")
    requirements = _read_requirements(requirements_path)
    if (
        manifest.dependencies
        and canonicalize_requirements(manifest.dependencies) != requirements
    ):
        raise ValueError("Manifest dependencies differ from requirements.txt")
    return ChannelDescription(
        plugin_id=manifest.id,
        version=manifest.version,
        descriptor=descriptor,
        descriptor_path=descriptor_path,
        code_root=root,
        requirements_path=requirements_path,
        requirements=requirements,
        source_revision=code_root_digest(root),
        name=manifest.name,
        description=manifest.description,
    )


@dataclass(frozen=True)
class StaticChannelDefinition:
    """Register metadata under the same lifecycle ledger as Python plugins."""

    description: ChannelDescription
    runtime_settings: ChannelRuntimeSettings | None = None
    global_enabled: bool = True

    def register(self, api) -> None:
        api.register_channel_descriptor(
            self.description,
            runtime_settings=self.runtime_settings,
            global_enabled=self.global_enabled,
        )


@dataclass(frozen=True)
class ChannelServices:
    """Host services used by static Channel execution, without a Loader."""

    runtime_settings: Callable
    prepare_candidate: Callable
    own_preparation: Callable
    stop_preparation: Callable
    release_preparation: Callable
    acquire_wheels: Callable
    dependency_usage: Callable
    workspaces: Callable
    registration: Callable
    record: Callable


class ChannelBackend:
    """Static definitions and execution checks for isolated Channels."""

    discover_disabled = True
    probe_before_activation = True

    def __init__(self, services: ChannelServices):
        self.services = services
        self._prepared = {}

    def runtime_for(self, candidate):
        """Select by trusted routing identity, independently of plugin ID."""
        settings = self.services.runtime_settings()
        if settings is None:
            return None
        payload = (
            candidate.payload
            if isinstance(candidate, PluginDescription)
            else candidate
        )
        if isinstance(payload, ChannelDescription):
            key = payload.descriptor.channel_key
        else:
            from .official_channel_catalog import official_channel_for_plugin

            official = official_channel_for_plugin(candidate.id)
            key = official["channel_key"] if official else None
            if key is None and hasattr(self.services, "registration"):
                row = self.services.registration(candidate.id)
                if row is not None and row.description_record is not None:
                    key = row.description_record.descriptor.channel_key
        return (
            settings
            if (
                settings.selected_channels is None
                or (key is not None and settings.allows(key))
            )
            else None
        )

    async def prepare_dependency_targets(self, description):
        """Configured roots serialize inspection; the child verifies them."""
        from .dependency_context import _capture_runtime_selection

        validate = _capture_runtime_selection(
            lambda: self.runtime_for(description),
        )
        settings = self.runtime_for(description)
        if settings is None:
            return PreparedDependencyTargets((), validate)
        return PreparedDependencyTargets(
            (
                *settings.dependency_paths,
                *(
                    (settings.dependency_install_target,)
                    if settings.dependency_install_target
                    else ()
                ),
            ),
            validate,
        )

    def dependency_install_target(self, description, _snapshot):
        """The host-selected publication site, independent of platform SDK."""
        settings = self.runtime_for(description)
        return settings.dependency_install_target if settings else None

    def dependency_environment(self, description, _snapshot):
        from .dependency_context import DependencyEnvironmentContext

        settings = self.runtime_for(description)
        if settings is None:
            self.require_selection(description.manifest)
        return DependencyEnvironmentContext.from_runtime(settings)

    def require_selection(self, manifest):
        if self.runtime_for(manifest) is None:
            raise ChannelRuntimeNotIntegratedError(
                CHANNEL_RUNTIME_NOT_INTEGRATED,
            )

    def describe(self, source_path, manifest):
        payload = describe_channel(source_path, manifest)
        return PluginDescription(
            manifest,
            Path(source_path),
            payload.requirements_path,
            payload,
            code_root_digest(
                source_path,
                ignored_paths=(".qwenpaw-pawport.json",),
            ),
        )

    def registration_scope(self, description):
        del description
        return nullcontext()

    async def prepare(
        self,
        description,
        *,
        allow_install,
        probe,
        wheels=(),
        owns_dependency_env=True,
    ):
        # Static discovery must not inspect/import an unselected platform SDK.
        if not allow_install and not probe:
            return
        self.require_selection(description)
        prepared = await self.services.prepare_candidate(
            description.payload,
            allow_install=allow_install and owns_dependency_env,
            probe=probe,
            wheels=wheels if owns_dependency_env else (),
        )
        snapshot = getattr(prepared, "snapshot", prepared)
        self._prepared[description.manifest.id] = (description, snapshot)
        record = self.services.record(description.manifest.id)
        if (
            record is not None
            and record.backend_binding is not None
            and record.backend_binding.description == description
        ):
            self._validation(description.manifest.id, passed=True)
            row = self.services.registration(description.manifest.id)
            if row is not None:
                self.services.dependency_usage().refine(
                    row.dependency_token,
                    snapshot,
                )
        return snapshot

    async def load_definition(
        self,
        description,
        config,
        *,
        saved_definition=None,
    ):
        from .settings import is_plugin_enabled

        del saved_definition
        settings = self.runtime_for(description)
        enabled = is_plugin_enabled(config)
        diagnostics = () if settings else (CHANNEL_RUNTIME_NOT_INTEGRATED,)
        prepared = self._prepared.get(description.manifest.id)
        snapshot = None
        if (
            prepared is not None
            and prepared[0].manifest == description.manifest
            and prepared[0].source_identity == description.source_identity
        ):
            self._prepared.pop(description.manifest.id)
            snapshot = prepared[1]
            diagnostics += ("channel_validation_passed",)
        if not enabled:
            diagnostics += ("channel_validation_pending",)
        return DefinitionResult(
            StaticChannelDefinition(description.payload, settings, enabled),
            enabled=settings is not None and enabled,
            status=(
                "inactive"
                if not enabled
                else "registered"
                if settings
                else "catalogued"
            ),
            diagnostics=diagnostics,
            dependency_snapshot=snapshot,
        )

    def _validation(self, plugin_id, *, passed):
        record = self.services.record(plugin_id)
        if record is None:
            return
        marker = (
            "channel_validation_passed"
            if passed
            else "channel_validation_pending"
        )
        if passed:
            record.diagnostics = [
                item
                for item in record.diagnostics
                if item != "channel_validation_pending"
            ]
        if marker not in record.diagnostics:
            record.diagnostics.append(marker)

    async def before_activate(self, description):
        from .api import channel_passes_gates

        plugin_id = description.manifest.id
        self.require_selection(description)
        record = self.services.record(plugin_id)
        if record is None or not record.enabled:
            return
        row = self.services.registration(plugin_id)
        channel_key = description.payload.descriptor.channel_key
        targets = [
            workspace
            for workspace in self.services.workspaces()
            if channel_passes_gates(workspace, channel_key)
            and getattr(workspace, "channel_manager", None) is not None
        ]
        for workspace in targets:
            owner = await workspace.channel_manager.get_channel(channel_key)
            if (
                owner is not None
                and getattr(owner, "_registration", None) is not row
            ):
                raise RuntimeError("CHANNEL_ALREADY_OWNED")
        if targets and "channel_validation_passed" not in record.diagnostics:
            import asyncio
            from .dependency_usage import admission_context

            if row is None or row.description_record != description.payload:
                raise RuntimeError(
                    "DEPENDENCY_PLAN_UNVERIFIED: admission source mismatch",
                )
            context = admission_context.set(
                (
                    self.services.dependency_usage(),
                    row.dependency_token,
                    asyncio.current_task(),
                    description,
                ),
            )
            try:
                await self.prepare(
                    description,
                    allow_install=False,
                    probe=True,
                )
            finally:
                admission_context.reset(context)
        elif not {
            "channel_validation_passed",
            "channel_validation_pending",
        }.intersection(record.diagnostics):
            self._validation(plugin_id, passed=False)

    def validate_update(self, old, candidate, *, in_place):
        old_payload = (
            old.payload if isinstance(old, PluginDescription) else old
        )
        candidate_payload = (
            candidate.payload
            if isinstance(candidate, PluginDescription)
            else candidate
        )
        if (
            isinstance(old_payload, ChannelDescription)
            and isinstance(candidate_payload, ChannelDescription)
            and old_payload.descriptor.channel_key
            != candidate_payload.descriptor.channel_key
        ):
            raise ValueError(
                "Channel update cannot change channel_key from "
                f"'{old_payload.descriptor.channel_key}' to "
                f"'{candidate_payload.descriptor.channel_key}'",
            )
        self.require_selection(candidate)
        if in_place:
            raise RuntimeError(
                "Channel in-place source update is not supported",
            )

    def validate_config_update(self, description, config):
        """Reject unintegrated mutations without probing disabled plugins."""
        del config
        self.require_selection(description)

    def capture_restore_state(self, record):
        """Static definitions require no host import snapshot."""
        del record

    def restore_state(self, state):
        """Static Channel definitions hold no host import state."""

    @asynccontextmanager
    async def _dependency_inspection(self, description):
        """Own only this inspection child; never stop another preparation."""
        from uuid import uuid4
        from ..app.channels.process_supervisor import (
            ChannelProcess,
            LaunchSpec,
        )

        settings = self.services.runtime_settings()
        if settings is None:
            raise ChannelRuntimeNotIntegratedError(
                CHANNEL_RUNTIME_NOT_INTEGRATED,
            )
        process, lease = self.services.own_preparation(
            description.plugin_id,
            ChannelProcess,
            description.code_root,
            instance_id="probe:" + uuid4().hex,
        )
        from .dependency_usage import DependencyDeclaration

        usage = self.services.dependency_usage()
        token = usage.declare(
            DependencyDeclaration(
                description.plugin_id,
                description.source_revision,
                description.requirements,
                None,
            ),
        )
        try:
            usage.bind(lease, token)
            process.dependency_observer = lambda snapshot: usage.observe(
                lease,
                snapshot,
            )
            spec = LaunchSpec(
                python_executable=settings.python_executable,
                support_root=settings.support_root,
                code_root=description.code_root,
                descriptor_path=description.descriptor_path,
                source_revision=description.source_revision,
                descriptor=description.descriptor,
                requirements=description.requirements,
                channel_key=description.descriptor.channel_key,
                instance_id=lease.instance_id,
                generation=lease.generation,
                qwenpaw_version=settings.qwenpaw_version,
                config={},
                dependency_paths=settings.dependency_paths,
                runtime_identity=settings.runtime_identity,
                startup_timeout=settings.startup_timeout,
                shutdown_timeout=settings.shutdown_timeout,
            )
            yield process, spec, token, usage
        finally:
            try:
                observed = getattr(process, "dependency_snapshot", None)
                if observed is not None:
                    usage.observe(lease, observed)
            finally:
                try:
                    await self.services.release_preparation(lease)
                finally:
                    usage.withdraw(token)

    async def admit_existing(
        self,
        description,
        *,
        usage,
        token,
        snapshot=None,
    ):
        from .dependency_gate import admit_shared_dependencies

        prepared = await self.prepare_dependency_targets(description)
        return await admit_shared_dependencies(
            lambda: self.audit_dependencies(description),
            plugin_id=description.manifest.id,
            requirements_file=None,
            usage_registry=usage,
            admission_token=token,
            snapshot=snapshot,
            targets=prepared.targets,
            validate=prepared.validate,
        )

    async def audit_dependencies(self, description):
        """Fence configured roots; the child still verifies actual sites."""
        from .install_lock import environment_observation

        prepared = await self.prepare_dependency_targets(description)
        async with environment_observation(prepared.targets):
            prepared.validate()
            async with self._dependency_inspection(
                description.payload,
            ) as values:
                process, spec, _token, _usage = values
                observed = (await process.audit(spec)).snapshot
            prepared.validate()
            return observed

    async def prepare_candidate(
        self,
        description,
        *,
        wheels=(),
        probe=True,
        allow_install=False,
    ):
        """One check/install/probe boundary for activation and C5 staging."""
        from .dependency_gate import (
            prepare_shared_dependencies,
            SharedDependencyError,
        )
        from .dependency_usage import current_admission_token

        await self.services.stop_preparation(description.plugin_id)
        async with self._dependency_inspection(description) as values:
            process, spec, token, usage = values
            admission = current_admission_token(
                usage,
                description.plugin_id,
                description.code_root,
            )
            settings = self.services.runtime_settings()
            try:
                snapshot = await prepare_shared_dependencies(
                    process,
                    spec,
                    plugin_id=description.plugin_id,
                    requirements_file=description.requirements_path,
                    usage_registry=usage,
                    admission_token=admission or token,
                    install_target=settings.dependency_install_target,
                    targets=settings.dependency_paths,
                    wheels=wheels,
                )
            except SharedDependencyError as exc:
                if (
                    not allow_install
                    or wheels
                    or exc.decision.require_restart
                    or exc.decision.unsupported
                ):
                    raise
                snapshot = (await process.audit(spec)).snapshot
                target = settings.dependency_install_target
                if target is None:
                    raise RuntimeError(
                        "DEPENDENCY_INSTALL_TARGET_REQUIRED",
                    ) from exc
                await self.services.acquire_wheels(
                    process,
                    spec,
                    snapshot,
                    target,
                    description.plugin_id,
                    description.requirements_path,
                )
                snapshot = await prepare_shared_dependencies(
                    process,
                    spec,
                    plugin_id=description.plugin_id,
                    requirements_file=description.requirements_path,
                    usage_registry=usage,
                    admission_token=admission or token,
                    install_target=settings.dependency_install_target,
                    targets=settings.dependency_paths,
                )
            return await process.probe(spec) if probe else snapshot
