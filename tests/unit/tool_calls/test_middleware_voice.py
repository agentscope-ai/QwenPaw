from types import SimpleNamespace

import pytest

from qwenpaw.tool_calls._middleware import ToolCoordinatorMiddleware


class _Coordinator:
    def __init__(self) -> None:
        self.kwargs = None

    async def execute(self, **kwargs):
        self.kwargs = kwargs
        yield "done"


@pytest.mark.asyncio
async def test_voice_turn_uses_the_same_configured_offload_policy():
    coordinator = _Coordinator()
    middleware = ToolCoordinatorMiddleware(coordinator)
    agent = SimpleNamespace(_request_context={"source": "realtime_voice"})

    events = [
        event
        async for event in middleware.on_acting(
            agent,
            {"tool_call": SimpleNamespace(id="call-1")},
            lambda: None,
        )
    ]

    assert events == ["done"]
    assert "offload_on_deadline" not in coordinator.kwargs


@pytest.mark.asyncio
async def test_ordinary_turn_uses_configured_offload_policy():
    coordinator = _Coordinator()
    middleware = ToolCoordinatorMiddleware(coordinator)
    agent = SimpleNamespace(_request_context={})

    _ = [
        event
        async for event in middleware.on_acting(
            agent,
            {"tool_call": SimpleNamespace(id="call-1")},
            lambda: None,
        )
    ]

    assert "offload_on_deadline" not in coordinator.kwargs
