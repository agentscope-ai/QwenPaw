# -*- coding: utf-8 -*-
"""Dependency declarations and evidence; RuntimeOwners remains custody."""

from __future__ import annotations

from copy import deepcopy
import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from .execution.dependencies import DependencySnapshot
from .ownership import RuntimeLease, RuntimeOwners

admission_context: ContextVar[tuple | None] = ContextVar(
    "dependency_admission",
    default=None,
)


def current_admission_token(usage, plugin_id, source_path):
    """Return only this task's exact admission in this registry."""
    current = admission_context.get()
    if current is None or current[0] is not usage:
        return None
    try:
        task = asyncio.current_task()
    except RuntimeError:
        return None
    description = current[3]
    if (
        current[2] is not task
        or description.manifest.id != plugin_id
        or description.source_path.resolve() != Path(source_path).resolve()
    ):
        return None
    return current[1]


@dataclass(frozen=True)
class DependencyEnvironment:
    executable: str
    sites: tuple[str, ...]
    marker_environment: Mapping[str, str]

    @classmethod
    def from_snapshot(cls, snapshot):
        """Old transport evidence cannot establish package-root isolation."""
        if snapshot is None or snapshot.dependency_sites is None:
            return None
        return cls(
            snapshot.executable,
            snapshot.dependency_sites,
            dict(snapshot.marker_environment),
        )


@dataclass(frozen=True)
class DependencyDeclaration:
    plugin_id: str
    source_revision: str | None
    requirements: tuple[str, ...] | None
    environment: DependencyEnvironment | None


class DeclarationToken:
    """Opaque identity for one admission, even for identical declarations."""


@dataclass(frozen=True)
class DependencyUse(DependencyDeclaration):
    instance_id: str | None = None
    generation: int | None = None
    active: bool = False
    snapshot: DependencySnapshot | None = None
    origin: str = "declaration"
    # Protect pending/admitted declarations; False is catalogue metadata only.
    pending: bool = True
    read_admitted: bool = False
    read_context: object | None = None


@dataclass(frozen=True)
class UsageSnapshot:
    revision: int
    uses: tuple[DependencyUse, ...]


