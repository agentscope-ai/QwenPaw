# -*- coding: utf-8 -*-
"""Durable setup requests are scoped, idempotent and terminal-safe."""

import os

import pytest

from qwenpaw.pawapp.setup import (
    SetupOpenAction,
    SetupResult,
    SetupStore,
)
from qwenpaw.pawapp.setup import store as store_module
from qwenpaw.pawapp.tasks import ProjectRef, TaskScope, TaskStoreError

SCOPE = TaskScope(
    principal_id="alice",
    workspace_id="default",
    app_id="qwenpaw-creator",
)


def _values(expires_at: float, **updates):
    values = {
        "descriptor_digest": "descriptor-digest",
        "entry_id": "video-model",
        "requirement_ids": ("shot-video",),
        "origin_ref": "chat-1",
        "action_id": "create-video",
        "project_ref": ProjectRef(
            app_id="qwenpaw-creator",
            project_id="project-1",
            kind="video",
            revision=2,
        ),
        "expected_revisions": {"shot-video": 3},
        "scopes": ("provider:video",),
        "presentation": "app_entry",
        "expires_at": expires_at,
        "return_target": "chat-1",
    }
    values.update(updates)
    return values


@pytest.mark.asyncio
async def test_create_replays_same_meaning_and_keeps_private_permissions(
    tmp_path,
    monkeypatch,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(store_module.time, "time", lambda: clock[0])
    store = await SetupStore.open(tmp_path / "setup.sqlite3")

    first, replayed = await store.create(
        SCOPE,
        idempotency_key="intent-1",
        values=_values(1000),
    )
    clock[0] = 110
    second, replayed_again = await store.create(
        SCOPE,
        idempotency_key="intent-1",
        values=_values(2000),
    )

    assert not replayed
    assert replayed_again
    assert second.request == first.request
    assert second.request.expires_at == 1000
    assert os.stat(store.path).st_mode & 0o777 == 0o600

    with pytest.raises(TaskStoreError, match="setup_idempotency_conflict"):
        await store.create(
            SCOPE,
            idempotency_key="intent-1",
            values=_values(2000, entry_id="other-entry"),
        )


@pytest.mark.asyncio
async def test_open_and_result_are_idempotent_and_terminal(tmp_path) -> None:
    store = await SetupStore.open(tmp_path / "setup.sqlite3")
    record, _ = await store.create(
        SCOPE,
        idempotency_key="intent-1",
        values=_values(store_module.time.time() + 600),
    )
    action = SetupOpenAction(
        app_id=SCOPE.app_id,
        request_id=record.request.request_id,
        entry_id="video-model",
        presentation="app_entry",
        path="/apps/qwenpaw-creator/models?setup=opaque",
    )
    opened = await store.opened(SCOPE, record.request.request_id, action)
    replayed_open = await store.opened(
        SCOPE,
        record.request.request_id,
        action,
    )
    assert opened.request.state == "opened"
    assert replayed_open.open_action == action

    out_of_scope = SetupResult(
        request_id=record.request.request_id,
        result_id="result-out-of-scope",
        outcome="saved",
        config_revisions={"other-requirement": 1},
    )
    with pytest.raises(TaskStoreError, match="setup_result_scope_mismatch"):
        await store.complete(SCOPE, out_of_scope)

    result = SetupResult(
        request_id=record.request.request_id,
        result_id="result-1",
        outcome="saved",
        changed_requirement_ids=("shot-video",),
        config_revisions={"shot-video": 4},
        public_refs=("model-binding:video@4",),
    )
    saved = await store.complete(SCOPE, result)
    replayed = await store.complete(SCOPE, result)
    assert saved.request.state == "saved"
    assert replayed.result == result

    conflicting = result.model_copy(
        update={"public_refs": ("model-binding:other@4",)},
    )
    with pytest.raises(TaskStoreError, match="setup_result_conflict"):
        await store.complete(SCOPE, conflicting)
    with pytest.raises(TaskStoreError, match="setup_request_closed"):
        await store.cancel(SCOPE, record.request.request_id)


@pytest.mark.asyncio
async def test_cancel_and_expiry_reject_late_results(
    tmp_path,
    monkeypatch,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(store_module.time, "time", lambda: clock[0])
    store = await SetupStore.open(tmp_path / "setup.sqlite3")
    cancelled, _ = await store.create(
        SCOPE,
        idempotency_key="cancel",
        values=_values(200),
    )
    cancelled = await store.cancel(SCOPE, cancelled.request.request_id)
    assert cancelled.request.state == "cancelled"
    assert (
        await store.cancel(SCOPE, cancelled.request.request_id)
    ) == cancelled

    external, _ = await store.create(
        SCOPE,
        idempotency_key="external",
        values=_values(200),
    )
    external_action = SetupOpenAction(
        app_id=SCOPE.app_id,
        request_id=external.request.request_id,
        entry_id="video-model",
        presentation="app_entry",
        path="/apps/qwenpaw-creator/models?setup=external",
    )
    await store.opened(SCOPE, external.request.request_id, external_action)
    waiting = await store.waiting_external(
        SCOPE,
        external.request.request_id,
    )
    replayed_wait = await store.waiting_external(
        SCOPE,
        external.request.request_id,
    )
    assert waiting.request.state == "waiting_external"
    assert replayed_wait == waiting
    await store.cancel(SCOPE, external.request.request_id)
    late_external = SetupResult(
        request_id=external.request.request_id,
        result_id="late-external",
        outcome="saved",
    )
    with pytest.raises(TaskStoreError, match="setup_request_closed"):
        await store.complete(SCOPE, late_external)

    expiring, _ = await store.create(
        SCOPE,
        idempotency_key="expire",
        values=_values(120),
    )
    clock[0] = 121
    expired = await store.get(SCOPE, expiring.request.request_id)
    assert expired.request.state == "expired"
    late = SetupResult(
        request_id=expiring.request.request_id,
        result_id="late",
        outcome="saved",
    )
    with pytest.raises(TaskStoreError, match="setup_request_closed"):
        await store.complete(SCOPE, late)


@pytest.mark.asyncio
async def test_scope_mismatch_is_indistinguishable_from_missing(
    tmp_path,
) -> None:
    store = await SetupStore.open(tmp_path / "setup.sqlite3")
    record, _ = await store.create(
        SCOPE,
        idempotency_key="intent-1",
        values=_values(store_module.time.time() + 600),
    )
    other = SCOPE.model_copy(update={"principal_id": "bob"})

    with pytest.raises(TaskStoreError, match="setup_request_not_found"):
        await store.get(other, record.request.request_id)
