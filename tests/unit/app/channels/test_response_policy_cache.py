# -*- coding: utf-8 -*-
"""Guards for the host-side response policy cache."""

# pylint: disable=protected-access

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.agents.tools.agent_management import _json_safe_channel_meta
from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy
from qwenpaw.channel_protocol.response_policy import ResponsePolicy


class _Process:
    def __init__(self, value=None):
        self.value = value or {
            "streaming": False,
            "prepare": False,
            "completion_reaction": False,
        }
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method, params, **_kwargs):
        self.calls.append((method, params))
        return self.value


def _proxy(process: _Process, route: str = "route-1") -> IsolatedChannelProxy:
    proxy = object.__new__(IsolatedChannelProxy)
    proxy.channel_process = process
    proxy.descriptor = SimpleNamespace(capabilities=())
    proxy.streaming_enabled = True
    proxy._identity = lambda: SimpleNamespace(to_mapping=lambda: {"c": "x"})

    async def _route(_to_handle, _meta):
        return route

    proxy._route = _route
    return proxy


@pytest.mark.asyncio
async def test_response_policy_reuses_local_dto_cache() -> None:
    process = _Process()
    proxy = _proxy(process)
    cached = ResponsePolicy(prepare=True)
    meta = {"_response_policy": ("route-1", cached)}

    policy = await proxy._response_policy("handle", meta)

    assert policy is cached
    assert process.calls == []


@pytest.mark.asyncio
async def test_send_parts_survives_serialized_policy_cache() -> None:
    process = _Process()
    proxy = _proxy(process)
    sent: list[list[dict]] = []

    async def _send_operation(_to_handle, _meta, _operation, **fields):
        sent.append(fields["content_parts"])
        return "ok"

    proxy._send_operation = _send_operation
    meta = _json_safe_channel_meta(
        {
            "_response_policy": (
                "route-1",
                ResponsePolicy(streaming=False, prepare=False),
            ),
        },
    )
    assert meta == {"_response_policy": ["route-1"]}

    result = await proxy._send_parts_owned(
        "handle",
        [{"type": "file", "file_url": "file:///tmp/报告.txt"}],
        meta,
    )

    assert result == "ok"
    assert sent == [[{"type": "file", "file_url": "file:///tmp/报告.txt"}]]
    route, policy = meta["_response_policy"]
    assert route == "route-1"
    assert isinstance(policy, ResponsePolicy)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cached",
    [
        ["route-1", "ResponsePolicy(streaming=False, prepare=True)"],
        ("route-1", "ResponsePolicy(streaming=False, prepare=True)"),
        ("other-route", ResponsePolicy(prepare=True)),
    ],
)
async def test_response_policy_ignores_serialized_or_stale_cache(
    cached,
) -> None:
    process = _Process()
    proxy = _proxy(process)
    meta = {"_response_policy": cached}

    policy = await proxy._response_policy("handle", meta)

    assert isinstance(policy, ResponsePolicy)
    assert [call[0] for call in process.calls] == [
        "channel.response.describe",
    ]
    assert meta["_response_policy"] == ("route-1", policy)
