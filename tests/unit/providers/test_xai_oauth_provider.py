# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for ``qwenpaw.providers.xai_oauth_provider.XaiOAuthProvider``.

Covers the four overridden entry points (``check_connection``,
``fetch_models``, ``check_model_connection``,
``get_chat_model_instance``).  All network and disk interactions are
stubbed — we only care that the standalone provider routes through
:class:`XaiAuth` + :class:`XaiOAuthChatModel`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import qwenpaw.providers.xai_oauth_provider as xai_provider_module
from qwenpaw.providers.xai_oauth_model import XaiOAuthChatModel
from qwenpaw.providers.xai_oauth_provider import XaiOAuthProvider


# ---------------------------------------------------------------- #
# Fakes                                                            #
# ---------------------------------------------------------------- #


class _FakeAuth:
    def __init__(
        self,
        *,
        base_url: str = "https://api.x.ai/v1",
        access_token: str = "fresh-token",
        ensure_fresh_exc: Exception | None = None,
    ) -> None:
        self.base_url = base_url
        self._access_token = access_token
        self._ensure_fresh_exc = ensure_fresh_exc
        self.ensure_fresh_calls = 0

    async def ensure_fresh(self) -> SimpleNamespace:
        self.ensure_fresh_calls += 1
        if self._ensure_fresh_exc is not None:
            raise self._ensure_fresh_exc
        return SimpleNamespace(access_token=self._access_token)


def _make_provider() -> XaiOAuthProvider:
    return XaiOAuthProvider(
        id="xai-oauth",
        name="Grok (xAI OAuth)",
        base_url="https://api.x.ai/v1",
        api_key="oauth",
        api_key_prefix="",
        require_api_key=False,
        models=[],
        chat_model="OpenAIChatModel",
        freeze_url=True,
    )


def _patch_auth(
    monkeypatch: pytest.MonkeyPatch,
    auth: _FakeAuth,
) -> None:
    """Replace ``XaiAuth()`` constructor so ``_get_auth`` returns the fake."""
    monkeypatch.setattr(
        "qwenpaw.providers.xai_auth.XaiAuth",
        lambda *_args, **_kwargs: auth,
    )


# ---------------------------------------------------------------- #
# check_connection                                                 #
# ---------------------------------------------------------------- #


