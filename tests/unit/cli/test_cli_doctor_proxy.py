# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from functools import partial

import httpx
import pytest

from qwenpaw.cli import doctor_cmd


@pytest.mark.parametrize(
    "url,trust_env",
    [
        ("http://127.1.2.3:8088/api/version", False),
        ("http://192.168.1.10:8088/api/version", True),
    ],
)
def test_doctor_http_get_preserves_proxy_policy(
    monkeypatch,
    url,
    trust_env,
) -> None:
    captured = {}
    real_client = httpx.Client

    def create_client(**kwargs):
        captured.update(kwargs)
        return real_client(**kwargs)

    monkeypatch.setattr(
        httpx,
        "Client",
        partial(
            create_client,
            transport=httpx.MockTransport(lambda _: httpx.Response(200)),
        ),
    )
    doctor_cmd._http_get(url, timeout=2.0)
    assert captured["trust_env"] is trust_env
