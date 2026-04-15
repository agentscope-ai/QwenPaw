# -*- coding: utf-8 -*-
from __future__ import annotations

import types
from types import SimpleNamespace

import pytest

import qwenpaw.observability.langfuse as langfuse_module
from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper


class _FakeGeneration:
    def __init__(self) -> None:
        self.end_calls: list[dict] = []

    def end(self, **kwargs):
        self.end_calls.append(kwargs)


class _FakeTrace:
    def __init__(self, generation: _FakeGeneration) -> None:
        self._generation = generation

    def generation(self, **_kwargs):
        return self._generation


class _FakeLangfuseClient:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.generation = _FakeGeneration()
        self.trace_calls: list[dict] = []
        self.flush_calls = 0

    def trace(self, **kwargs):
        self.trace_calls.append(kwargs)
        return _FakeTrace(self.generation)

    def flush(self):
        self.flush_calls += 1


class _FakeModel:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.model_name = "gpt-test"
        self.stream = False
        self.should_fail = should_fail

    async def __call__(self, **kwargs):
        _ = kwargs
        if self.should_fail:
            raise RuntimeError("boom")
        usage = SimpleNamespace(input_tokens=3, output_tokens=5, total_tokens=8)
        return SimpleNamespace(content=[{"type": "text", "text": "ok"}], usage=usage)


def _reset_observer_singleton(monkeypatch) -> None:
    monkeypatch.setattr(langfuse_module, "_OBSERVER", None)
    monkeypatch.setattr(langfuse_module, "_OBSERVER_LOADED", False)


def test_langfuse_disabled_without_env(monkeypatch) -> None:
    _reset_observer_singleton(monkeypatch)
    monkeypatch.delenv("QWENPAW_LANGFUSE_ENABLED", raising=False)
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    observer = langfuse_module.get_langfuse_observer()

    assert observer is None


def test_langfuse_enabled_but_missing_keys_degrades(monkeypatch) -> None:
    _reset_observer_singleton(monkeypatch)
    monkeypatch.setenv("QWENPAW_LANGFUSE_ENABLED", "true")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    observer = langfuse_module.get_langfuse_observer()

    assert observer is None


def test_langfuse_success_records_generation(monkeypatch) -> None:
    _reset_observer_singleton(monkeypatch)
    monkeypatch.setenv("QWENPAW_LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")

    fake_module = types.ModuleType("langfuse")
    client_holder: dict[str, _FakeLangfuseClient] = {}

    def _factory(**kwargs):
        client = _FakeLangfuseClient(**kwargs)
        client_holder["client"] = client
        return client

    setattr(fake_module, "Langfuse", _factory)
    monkeypatch.setattr(langfuse_module.importlib, "import_module", lambda _: fake_module)

    observer = langfuse_module.get_langfuse_observer()
    assert observer is not None

    context = observer.start_generation(
        provider_id="openai",
        model_name="gpt-test",
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
    )
    usage = SimpleNamespace(input_tokens=3, output_tokens=2, total_tokens=5)
    observer.finish_success(context, response=SimpleNamespace(content="ok"), usage=usage)

    client = client_holder["client"]
    assert client.kwargs["public_key"] == "pk-test"
    assert client.kwargs["secret_key"] == "sk-test"
    assert client.kwargs["host"] == "https://cloud.langfuse.com"
    assert len(client.trace_calls) == 1
    assert len(client.generation.end_calls) == 1
    assert client.generation.end_calls[0]["usage_details"] == {
        "input": 3,
        "output": 2,
        "total": 5,
    }
    assert client.flush_calls == 1


async def test_wrapper_records_langfuse_error(monkeypatch) -> None:
    class _FakeObserver:
        def __init__(self) -> None:
            self.error_called = False

        def start_generation(self, **_kwargs):
            return "ctx"

        def finish_success(self, *_args, **_kwargs):
            raise AssertionError("should not be called")

        def finish_error(self, context, *, error):
            assert context == "ctx"
            assert isinstance(error, RuntimeError)
            self.error_called = True

    fake_observer = _FakeObserver()
    monkeypatch.setattr(
        "qwenpaw.token_usage.model_wrapper.get_langfuse_observer",
        lambda: fake_observer,
    )

    wrapper = TokenRecordingModelWrapper("openai", _FakeModel(should_fail=True))

    with pytest.raises(RuntimeError, match="boom"):
        await wrapper(messages=[{"role": "user", "content": "hi"}])

    assert fake_observer.error_called is True
