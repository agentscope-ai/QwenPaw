# -*- coding: utf-8 -*-
"""Opaque workspace contributions share exact ownership and stop semantics."""

import asyncio
from dataclasses import replace

import pytest

from qwenpaw.plugins.lifecycle import QuiescenceError
from qwenpaw.plugins.ownership import (
    RuntimeKey,
    RuntimeOwners,
    RuntimeStopReceipt,
)
from qwenpaw.plugins.workspace_projector import WorkspaceProjector


class Workspace:
    def __init__(self, agent_id="same-agent"):
        self.agent_id = agent_id
        self.enabled = True

    @property
    def channel_manager(self):
        raise AssertionError("generic projection must use adapter callbacks")


class Component:
    def __init__(self, projector, root, kind="worker", name="index"):
        self.owners = RuntimeOwners()
        self.root, self.kind, self.name = root, kind, name
        self.current = {}
        self.applied, self.revoked = [], []
        self.receipt = RuntimeStopReceipt(True)
        self.intent = projector.intend(
            kind,
            name,
            "plugin",
            self.apply,
            self.revoke,
            can_apply=lambda ws: ws.enabled,
            binding_is_current=lambda ws, token: self.current.get(ws) is token,
        )

    async def apply(self, ws):
        lease = self.owners.reserve(
            "plugin",
            RuntimeKey(self.kind, self.name, str(id(ws))),
            self.root,
            instance_id=f"{self.name}:{id(ws)}",
        )
        self.current[ws] = lease
        self.applied.append((ws, lease))

        async def stop():
            return self.receipt

        self.owners.attach(lease, stop, resource=object())
        return lease

    async def revoke(self, ws, token):
        self.revoked.append((ws, token))
        result = await self.owners.stop(token)
        if result.stopped and self.current.get(ws) is token:
            self.current.pop(ws)
        return result


@pytest.mark.asyncio
async def test_two_opaque_components_share_callbacks_and_kind_filter(tmp_path):
    ws = Workspace()
    projector = WorkspaceProjector(lambda: [ws])
    worker = Component(projector, tmp_path, "worker")
    events = Component(projector, tmp_path, "event-source")
    ws.enabled = False
    await projector.project_workspace(ws)
    assert not worker.applied and not events.applied
    ws.enabled = True
    await projector.project_workspace(ws, kinds={"worker"})
    assert len(worker.applied) == 1 and not events.applied
    await projector.project_workspace(ws)
    await projector.project_workspace(ws)
    assert len(worker.applied) == len(events.applied) == 1
    await projector.revoke("worker", "index", "plugin")
    assert not worker.owners.leases()
    assert events.owners.leases() and not events.revoked
    await projector.revoke_workspace(ws)
    assert not events.owners.leases()


@pytest.mark.asyncio
async def test_channel_kind_also_uses_opaque_callbacks_and_legacy_none():
    ws, token = Workspace(), object()
    # Fixture represents a workspace whose channel starts are deferred.
    # pylint: disable-next=protected-access
    ws._defer_channel_start = True
    projector = WorkspaceProjector(lambda: [ws])
    stopped = []
    projector.intend(
        "channel",
        "opaque",
        "plugin",
        lambda _: token,
        lambda workspace, binding: stopped.append((workspace, binding)),
    )
    await projector.project_workspace(ws, kinds={"channel"})
    await projector.project_workspace(ws)
    await projector.revoke("channel", "opaque", "plugin")
    assert stopped == [(ws, token)]


@pytest.mark.asyncio
async def test_displaced_binding_callback_allows_new_projection(tmp_path):
    ws = Workspace()
    projector = WorkspaceProjector(lambda: [ws])
    component = Component(projector, tmp_path)
    await projector.project_workspace(ws)
    old = component.current.pop(ws)
    assert component.owners.release(old, RuntimeStopReceipt(True))
    await projector.project_workspace(ws)
    fresh = component.current[ws]
    assert fresh.generation > old.generation
    assert component.owners.resource(old) is None
    await projector.revoke_workspace(ws)
    assert component.revoked == [(ws, fresh)]


@pytest.mark.asyncio
async def test_same_agent_id_retirement_and_replace_require_exact_object(
    tmp_path,
):
    old, new = Workspace(), Workspace()
    projector = WorkspaceProjector(lambda: [new])
    component = Component(projector, tmp_path)
    await projector.project_workspace(old)
    await projector.project_workspace(new)
    outgoing, incoming = component.current[old], component.current[new]
    replacement = object()
    for kind, name, plugin, workspace, expected in (
        ("worker", "index", "plugin", new, outgoing),
        ("worker", "index", "other", old, outgoing),
        ("worker", "other", "plugin", old, outgoing),
        ("other", "index", "plugin", old, outgoing),
        ("worker", "index", "plugin", old, object()),
        ("worker", "index", "plugin", old, replace(outgoing)),
    ):
        assert not projector.replace_binding(
            kind,
            name,
            plugin,
            workspace,
            expected=expected,
            token=replacement,
        )
    await projector.revoke_workspace(old)
    assert component.revoked == [(old, outgoing)]
    assert component.current[new] is incoming
    assert not projector.start_allowed("worker", "index", "plugin", old)
    assert projector.start_allowed("worker", "index", "plugin", new)
    await projector.project_workspace(old)
    assert len(component.applied) == 2
    await projector.revoke_workspace(new)


