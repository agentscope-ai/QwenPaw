# -*- coding: utf-8 -*-
"""Cancellation persistence must respect ephemeral internal requests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.agents.acp.meta import ACP_EPHEMERAL_META_KEY
from qwenpaw.runtime.runtime import Runtime


@pytest.mark.asyncio
async def test_ephemeral_cancel_does_not_create_hidden_session() -> None:
    class FailIfSaved:
        async def save_session_state(self, **_kwargs) -> None:
            raise AssertionError("ephemeral request must not be saved")

    ctx = SimpleNamespace(
        request=SimpleNamespace(
            request_context={ACP_EPHEMERAL_META_KEY: True},
        ),
        agent=SimpleNamespace(state_dict=lambda: {"state": {}}),
        workspace=SimpleNamespace(session=FailIfSaved()),
    )
    runtime = Runtime(workspace=object(), app_services=None)

    await runtime._try_save_on_cancel(ctx)  # pylint: disable=protected-access
