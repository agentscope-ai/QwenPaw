# -*- coding: utf-8 -*-
"""The console chat SSE responses must opt out of nginx response buffering."""
from __future__ import annotations

from qwenpaw.app.routers.console import _empty_sse_response


def test_empty_sse_response_disables_proxy_buffering() -> None:
    response = _empty_sse_response()
    assert response.headers["x-accel-buffering"] == "no"