class TestCheckConnection:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        auth = _FakeAuth()
        _patch_auth(monkeypatch, auth)

        # _bearer_client returns an AsyncOpenAI — stub it.
        models_list_calls: list[float | None] = []

        class _FakeModels:
            async def list(self, timeout: float | None = None) -> Any:
                models_list_calls.append(timeout)
                return SimpleNamespace(data=[])

        fake_client = SimpleNamespace(models=_FakeModels())
        provider = _make_provider()
        monkeypatch.setattr(
            provider,
            "_bearer_client",
            lambda bearer, timeout: fake_client,
        )

        ok, msg = await provider.check_connection(timeout=2.5)

        assert ok is True
        assert msg == ""
        assert auth.ensure_fresh_calls == 1
        assert models_list_calls == [2.5]

    async def test_file_not_found_returns_relogin_message(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        auth = _FakeAuth(ensure_fresh_exc=FileNotFoundError("no auth.json"))
        _patch_auth(monkeypatch, auth)

        provider = _make_provider()
        ok, msg = await provider.check_connection()

        assert ok is False
        assert "not set up" in msg

    async def test_refresh_failure_returns_false(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        auth = _FakeAuth(ensure_fresh_exc=RuntimeError("refresh broke"))
        _patch_auth(monkeypatch, auth)

        provider = _make_provider()
        ok, msg = await provider.check_connection()

        assert ok is False
        assert "refresh failed" in msg

    async def test_api_error_on_models_list(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        auth = _FakeAuth()
        _patch_auth(monkeypatch, auth)

        class _FakeModels:
            async def list(self, timeout: float | None = None) -> Any:
                raise xai_provider_module.APIError(
                    "boom",
                    request=None,  # type: ignore[arg-type]
                    body=None,
                )

        fake_client = SimpleNamespace(models=_FakeModels())
        provider = _make_provider()
        monkeypatch.setattr(
            provider,
            "_bearer_client",
            lambda bearer, timeout: fake_client,
        )

        ok, msg = await provider.check_connection()

        assert ok is False
        assert "xAI API error" in msg


# ---------------------------------------------------------------- #
# fetch_models                                                     #
# ---------------------------------------------------------------- #


class TestFetchModels:
    async def test_returns_normalized_models(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        auth = _FakeAuth()
        _patch_auth(monkeypatch, auth)

        rows = [
            SimpleNamespace(id="grok-4", name="Grok 4"),
            SimpleNamespace(id="grok-4-fast", name="Grok 4 Fast"),
            SimpleNamespace(id="grok-4", name="dup"),  # de-duped
        ]

        class _FakeModels:
            async def list(self, timeout: float | None = None) -> Any:
                # ``timeout`` mirrors the real openai-python signature
                # so the SDK call from XaiOAuthProvider compiles —
                # the fake just returns canned data.
                del timeout
                return SimpleNamespace(data=rows)

        fake_client = SimpleNamespace(models=_FakeModels())
        provider = _make_provider()
        monkeypatch.setattr(
            provider,
            "_bearer_client",
            lambda bearer, timeout: fake_client,
        )

        models = await provider.fetch_models(timeout=5)

        assert [m.id for m in models] == ["grok-4", "grok-4-fast"]
        assert [m.name for m in models] == ["Grok 4", "Grok 4 Fast"]

    async def test_returns_empty_list_on_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Discovery failure must not crash the caller — UI falls back
        # to whatever extra_models the user already saved.
        auth = _FakeAuth(ensure_fresh_exc=RuntimeError("oops"))
        _patch_auth(monkeypatch, auth)

        provider = _make_provider()
        models = await provider.fetch_models()

        assert models == []


# ---------------------------------------------------------------- #
# check_model_connection                                           #
# ---------------------------------------------------------------- #


class TestCheckModelConnection:
    async def test_empty_model_id_rejected(self) -> None:
        provider = _make_provider()
        ok, msg = await provider.check_model_connection("", timeout=1)
        assert ok is False
        assert "Empty model ID" in msg

    async def test_success_pings_one_token(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        auth = _FakeAuth()
        _patch_auth(monkeypatch, auth)

        captured: list[dict[str, Any]] = []

        class _FakeStream:
            def __aiter__(self) -> "_FakeStream":
                return self

            async def __anext__(self) -> None:
                raise StopAsyncIteration

        class _FakeCompletions:
            async def create(self, **kwargs: Any) -> _FakeStream:
                captured.append(kwargs)
                return _FakeStream()

        # Inject our fake client into XaiOAuthChatModel by monkey-
        # patching the wrapped create at the module level: the cleanest
        # way is to override XaiOAuthChatModel construction itself.
        class _FakeModel:
            def __init__(self, **_: Any) -> None:
                self.client = SimpleNamespace(
                    chat=SimpleNamespace(completions=_FakeCompletions()),
                )

        monkeypatch.setattr(
            "qwenpaw.providers.xai_oauth_model.XaiOAuthChatModel",
            _FakeModel,
        )

        provider = _make_provider()
        ok, msg = await provider.check_model_connection("grok-4", timeout=3)

        assert ok is True
        assert msg == ""
        assert len(captured) == 1
        assert captured[0]["model"] == "grok-4"
        assert captured[0]["max_tokens"] == 1
        assert captured[0]["stream"] is True

    async def test_file_not_found_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # XaiAuth() itself raises FileNotFoundError when auth.json is
        # missing — `_get_auth()` calls the constructor each time.
        def _raise(*_a: Any, **_kw: Any) -> Any:
            raise FileNotFoundError("auth.json missing")

        monkeypatch.setattr(
            "qwenpaw.providers.xai_auth.XaiAuth",
            _raise,
        )

        provider = _make_provider()
        ok, msg = await provider.check_model_connection("grok-4")

        assert ok is False
        assert "not set up" in msg

    async def test_model_call_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        auth = _FakeAuth()
        _patch_auth(monkeypatch, auth)

        class _FakeCompletions:
            async def create(self, **_kwargs: Any) -> Any:
                raise RuntimeError("model exploded")

        class _FakeModel:
            def __init__(self, **_: Any) -> None:
                self.client = SimpleNamespace(
                    chat=SimpleNamespace(completions=_FakeCompletions()),
                )

        monkeypatch.setattr(
            "qwenpaw.providers.xai_oauth_model.XaiOAuthChatModel",
            _FakeModel,
        )

        provider = _make_provider()
        ok, msg = await provider.check_model_connection("grok-4")

        assert ok is False
        assert "model check failed" in msg


# ---------------------------------------------------------------- #
# get_chat_model_instance                                          #
# ---------------------------------------------------------------- #


class TestGetChatModelInstance:
    def test_returns_xai_oauth_chat_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        auth = _FakeAuth()
        _patch_auth(monkeypatch, auth)

        provider = _make_provider()
        model = provider.get_chat_model_instance("grok-4")

        assert isinstance(model, XaiOAuthChatModel)

    def test_raises_value_error_when_auth_file_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # XaiAuth() raises FileNotFoundError when ~/.xai/auth.json is
        # absent.  get_chat_model_instance must convert that to ValueError
        # so create_model_and_formatter() call sites (which only catch
        # ValueError/AppBaseException) surface a clean "please log in"
        # error in the UI instead of crashing the agent runtime.
        def _raise(*_a: Any, **_kw: Any) -> Any:
            raise FileNotFoundError("auth.json missing")

        monkeypatch.setattr("qwenpaw.providers.xai_auth.XaiAuth", _raise)

        provider = _make_provider()
        with pytest.raises(ValueError, match="qwenpaw xai login"):
            provider.get_chat_model_instance("grok-4")

    def test_passes_through_generate_kwargs(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # ``get_effective_generate_kwargs`` is on the parent and merges
        # provider-level defaults with per-model overrides; the
        # standalone provider shouldn't drop them when building the model.
        auth = _FakeAuth()
        _patch_auth(monkeypatch, auth)

        provider = _make_provider()
        provider.generate_kwargs = {"temperature": 0.4}

        # XaiOAuthChatModel is imported lazily inside the method, so
        # we have to patch the source module to intercept construction.
        import qwenpaw.providers.xai_oauth_model as xom_module

        captured: dict[str, Any] = {}
        original = xom_module.XaiOAuthChatModel

        def _spy(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return original(**kwargs)

        monkeypatch.setattr(xom_module, "XaiOAuthChatModel", _spy)

        provider.get_chat_model_instance("grok-4")

        assert captured["model_name"] == "grok-4"
        assert captured["stream"] is True
        assert captured["generate_kwargs"] == {"temperature": 0.4}


# ---------------------------------------------------------------- #
# _bearer_client                                                   #
# ---------------------------------------------------------------- #


class TestBearerClient:
    def test_includes_custom_headers(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def _spy(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return SimpleNamespace(**kwargs)

        monkeypatch.setattr(xai_provider_module, "AsyncOpenAI", _spy)

        provider = _make_provider()
        provider.custom_headers = {"X-Account": "qwenpaw"}
        provider._bearer_client(bearer="abc", timeout=3)

        assert captured["api_key"] == "abc"
        assert captured["base_url"] == "https://api.x.ai/v1"
        assert captured["timeout"] == 3
        assert captured["default_headers"] == {"X-Account": "qwenpaw"}

    def test_no_custom_headers_omits_header_kwarg(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def _spy(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return SimpleNamespace(**kwargs)

        monkeypatch.setattr(xai_provider_module, "AsyncOpenAI", _spy)

        provider = _make_provider()
        provider._bearer_client(bearer="abc", timeout=3)

        assert "default_headers" not in captured
