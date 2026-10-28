# -*- coding: utf-8 -*-
"""Preserved low-level HTTP timeout normalization assertions."""

from datetime import timedelta

import pytest
from mcp_plugin_under_test.mcp_stateful_client import HttpStatefulClient
from mcp_plugin_under_test.mcp_streamable_http import HttpStatelessClient


@pytest.mark.parametrize(
    "client_cls",
    [HttpStatefulClient, HttpStatelessClient],
)
@pytest.mark.parametrize(
    "timeout,expected_timeout,expected_read",
    [
        (1200, 1200.0, 1200.0),
        (timedelta(seconds=60), 60.0, 300.0),
        (None, 30.0, 300.0),
    ],
)
def test_http_client_timeout_normalization(
    client_cls,
    timeout,
    expected_timeout,
    expected_read,
):
    kwargs = {} if timeout is None else {"timeout": timeout}
    client = client_cls(
        "actions",
        "streamable_http",
        "http://peer.invalid",
        **kwargs,
    )
    assert client.timeout == expected_timeout
    assert client.sse_read_timeout == expected_read
