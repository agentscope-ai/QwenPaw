# -*- coding: utf-8 -*-
"""Error normalization privacy contract tests."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from qwenpaw.app.chats import query_error_dump
from qwenpaw.hooks.error.error_hook import ErrorNormalizeHook


@pytest.mark.asyncio
async def test_error_dump_path_is_logged_but_not_exposed_to_chat(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    private_path = (
        r"C:\Users\example\AppData\Local\Temp\qwenpaw_query_error.json"
    )
    monkeypatch.setattr(
        query_error_dump,
        "write_query_error_dump",
        lambda *_args, **_kwargs: private_path,
    )
    context = SimpleNamespace(
        error=RuntimeError("provider failed"),
        agent=None,
        request={"input": []},
        extras={},
    )

    await ErrorNormalizeHook().run(context)

    assert "provider failed" in context.extras["_error_text"]
    assert private_path not in context.extras["_error_text"]
    assert "[dump:" not in context.extras["_error_text"]
    assert private_path in caplog.text
