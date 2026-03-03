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

    monkeypatch.delenv("COPAW_OLLAMA_LIST_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(
        ollama_manager,
        "_ensure_ollama",
        lambda: fake_ollama,
    )

    models = ollama_manager.OllamaModelManager.list_models()

    assert timeout_box["timeout"] == 10.0
    assert [m.name for m in models] == ["qwen2:7b"]


def test_list_models_uses_env_timeout(monkeypatch) -> None:
    timeout_box: dict = {}
    fake_ollama = _make_fake_ollama(timeout_box, {"models": []})

    monkeypatch.setenv("COPAW_OLLAMA_LIST_TIMEOUT_SECONDS", "3.5")
    monkeypatch.setattr(
        ollama_manager,
        "_ensure_ollama",
        lambda: fake_ollama,
    )

    ollama_manager.OllamaModelManager.list_models()

    assert timeout_box["timeout"] == 3.5


def test_list_models_falls_back_on_invalid_env_timeout(monkeypatch) -> None:
    timeout_box: dict = {}
    fake_ollama = _make_fake_ollama(timeout_box, {"models": []})

    monkeypatch.setenv("COPAW_OLLAMA_LIST_TIMEOUT_SECONDS", "abc")
    monkeypatch.setattr(
        ollama_manager,
        "_ensure_ollama",
        lambda: fake_ollama,
    )

    ollama_manager.OllamaModelManager.list_models()

    assert timeout_box["timeout"] == 10.0


def test_list_models_falls_back_on_non_positive_env_timeout(
    monkeypatch,
) -> None:
    timeout_box: dict = {}
    fake_ollama = _make_fake_ollama(timeout_box, {"models": []})

    monkeypatch.setattr(
        ollama_manager,
        "_ensure_ollama",
        lambda: fake_ollama,
    )

    for timeout_value in ("0", "-1"):
        monkeypatch.setenv(
            "COPAW_OLLAMA_LIST_TIMEOUT_SECONDS",
            timeout_value,
        )
        ollama_manager.OllamaModelManager.list_models()
        assert timeout_box["timeout"] == 10.0


def test_list_models_falls_back_on_non_finite_env_timeout(
    monkeypatch,
) -> None:
    timeout_box: dict = {}
    fake_ollama = _make_fake_ollama(timeout_box, {"models": []})

    monkeypatch.setattr(
        ollama_manager,
        "_ensure_ollama",
        lambda: fake_ollama,
    )

    for timeout_value in ("nan", "inf", "-inf"):
        monkeypatch.setenv(
            "COPAW_OLLAMA_LIST_TIMEOUT_SECONDS",
            timeout_value,
        )
        ollama_manager.OllamaModelManager.list_models()
        assert timeout_box["timeout"] == 10.0
