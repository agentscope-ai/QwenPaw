# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path

import pytest

from copaw.providers.openai_auth import (
    LoginSession,
    OpenAIAuthHelper,
    load_provider_auth_from_codex_home,
)
from copaw.providers.openai_provider import OpenAIProvider
from copaw.providers.provider import ProviderAuth

pytestmark = pytest.mark.anyio


def test_load_provider_auth_from_codex_home_raises_for_missing_file(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        load_provider_auth_from_codex_home(tmp_path)


class _FakeStdout:
    async def readline(self) -> bytes:
        return b""


class _FakeProcess:
    def __init__(self, return_code: int) -> None:
        self.stdout = _FakeStdout()
        self._return_code = return_code

    async def wait(self) -> int:
        return self._return_code


async def test_watch_session_failure_restores_previous_auth(
    tmp_path: Path,
) -> None:
    helper = OpenAIAuthHelper()
    provider = OpenAIProvider(
        id="openai",
        name="OpenAI",
        api_key="sk-test",
        auth=ProviderAuth(mode="api_key", status="authorized"),
        auth_modes=["api_key", "oauth_browser"],
    )
    provider.auth = provider.auth.model_copy(
        update={
            "mode": "oauth_browser",
            "status": "authorizing",
        },
    )

    persisted: list[ProviderAuth] = []
    session = LoginSession(
        session_id="session-1",
        provider_id="openai",
        codex_home=tmp_path / "codex-home",
        process=_FakeProcess(return_code=1),
        previous_auth=ProviderAuth(mode="api_key", status="authorized"),
    )
    session.codex_home.mkdir(parents=True, exist_ok=True)

    await helper._watch_session(
        session,
        provider,
        lambda current: persisted.append(current.auth.model_copy(deep=True)),
    )

    assert session.status == "error"
    assert provider.auth.mode == "api_key"
    assert provider.auth.status == "authorized"
    assert provider.api_key == "sk-test"
    assert persisted[-1].mode == "api_key"
    assert session.codex_home.exists() is False
