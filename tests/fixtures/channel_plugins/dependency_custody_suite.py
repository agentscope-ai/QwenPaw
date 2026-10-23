"""Host-owned resource claims do not invent a second interpreter."""

from dataclasses import replace
import sys

import pytest
from packaging.markers import default_environment

from qwenpaw.plugins.dependency_gate import evaluate_shared_dependencies
from qwenpaw.plugins.dependency_usage import (
    DependencyDeclaration,
    DependencyEnvironment,
    DependencyUsageRegistry,
)
from qwenpaw.plugins.execution.dependencies import DependencySnapshot
from qwenpaw.plugins.ownership import (
    RuntimeKey,
    RuntimeOwners,
    RuntimeSourceBusyError,
    RuntimeStopReceipt,
)


def parent_lease(owners, root):
    return owners.reserve(
        "sample",
        RuntimeKey("channel", "sample", "workspace"),
        root,
        instance_id="exact-worker",
    )


def claim_lease(owners, parent, **changes):
    values = {
        "plugin_id": parent.plugin_id,
        "key": RuntimeKey("file-custody", "auth-path", "host"),
        "code_root": parent.code_root,
        "instance_id": parent.instance_id,
        "dependency_owner": parent,
    }
    return owners.reserve(**(values | changes))


def verified_parent(owners, parent, site):
    evidence = DependencySnapshot.from_mapping(
        {
            "executable": sys.executable,
            "prefix": str(site.parent),
            "sites": [str(site)],
            "dependency_sites": [str(site)],
            "marker_environment": default_environment(),
            "supported_tags": ["py3-none-any"],
            "distributions": {},
        }
    )
    usage = DependencyUsageRegistry(owners)
    token = usage.declare(
        DependencyDeclaration(
            parent.plugin_id,
            "exact-source",
            (),
            DependencyEnvironment.from_snapshot(evidence),
        ),
        pending=False,
    )
    usage.bind(parent, token)
    usage.observe(parent, evidence)
    return usage, evidence


def gate(usage, evidence):
    return evaluate_shared_dependencies(
        None,
        evidence,
        plugin_id="candidate",
        uses=usage.snapshot().uses,
    )


def test_trusted_claim_preserves_custody_without_second_environment(tmp_path):
    owners = RuntimeOwners()
    parent = parent_lease(owners, tmp_path / "source")
    usage, evidence = verified_parent(owners, parent, tmp_path / "site")
    claim = claim_lease(owners, parent)
    assert owners.leases() == (parent, claim)
    assert owners.dependency_leases() == (parent,)
    (use,) = usage.snapshot().uses
    assert use.instance_id == parent.instance_id
    assert use.generation == parent.generation
    assert use.source_revision == "exact-source"
    assert use.environment is not None and use.snapshot == evidence
    assert gate(usage, evidence).already_satisfied
    with pytest.raises(RuntimeSourceBusyError):
        with owners.mutation(parent.code_root):
            pytest.fail("Live resource custody admitted source mutation")


@pytest.mark.parametrize("kind", ["wechat_auth", "worker"])
def test_unbound_kind_never_grants_dependency_exemption(tmp_path, kind):
    owners = RuntimeOwners()
    parent = parent_lease(owners, tmp_path / "source")
    usage, evidence = verified_parent(owners, parent, tmp_path / "site")
    unknown = owners.reserve(
        "unbound",
        RuntimeKey(kind, "resource", "host"),
        tmp_path / "other",
        instance_id="unknown-executor",
    )
    assert unknown in owners.dependency_leases()
    unknown_use = next(
        use for use in usage.snapshot().uses if use.plugin_id == "unbound"
    )
    assert unknown_use.environment is None and unknown_use.snapshot is None
    decision = gate(usage, evidence)
    assert not decision.already_satisfied
    assert decision.reason_code == "DEPENDENCY_PLAN_UNVERIFIED"
    assert (
        "runtime unbound: environment evidence unavailable" in decision.reason
    )


@pytest.mark.parametrize(
    "mismatch",
    [
        "plugin",
        "source",
        "instance",
        "released-parent",
        "wrong-generation",
    ],
)
def test_claim_rejects_mismatched_or_stale_parent(tmp_path, mismatch):
    owners = RuntimeOwners()
    parent = parent_lease(owners, tmp_path / "source")
    changes = {}
    if mismatch == "plugin":
        changes["plugin_id"] = "other-plugin"
    elif mismatch == "source":
        changes["code_root"] = tmp_path / "other-source"
    elif mismatch == "instance":
        changes["instance_id"] = "other-worker"
    elif mismatch == "released-parent":
        assert owners.release(parent, RuntimeStopReceipt(True))
    else:
        changes["dependency_owner"] = replace(
            parent,
            generation=parent.generation + 1,
        )
    before = owners.leases()
    expected = (
        "STALE"
        if mismatch in ("released-parent", "wrong-generation")
        else "MISMATCH"
    )
    with pytest.raises(
        ValueError, match="RUNTIME_DEPENDENCY_OWNER_" + expected
    ):
        claim_lease(owners, parent, **changes)
    assert owners.leases() == before