@pytest.mark.asyncio
async def test_replacement_during_revocation_is_stopped_as_current_token():
    ws, old, fresh = Workspace(), object(), object()
    projector = WorkspaceProjector(lambda: [ws])
    entered, release = asyncio.Event(), asyncio.Event()
    stopped = []

    async def revoke(workspace, token):
        assert workspace is ws
        stopped.append(token)
        if token is old:
            entered.set()
            await release.wait()
        return RuntimeStopReceipt(True)

    projector.intend("worker", "index", "plugin", lambda _: old, revoke)
    await projector.project_workspace(ws)
    revoking = asyncio.create_task(
        projector.revoke("worker", "index", "plugin"),
    )
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert not projector.start_allowed("worker", "index", "plugin", ws)
        assert projector.start_allowed("worker", "other", "plugin", ws)
        assert projector.replace_binding(
            "worker",
            "index",
            "plugin",
            ws,
            expected=old,
            token=fresh,
        )
        assert not projector.replace_binding(
            "worker",
            "index",
            "plugin",
            ws,
            expected=old,
            token=object(),
        )
        release.set()
        await revoking
        assert stopped == [old, fresh]
    finally:
        release.set()
        await asyncio.gather(revoking, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evidence",
    [
        RuntimeStopReceipt(False, "accepted work remains"),
        RuntimeStopReceipt(True, "process remains", exited=False),
        RuntimeStopReceipt(True, "descendant remains", residual=("BUSY",)),
    ],
)
async def test_failed_generic_stop_retains_unpublished_workspace_for_retry(
    tmp_path,
    evidence,
):
    ws = Workspace()
    live = [ws]
    projector = WorkspaceProjector(lambda: live)
    component = Component(projector, tmp_path)
    await projector.project_workspace(ws)
    held = component.current[ws]
    component.receipt = evidence
    live.clear()
    with pytest.raises(QuiescenceError):
        await projector.revoke("worker", "index", "plugin")
    assert component.owners.leases() == (held,)
    assert component.owners.resource(held) is not None
    assert component.current[ws] is held
    component.receipt = RuntimeStopReceipt(True)
    await projector.revoke("worker", "index", "plugin")
    assert component.revoked == [(ws, held), (ws, held)]
    assert not component.owners.leases()


@pytest.mark.asyncio
async def test_exception_preserves_failed_binding_and_settles_sibling():
    ws, stuck, healthy = Workspace(), object(), object()
    projector = WorkspaceProjector(lambda: [])
    failed = True
    stopped = []

    async def stop_stuck(workspace, token):
        assert workspace is ws and token is stuck
        if failed:
            raise OSError("current adapter stop failed")
        stopped.append(token)
        return RuntimeStopReceipt(True)

    projector.intend("worker", "stuck", "plugin", lambda _: stuck, stop_stuck)
    projector.intend(
        "event-source",
        "healthy",
        "plugin",
        lambda _: healthy,
        lambda workspace, token: stopped.append(token),
    )
    await projector.project_workspace(ws)
    with pytest.raises(QuiescenceError, match="current adapter stop failed"):
        await projector.revoke_workspace(ws)
    assert stopped == [healthy]
    assert not projector.start_allowed("worker", "stuck", "plugin", ws)
    failed = False
    await projector.revoke_workspace(ws)
    assert stopped == [healthy, stuck]


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_caller", [False, True])
async def test_preparing_workspace_start_remains_owned_until_retirement(
    tmp_path,
    cancel_caller,
):
    ws = Workspace()
    projector = WorkspaceProjector(lambda: [])
    projector.track_workspace(ws)
    owners = RuntimeOwners()
    entered, release, stop_entered = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )

    async def apply(workspace):
        assert workspace is ws
        held = owners.reserve(
            "plugin",
            RuntimeKey("worker", "index", "preparing"),
            tmp_path,
            instance_id="preparing:index",
        )

        async def stop():
            stop_entered.set()
            return RuntimeStopReceipt(True)

        owners.attach(held, stop, resource=object())
        entered.set()
        await release.wait()
        return held

    async def revoke(workspace, token):
        assert workspace is ws
        return await owners.stop(token)

    projector.intend("worker", "index", "plugin", apply, revoke)
    starting = asyncio.create_task(
        projector.project("worker", "index", "plugin"),
    )
    retiring = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert len(owners.leases()) == 1
        if cancel_caller:
            starting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await starting
        retiring = asyncio.create_task(projector.revoke_workspace(ws))
        await asyncio.sleep(0)
        assert not projector.start_allowed("worker", "index", "plugin", ws)
        assert not retiring.done() and not stop_entered.is_set()
        release.set()
        if not cancel_caller:
            await starting
        await retiring
        assert stop_entered.is_set() and not owners.leases()
        await projector.project_workspace(ws)
        assert not owners.leases()
    finally:
        release.set()
        await asyncio.gather(
            starting,
            *([retiring] if retiring else []),
            return_exceptions=True,
        )
