# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Retryable transport custody beyond the public host lifecycle checks."""

import asyncio

import httpx
import pytest

import mcp_plugin_under_test.mcp_stateful_client as stateful
from mcp_plugin_under_test.mcp_streamable_http import (
    HttpAutoClient,
    HttpStatelessClient,
)


async def test_auto_failed_legacy_open_keeps_impl_for_close_retry(monkeypatch):
    instances = []
    allow = False

    class Legacy(stateful.HttpStatefulClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.live = True
            self.is_connected = True
            instances.append(self)

        async def connect(self, timeout=30.0):
            raise ConnectionError("synthetic partial legacy open")

        async def close(self, ignore_errors=True):
            if not allow:
                if not ignore_errors:
                    raise RuntimeError("synthetic legacy close blocked")
                return
            self.live = False
            self.is_connected = False

    monkeypatch.setattr(stateful, "HttpStatefulClient", Legacy)
    client = HttpAutoClient(
        "legacy",
        "streamable_http",
        "https://peer.invalid/mcp",
        http_transport=httpx.MockTransport(lambda _: httpx.Response(404)),
    )
    try:
        with pytest.raises(ConnectionError):
            await client.connect()
        assert len(instances) == 1
        assert client._impl is instances[0]
        with pytest.raises(RuntimeError, match="close blocked"):
            await client.close(ignore_errors=False)
        assert client._impl is instances[0] and instances[0].live
        allow = True
        await client.close(ignore_errors=False)
        assert client._impl is None and not instances[0].live
    finally:
        allow = True
        await client.close(ignore_errors=False)


@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_modern_http_close_failure_keeps_client_for_retry(failure):
    entered = asyncio.Event()
    allow = False

    class HTTP:
        async def aclose(self):
            if not allow:
                if failure == "error":
                    raise RuntimeError("synthetic HTTP close failed")
                entered.set()
                await asyncio.Event().wait()

    client = HttpStatelessClient(
        "modern",
        "streamable_http",
        "https://peer.invalid",
    )
    resource = HTTP()
    client._http = resource
    task = None
    try:
        if failure == "error":
            with pytest.raises(RuntimeError):
                await client.close(ignore_errors=False)
        else:
            task = asyncio.create_task(client.close(ignore_errors=False))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
        assert client._http is resource
        allow = True
        await client.close(ignore_errors=False)
        assert client._http is None
    finally:
        allow = True
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait_for(
                asyncio.gather(task, return_exceptions=True),
                1,
            )
        await client.close(ignore_errors=False)