@pytest.mark.parametrize("replacement", [False, True])
def test_orphan_claim_becomes_unknown_even_after_same_key_restart(
    tmp_path,
    replacement,
):
    owners = RuntimeOwners()
    parent = parent_lease(owners, tmp_path / "source")
    usage, evidence = verified_parent(owners, parent, tmp_path / "site")
    claim = claim_lease(owners, parent)
    before = usage.snapshot()
    assert owners.release(parent, RuntimeStopReceipt(True))
    if replacement:
        current = parent_lease(owners, parent.code_root)
        assert current.instance_id == parent.instance_id
        assert current.generation > parent.generation
        token = usage.declare(
            DependencyDeclaration(
                "sample",
                "exact-source",
                (),
                DependencyEnvironment.from_snapshot(evidence),
            ),
            pending=False,
        )
        usage.bind(current, token)
        usage.observe(current, evidence)
    assert claim in owners.dependency_leases()
    after = usage.snapshot()
    assert after.revision != before.revision
    unknown = [use for use in after.uses if use.environment is None]
    assert len(unknown) == 1
    assert unknown[0].instance_id == claim.instance_id
    assert unknown[0].generation == claim.generation
    assert not gate(usage, evidence).already_satisfied
    with pytest.raises(RuntimeSourceBusyError):
        with owners.mutation(parent.code_root):
            pytest.fail("Orphan resource custody admitted source mutation")


@pytest.mark.asyncio
async def test_failed_claim_stop_retains_custody_until_exact_retry(tmp_path):
    owners = RuntimeOwners()
    parent = parent_lease(owners, tmp_path / "source")
    claim = claim_lease(owners, parent)
    receipts = iter(
        [
            RuntimeStopReceipt(False, exited=False, residual=("AUTH_IO",)),
            RuntimeStopReceipt(True),
        ]
    )

    async def stop():
        return next(receipts)

    resource = object()
    owners.attach(claim, stop, resource=resource)
    assert owners.release(parent, RuntimeStopReceipt(True))
    failed = await owners.stop(claim)
    assert not failed.stopped
    assert owners.leases() == (claim,)
    assert owners.dependency_leases() == (claim,)
    assert owners.resource(claim) is resource
    with pytest.raises(RuntimeSourceBusyError):
        with owners.mutation(parent.code_root):
            pytest.fail("Failed-stop claim admitted source replacement")
    assert (await owners.stop(claim)).stopped
    assert owners.leases() == ()
    assert owners.dependency_leases() == ()
    with owners.mutation(parent.code_root):
        assert owners.resource(claim) is None


@pytest.mark.asyncio
async def test_explicit_host_record_keeps_failed_stop_custody_not_interpreter(
    tmp_path,
):
    owners = RuntimeOwners()
    parent = parent_lease(owners, tmp_path / "source")
    usage, evidence = verified_parent(owners, parent, tmp_path / "site")
    record = owners.reserve(
        "sample",
        RuntimeKey("arbitrary-host-record", "pending-state", "host"),
        parent.code_root,
        instance_id="host-record",
        custody_only=True,
    )
    calls = []

    async def stop_record():
        calls.append(record)
        return RuntimeStopReceipt(
            len(calls) > 1,
            residual=("HOST_CLEANUP",) if len(calls) == 1 else (),
        )

    owners.attach(record, stop_record)
    assert owners.release(parent, RuntimeStopReceipt(True))
    assert owners.leases() == (record,)
    assert owners.dependency_leases() == ()
    assert gate(usage, evidence).already_satisfied
    assert not (await owners.stop(record)).stopped
    assert calls == [record] and owners.leases() == (record,)
    assert gate(usage, evidence).already_satisfied
    with pytest.raises(RuntimeSourceBusyError):
        with owners.mutation(record.code_root):
            pytest.fail("Failed host cleanup admitted source replacement")
    assert (await owners.stop(record)).stopped
    assert calls == [record, record]
    assert owners.leases() == ()
    with owners.mutation(record.code_root):
        assert gate(usage, evidence).already_satisfied


@pytest.mark.parametrize("classification", [None, 1, "true"])
def test_host_record_classification_requires_exact_bool(
    tmp_path, classification
):
    owners = RuntimeOwners()
    with pytest.raises(ValueError, match="RUNTIME_CUSTODY_CLASS_INVALID"):
        owners.reserve(
            "sample",
            RuntimeKey("host-record", "state", "host"),
            tmp_path / "source",
            instance_id="record",
            custody_only=classification,
        )
    assert owners.leases() == ()
    assert owners.dependency_leases() == ()


def test_host_record_cannot_also_claim_dependency_parent(tmp_path):
    owners = RuntimeOwners()
    parent = parent_lease(owners, tmp_path / "source")
    with pytest.raises(ValueError, match="RUNTIME_CUSTODY_CLASS_INVALID"):
        claim_lease(owners, parent, custody_only=True)
    assert owners.leases() == (parent,)
    assert owners.dependency_leases() == (parent,)
