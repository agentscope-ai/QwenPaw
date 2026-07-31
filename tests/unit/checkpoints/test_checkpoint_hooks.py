# -*- coding: utf-8 -*-
"""Checkpoint hook scheduling behavior."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.agents.acp.meta import ACP_EPHEMERAL_META_KEY
from qwenpaw.checkpoints.hooks import CheckpointAutoSnapshotHook
from qwenpaw.checkpoints.runtime import RUNTIME
from qwenpaw.hooks.session.signals import SESSION_SAVE_SUCCEEDED_KEY

pytestmark = [pytest.mark.unit, pytest.mark.p1]


def _ctx(*, persisted: bool | None, ephemeral: bool = False):
    extras = {}
    if persisted is not None:
        extras[SESSION_SAVE_SUCCEEDED_KEY] = persisted
    return SimpleNamespace(
        request=SimpleNamespace(
            request_context={ACP_EPHEMERAL_META_KEY: ephemeral},
            user_id="user",
            channel="console",
        ),
        workspace=object(),
        session_id="session",
        input_msgs=[
            SimpleNamespace(get_text_content=lambda: "hello"),
        ],
        extras=extras,
    )


async def test_auto_snapshot_requires_successfully_persisted_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[dict] = []

    async def schedule(*_args, **kwargs) -> None:
        scheduled.append(kwargs)

    monkeypatch.setattr(RUNTIME, "schedule_auto_snapshot", schedule)

    await CheckpointAutoSnapshotHook().run(_ctx(persisted=True))

    assert scheduled == [
        {
            "session_id": "session",
            "user_id": "user",
            "channel": "console",
            "query_text": "hello",
        },
    ]


@pytest.mark.parametrize(
    ("persisted", "ephemeral"),
    [
        (None, False),
        (False, False),
        (False, True),
    ],
)
async def test_auto_snapshot_skips_unpersisted_and_ephemeral_requests(
    monkeypatch: pytest.MonkeyPatch,
    persisted: bool | None,
    ephemeral: bool,
) -> None:
    scheduled = False

    async def schedule(*_args, **_kwargs) -> None:
        nonlocal scheduled
        scheduled = True

    monkeypatch.setattr(RUNTIME, "schedule_auto_snapshot", schedule)

    await CheckpointAutoSnapshotHook().run(
        _ctx(persisted=persisted, ephemeral=ephemeral),
    )

    assert scheduled is False


def test_auto_snapshot_declares_session_save_dependency() -> None:
    assert CheckpointAutoSnapshotHook.after == ("session_save",)