class DependencyUsageRegistry:
    """Store only evidence; query exact leases for current runtime custody."""

    def __init__(self, runtime_owners: RuntimeOwners):
        self._owners = runtime_owners
        self._declarations: dict[DeclarationToken, DependencyUse] = {}
        self._bindings: dict[
            RuntimeLease,
            tuple[DeclarationToken, DependencyUse],
        ] = {}
        self._host: dict[DeclarationToken, DependencyUse] = {}
        self._leases: tuple[RuntimeLease, ...] = ()
        self._revision = 0

    def declare(
        self,
        declaration: DependencyDeclaration,
        *,
        pending: bool = True,
    ) -> DeclarationToken:
        """Retain exact metadata; a static catalogue is not an admission."""
        token = DeclarationToken()
        self._declarations[token] = deepcopy(
            DependencyUse(
                declaration.plugin_id,
                declaration.source_revision,
                (
                    tuple(declaration.requirements)
                    if declaration.requirements is not None
                    else None
                ),
                declaration.environment,
                pending=pending,
            ),
        )
        self._revision += 1
        return token

    def admit_read(self, token, environment, *, description, context):
        """Record one exact, checked admission without inventing an audit."""
        declaration = self._declarations.get(token)
        expected = description.dependency_declaration()
        if (
            declaration is None
            or any(
                getattr(declaration, key) != getattr(expected, key)
                for key in ("plugin_id", "source_revision", "requirements")
            )
            or environment is None
        ):
            raise ValueError("DEPENDENCY_DECLARATION_MISMATCH")
        self._declarations[token] = replace(
            declaration,
            environment=deepcopy(environment),
            snapshot=None,
            read_admitted=True,
            read_context=deepcopy(context),
        )
        for lease, (bound_token, use) in tuple(self._bindings.items()):
            if bound_token is token:
                self._bindings[lease] = (
                    token,
                    replace(
                        use,
                        environment=deepcopy(environment),
                        snapshot=None,
                        read_admitted=True,
                        read_context=deepcopy(context),
                    ),
                )
        self._revision += 1

    def withdraw(self, token) -> None:
        if self._declarations.pop(token, None) is not None:
            for lease, (bound_token, use) in tuple(self._bindings.items()):
                if bound_token is token:
                    self._bindings[lease] = (
                        token,
                        replace(
                            use,
                            read_admitted=False,
                            read_context=None,
                        ),
                    )
            self._revision += 1

    def has_declaration(self, token, *, plugin_id=None) -> bool:
        """Check the exact admission without substituting a newer token."""
        declaration = self._declarations.get(token)
        return declaration is not None and (
            plugin_id is None or declaration.plugin_id == plugin_id
        )

    def bind(self, lease, token) -> None:
        if lease not in self._owners.leases():
            raise ValueError("DEPENDENCY_LEASE_STALE")
        declaration = self._declarations.get(token)
        if declaration is None or declaration.plugin_id != lease.plugin_id:
            raise ValueError("DEPENDENCY_DECLARATION_MISMATCH")
        bound = self._bindings.get(lease)
        if bound is not None:
            if bound[0] is not token:
                raise ValueError("DEPENDENCY_LEASE_ALREADY_BOUND")
            return
        self._bindings[lease] = (
            token,
            replace(
                declaration,
                instance_id=lease.instance_id,
                generation=lease.generation,
                active=True,
                origin="runtime",
            ),
        )
        self._revision += 1

    def refine(
        self,
        token,
        snapshot,
        *,
        plugin_id=None,
        pending=False,
    ) -> None:
        """Refine evidence without changing admission/source identity."""
        if plugin_id is not None and (
            token not in self._declarations
            or self._declarations[token].plugin_id != plugin_id
        ):
            raise ValueError("DEPENDENCY_DECLARATION_MISMATCH")
        if token in self._declarations:
            self._declarations[token] = deepcopy(
                replace(
                    self._declarations[token],
                    environment=DependencyEnvironment.from_snapshot(snapshot),
                    snapshot=snapshot,
                    read_admitted=False,
                    read_context=None,
                    pending=self._declarations[token].pending or pending,
                ),
            )
            self._revision += 1

    def observe(self, lease, snapshot: DependencySnapshot) -> None:
        if lease not in self._owners.leases():
            return
        if lease not in self._bindings:
            raise ValueError("DEPENDENCY_LEASE_UNBOUND")
        token, use = self._bindings[lease]
        self._bindings[lease] = (
            token,
            deepcopy(
                replace(
                    use,
                    snapshot=snapshot,
                    read_admitted=False,
                    read_context=None,
                    environment=DependencyEnvironment.from_snapshot(snapshot),
                ),
            ),
        )
        self.refine(token, snapshot)
        self._revision += 1

    def observe_host(self, token, snapshot: DependencySnapshot | None) -> None:
        """Adapters supply imports only, never an installed host inventory."""
        observed = snapshot is not None
        declaration = self._declarations[token]
        previous = self._host.get(token)
        if (
            previous is not None
            and previous.snapshot is not None
            and snapshot is not None
        ):
            old = previous.snapshot
            snapshot = replace(
                snapshot,
                sites=tuple(dict.fromkeys((*old.sites, *snapshot.sites))),
                dependency_sites=(
                    tuple(
                        dict.fromkeys(
                            (
                                *old.dependency_sites,
                                *snapshot.dependency_sites,
                            ),
                        ),
                    )
                    if old.dependency_sites is not None
                    and snapshot.dependency_sites is not None
                    else None
                ),
                distributions={**snapshot.distributions, **old.distributions},
            )
        elif previous is not None and snapshot is None:
            snapshot = previous.snapshot
        self._host[token] = deepcopy(
            replace(
                declaration,
                active=True,
                origin="host",
                snapshot=snapshot,
                read_admitted=False,
                read_context=None,
                environment=(
                    DependencyEnvironment.from_snapshot(snapshot)
                    if observed
                    and (previous is None or previous.environment is not None)
                    else None
                ),
            ),
        )
        self._revision += 1

    def capture_admissions(self, leases):
        """Retain exact token identity across custody snapshot pruning."""
        return {
            lease: self._bindings[lease][0]
            for lease in leases
            if lease in self._bindings
        }

    def rebase_stopped(self, leases, snapshot, admissions=()):
        """Refine exact stopped admissions after an explicit transaction."""
        restored = []
        for lease in leases:
            if lease in self._owners.leases():
                raise ValueError("DEPENDENCY_LEASE_STILL_ACTIVE")
            bound = self._bindings.pop(lease, None)
            if bound is None and lease in admissions:
                bound = (admissions[lease], None)
            if bound is not None and bound[0] in self._declarations:
                token = bound[0]
                restored.append((token, self._declarations[token]))
                self._declarations[token] = replace(
                    self._declarations[token],
                    snapshot=snapshot,
                    read_admitted=False,
                    read_context=None,
                    environment=DependencyEnvironment.from_snapshot(snapshot),
                )
        self._revision += 1
        return restored

    def restore_rebased(self, declarations):
        """Restore old evidence only after dependency rollback succeeded."""
        for token, declaration in declarations:
            if token in self._declarations:
                self._declarations[token] = declaration
        self._revision += 1

    def snapshot(
        self,
        environment=None,
        *,
        admission_token=None,
    ) -> UsageSnapshot:
        """Include one exact candidate without promoting its catalogue row."""
        leases = self._owners.dependency_leases()
        if leases != self._leases:
            self._leases = leases
            self._bindings = {
                lease: row
                for lease, row in self._bindings.items()
                if lease in leases
            }
            self._revision += 1
        uses = [
            use
            for token, use in self._declarations.items()
            if use.pending or token is admission_token
        ] + list(self._host.values())
        for lease in leases:
            bound = self._bindings.get(lease)
            uses.append(
                (
                    bound[1]
                    if bound
                    else DependencyUse(
                        lease.plugin_id,
                        None,
                        None,
                        None,
                        lease.instance_id,
                        lease.generation,
                        True,
                        origin="runtime",
                    )
                ),
            )
        sites = (
            {Path(site).resolve() for site in environment.sites}
            if environment
            else None
        )
        return UsageSnapshot(
            self._revision,
            deepcopy(
                tuple(
                    use
                    for use in uses
                    if sites is None
                    or use.environment is None
                    or sites.intersection(
                        Path(site).resolve() for site in use.environment.sites
                    )
                ),
            ),
        )
