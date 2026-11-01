# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Manifest-free shared-environment identity and component contract."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from .errors import ProtocolValidationError
from .models import PluginIdentity
from .rpc import RpcPeer


class PluginContext:
    """Data-only peer and generation identity provided to a component."""

    def __init__(self, peer: Any, identity: PluginIdentity) -> None:
        self.peer, self.identity = peer, identity

    async def set_state(self, state: str) -> None:
        if state not in {"starting", "ready", "failed", "stopped"}:
            raise ValueError("COMPONENT_STATE_INVALID")
        await self.peer.notify(
            "execution.state",
            {
                **self.identity.to_mapping(),
                "component_state": state,
            },
        )


def _requirements(path: str | Path | None) -> tuple[str, ...]:
    if path is None:
        return ()
    values = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            raise ProtocolValidationError(
                "invalid dependency declaration",
            ) from None
        if requirement.url or requirement.extras:
            raise ProtocolValidationError(
                "plain distribution requirements required",
            )
        values.append(str(requirement))
    return tuple(sorted(set(values)))


def _dependencies(
    path: str | Path | None,
    environment: Mapping[str, str],
    versions: Mapping[str, str | None] | None = None,
    *,
    expected_requirements: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for value in (
        _requirements(path)
        if expected_requirements is None
        else expected_requirements
    ):
        requirement = Requirement(value)
        name = str(canonicalize_name(requirement.name))
        installed = None
        skipped = requirement.marker and not requirement.marker.evaluate(
            environment=dict(environment),
        )
        if not skipped:
            if versions is not None:
                installed = versions.get(name)
            else:
                try:
                    installed = metadata.version(name)
                except metadata.PackageNotFoundError:
                    pass
            try:
                satisfied = (
                    installed is not None
                    and requirement.specifier.contains(
                        Version(installed),
                        prereleases=True,
                    )
                )
            except (InvalidVersion, TypeError):
                satisfied = False
            if not satisfied:
                raise ProtocolValidationError(
                    "shared dependency unavailable",
                    reason_code="DEPENDENCY_UNSATISFIED",
                )
        rows.append(
            {
                "requirement": value,
                "name": name,
                "installed_version": installed,
                "status": "skipped" if skipped else "satisfied",
            },
        )
    return rows


def validate_hello(
    hello: Any,
    spec: Any,
    *,
    expected_requirements: tuple[str, ...],
) -> None:
    """Fence handshake against the trusted parent launch and declarations."""
    identity = PluginIdentity(
        spec.plugin_id,
        spec.instance_id,
        spec.generation,
    )
    fields = set(identity.to_mapping()) | {
        "protocol_version",
        "source_revision",
        "python_abi",
        "platform_tag",
        "marker_environment",
        "dependencies",
    }
    if not isinstance(hello, Mapping) or set(hello) != fields:
        raise ProtocolValidationError(
            "invalid execution hello",
            reason_code="SCHEMA_MISMATCH",
        )
    if (
        type(hello["protocol_version"]) is not int
        or hello["protocol_version"] != 1
    ):
        raise ProtocolValidationError(
            "unsupported execution protocol",
            reason_code="PROTOCOL_MISMATCH",
        )
    received = PluginIdentity.from_mapping(
        {name: hello[name] for name in identity.to_mapping()},
    )
    if received != identity:
        raise ProtocolValidationError(
            "identity mismatch",
            reason_code="IDENTITY_MISMATCH",
        )
    if hello["source_revision"] != spec.source_revision:
        raise ProtocolValidationError(
            "source mismatch",
            reason_code="SOURCE_REVISION_MISMATCH",
        )
    environment = hello["marker_environment"]
    if (
        not isinstance(environment, Mapping)
        or set(environment) != set(default_environment())
        or any(not isinstance(item, str) for item in environment.values())
    ):
        raise ProtocolValidationError("invalid marker environment")
    for name in ("python_abi", "platform_tag"):
        if not isinstance(hello[name], str) or not hello[name]:
            raise ProtocolValidationError("invalid runtime identity")
    rows = hello["dependencies"]
    if not isinstance(rows, list) or any(
        not isinstance(row, Mapping) for row in rows
    ):
        raise ProtocolValidationError("invalid dependency evidence")
    try:
        expected = _dependencies(
            spec.requirements_path,
            environment,
            {row["name"]: row["installed_version"] for row in rows},
            expected_requirements=expected_requirements,
        )
    except (KeyError, TypeError):
        raise ProtocolValidationError("invalid dependency evidence") from None
    if rows != expected:
        raise ProtocolValidationError(
            "dependency evidence mismatch",
            reason_code="DEPENDENCY_UNSATISFIED",
        )


class Runtime:
    """Manifest-free worker policy for the common execution loop."""

    hello_method = "execution.hello"
    control_prefix = "execution."
    initial_state = "starting"
    failed_state = "failed"

    def identity(self, packet: Mapping[str, Any]) -> PluginIdentity:
        return PluginIdentity.from_mapping(
            {
                name: packet[name]
                for name in ("plugin_id", "instance_id", "generation")
            },
        )

    def peer(self, transport: Any) -> RpcPeer:
        return RpcPeer(transport)

    def context(self, peer: Any, identity: Any) -> PluginContext:
        return PluginContext(peer, identity)

    async def state(self, context: PluginContext, state: str) -> None:
        await context.set_state(state)

    def verify(
        self,
        boot: Any,
        packet: Mapping[str, Any],
        identity: Any,
    ) -> tuple[Any, Any, Any]:
        root = Path(packet["code_root"])
        if boot._hash_code_root(root) != packet["source_revision"]:
            raise boot.BootstrapError(
                "SOURCE_REVISION_MISMATCH",
                "source mismatch",
            )
        module, separator, qualname = packet["entrypoint"].partition(":")
        if not separator or any(
            not part.isidentifier()
            for item in (module, qualname)
            for part in item.split(".")
        ):
            raise boot.BootstrapError(
                "ENTRYPOINT_INVALID",
                "invalid entrypoint",
            )
        entrypoint = SimpleNamespace(module=module, qualname=qualname)
        source = boot._entrypoint_source(root, entrypoint)
        requirements = packet.get("requirements_path")
        if requirements is not None:
            requirements = boot._absolute_existing_file(
                requirements,
                "requirements_path",
            )
            if not requirements.is_relative_to(root):
                raise boot.BootstrapError(
                    "DEPENDENCY_PATH_INVALID",
                    "requirements outside root",
                )
        environment = default_environment()
        tag = next(sys_tags())
        hello = {
            **identity.to_mapping(),
            "protocol_version": 1,
            "source_revision": packet["source_revision"],
            "python_abi": f"{tag.interpreter}-{tag.abi}",
            "platform_tag": tag.platform,
            "marker_environment": environment,
            "dependencies": _dependencies(
                requirements,
                environment,
                packet.get("dependency_versions"),
            ),
        }
        return entrypoint, source, hello
