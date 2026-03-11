# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from copaw.providers import ollama_manager


def _make_fake_ollama(timeout_box: dict, response: dict):
    class _FakeClient:
        def __init__(self, *, timeout=None, **kwargs):
            _ = kwargs
            timeout_box["timeout"] = timeout

        def list(self):
            return response

    return SimpleNamespace(Client=_FakeClient)


def test_list_models_uses_default_timeout(monkeypatch) -> None:
    timeout_box: dict = {}
    fake_ollama = _make_fake_ollama(
        timeout_box,
        {"models": [{"model": "qwen2:7b", "size": 1}]},
    )

    monkeypatch.delenv("COPAW_MODEL_PROVIDER_CHECK_TIMEOUT", raising=False)
    monkeypatch.setattr(
        ollama_manager,
        "_ensure_ollama",
        lambda: fake_ollama,
    )

    models = ollama_manager.OllamaModelManager.list_models()

    assert timeout_box["timeout"] == 5.0
    assert [m.name for m in models] == ["qwen2:7b"]
