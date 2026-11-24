# -*- coding: utf-8 -*-
"""Host dependency evidence retained by the usage registry."""

from __future__ import annotations

from qwenpaw.plugins.dependency_usage import (
    DependencyDeclaration,
    DependencyUsageRegistry,
)
from qwenpaw.plugins.execution.dependencies import DependencySnapshot


class _Owners:
    """Lease source with no runtime consumers."""

    def leases(self):
        return ()

    def dependency_leases(self):
        return ()


def _snapshot() -> DependencySnapshot:
    site = "/opt/site-packages"
    return DependencySnapshot(
        executable="/opt/venv/bin/python",
        prefix="/opt/venv",
        sites=(site,),
        marker_environment={"python_version": "3.11"},
        supported_tags=("cp311-cp311-linux_x86_64",),
        distributions={},
        dependency_sites=(site,),
    )


def _declared() -> tuple[DependencyUsageRegistry, object]:
    usage = DependencyUsageRegistry(_Owners())
    return usage, usage.declare(DependencyDeclaration("hub", None, (), None))


def _host_uses(usage: DependencyUsageRegistry):
    return [use for use in usage.snapshot().uses if use.origin == "host"]


def test_unknown_host_evidence_stays_unusable() -> None:
    """A capture that never succeeded must keep blocking admission."""
    usage, token = _declared()

    usage.observe_host(token, None)

    (use,) = _host_uses(usage)
    assert use.snapshot is None
    assert use.environment is None


def test_unknown_observation_keeps_last_capture() -> None:
    """A later failed observation must not discard usable evidence."""
    usage, token = _declared()
    snapshot = _snapshot()
    usage.observe_host(token, snapshot)

    usage.observe_host(token, None)

    (use,) = _host_uses(usage)
    assert use.snapshot == snapshot
    assert use.environment is not None
    assert use.environment.sites == snapshot.dependency_sites


def test_withdraw_drops_host_evidence() -> None:
    """Reloading a plugin must not leave its old capture behind."""
    usage, token = _declared()
    usage.observe_host(token, _snapshot())

    usage.withdraw(token)

    assert usage.snapshot().uses == ()
