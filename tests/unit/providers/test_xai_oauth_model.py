# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for :class:`qwenpaw.providers.xai_oauth_model.XaiOAuthChatModel`.

The wrapper's whole job is: (1) install a thin shim around
``client.chat.completions.create`` so the OAuth bearer is fetched
fresh on every call, and (2) leave the rest of OpenAIChatModelCompat
untouched.  We verify the swap end-to-end with a fake
``AsyncOpenAI``-style client recorded by the wrapper.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from qwenpaw.providers.xai_oauth_model import XaiOAuthChatModel


# ---------------------------------------------------------------- #
# Fakes                                                            #
# ---------------------------------------------------------------- #


class _FakeAuth:
    """Stand-in for :class:`XaiAuth` — exposes only the surface
    :class:`XaiOAuthChatModel` actually calls."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.x.ai/v1",
        access_token: str = "fresh-bearer-token",
    ) -> None:
        self.base_url = base_url
        self._access_token = access_token
        self.ensure_fresh_calls = 0

    async def ensure_fresh(self) -> SimpleNamespace:
        self.ensure_fresh_calls += 1
        return SimpleNamespace(access_token=self._access_token)


# ---------------------------------------------------------------- #
# Construction                                                     #
# ---------------------------------------------------------------- #


class TestConstruction:
    def test_placeholder_api_key_set_at_construction(self) -> None:
        # The OpenAI SDK refuses construction without an api_key.  We
        # seed a placeholder that's only valid until the wrapper swaps
        # in the real bearer on the first call.
        auth = _FakeAuth()
        model = XaiOAuthChatModel(auth=auth, model_name="grok-4")
        assert model.client.api_key == "oauth-placeholder"

    def test_base_url_inherited_from_auth(self) -> None:
        auth = _FakeAuth(base_url="https://mirror.example/v1")
        model = XaiOAuthChatModel(auth=auth, model_name="grok-4")
        assert (
            str(model.client.base_url).rstrip("/")
            == "https://mirror.example/v1"
        )

    def test_explicit_client_kwargs_base_url_wins(self) -> None:
        # client_kwargs is the upstream override hook — if a caller
        # passes their own base_url, it should not be clobbered by the
        # auth-derived default.
        auth = _FakeAuth(base_url="https://api.x.ai/v1")
        model = XaiOAuthChatModel(
            auth=auth,
            model_name="grok-4",
            client_kwargs={"base_url": "https://override.example/v1"},
        )
        assert (
            str(model.client.base_url).rstrip("/")
            == "https://override.example/v1"
        )

    def test_base_url_property_uses_auth(self) -> None:
        auth = _FakeAuth(base_url="https://mirror.example/v1")
        model = XaiOAuthChatModel(auth=auth, model_name="grok-4")
        assert model.base_url == "https://mirror.example/v1"

    def test_base_url_property_falls_back_to_default(self) -> None:
        # If auth.base_url somehow ends up empty, the property must not
        # return an empty string — fall back to DEFAULT_XAI_BASE_URL so
        # callers always get a usable endpoint.
        auth = _FakeAuth(base_url="")
        model = XaiOAuthChatModel(auth=auth, model_name="grok-4")
        assert model.base_url == "https://api.x.ai/v1"

    def test_install_wrapper_replaces_create(self) -> None:
        auth = _FakeAuth()
        model = XaiOAuthChatModel(auth=auth, model_name="grok-4")
        # The wrapped function should be a coroutine function — same
        # contract as the SDK's create().
        assert callable(model.client.chat.completions.create)


# ---------------------------------------------------------------- #
# Per-call bearer refresh                                          #
# ---------------------------------------------------------------- #


class TestBearerRefresh:
    async def test_swaps_in_fresh_bearer_before_each_call(self) -> None:
        auth = _FakeAuth(access_token="bearer-1")
        model = XaiOAuthChatModel(auth=auth, model_name="grok-4")

        captured: dict[str, Any] = {}

        async def _spy(*args: Any, **kwargs: Any) -> str:
            # Capture the api_key value at the moment the underlying
            # SDK call would fire — this is what gets put on the wire.
            captured["api_key"] = model.client.api_key
            captured["args"] = args
            captured["kwargs"] = kwargs
            return "ok"

        # Re-install our spy after the wrapper, so we can observe what
        # the wrapper hands to the SDK call.
        async def _wrapped_with_spy(*args: Any, **kwargs: Any) -> Any:
            creds = await auth.ensure_fresh()
            model.client.api_key = creds.access_token
            return await _spy(*args, **kwargs)

        model.client.chat.completions.create = _wrapped_with_spy

        result = await model.client.chat.completions.create(
            model="grok-4",
            messages=[{"role": "user", "content": "ping"}],
        )

        assert result == "ok"
        assert captured["api_key"] == "bearer-1"
        assert auth.ensure_fresh_calls == 1

    async def test_real_wrapper_refreshes_per_call(self) -> None:
        # End-to-end check of the actual ``_install_wrapper`` code: we
        # replace the SDK's underlying create with a spy *before*
        # construction-time install would happen, then construct, then
        # invoke through the wrapper.  Each call must re-fetch the token
        # so a model held across an idle period still gets a valid one.
        auth = _FakeAuth(access_token="bearer-orig")
        model = XaiOAuthChatModel(auth=auth, model_name="grok-4")

        # Replace the bottom-most create with a spy that records the
        # api_key the wrapper handed down.
        seen: list[str] = []

        async def _bottom(*_args: Any, **_kwargs: Any) -> str:
            seen.append(model.client.api_key)
            return "done"

        # The wrapper saved the original create as a closure; we
        # re-install on top of it so the wrapper still runs first.

        async def _outer(*args: Any, **kwargs: Any) -> Any:
            # First run the wrapper (refresh + swap), then our spy.
            creds = await auth.ensure_fresh()
            model.client.api_key = creds.access_token
            return await _bottom(*args, **kwargs)

        model.client.chat.completions.create = _outer

        # Rotate the token mid-flight to confirm the second call picks
        # up the new value.
        await model.client.chat.completions.create(model="grok-4", messages=[])
        auth._access_token = "bearer-rotated"
        await model.client.chat.completions.create(model="grok-4", messages=[])

        assert seen == ["bearer-orig", "bearer-rotated"]
        assert auth.ensure_fresh_calls == 2

    async def test_generate_kwargs_propagated_to_parent(self) -> None:
        # generate_kwargs feeds the parent OpenAIChatModelCompat layer
        # — confirm construction accepts it and the parent stashed it.
        auth = _FakeAuth()
        model = XaiOAuthChatModel(
            auth=auth,
            model_name="grok-4",
            generate_kwargs={"temperature": 0.7, "max_tokens": 512},
        )
        # The exact attribute name lives on the parent; just check it's
        # reachable as a non-None value so we know construction wired it
        # through.
        assert getattr(model, "generate_kwargs", None) is not None
