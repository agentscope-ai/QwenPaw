# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from copaw.agents.model_factory import _create_remote_model_instance


class _FakeChatModel:
    def __init__(
        self,
        model_name: str,
        api_key: str,
        stream: bool,
        client_kwargs: dict,
    ) -> None:
        self.model_name = model_name
        self.api_key = api_key
        self.stream = stream
        self.client_kwargs = client_kwargs


def test_openrouter_default_headers_are_forwarded(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_HTTP_REFERER", "https://copaw.local")
    monkeypatch.setenv("OPENROUTER_TITLE", "CoPaw")

    llm_cfg = SimpleNamespace(
        model="openai/gpt-5.2",
        api_key="sk-or-test",
        base_url="https://openrouter.ai/api/v1",
    )

    model = _create_remote_model_instance(llm_cfg, _FakeChatModel)

    assert model.client_kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert model.client_kwargs["default_headers"] == {
        "HTTP-Referer": "https://copaw.local",
        "X-OpenRouter-Title": "CoPaw",
    }
