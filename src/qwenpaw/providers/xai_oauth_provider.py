# -*- coding: utf-8 -*-
"""xAI OAuth provider — Grok chat over the OAuth bearer flow.

Self-contained ``OpenAIProvider`` subclass that does not require any
edits to ``openai_provider.py``.  All OAuth-specific behaviour is
encapsulated here, so the standard OpenAI path is unaffected when
xai-oauth isn't in use.

The provider works against xAI's OpenAI-compatible endpoint
(``https://api.x.ai/v1``), using a fresh access_token from
:class:`XaiAuth` on every outbound call.  Users authenticate once via
``qwenpaw xai login``, which writes ``~/.xai/auth.json``; the refresh
token cycles new bearers automatically thereafter.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from agentscope.model import ChatModelBase
from openai import APIError, AsyncOpenAI

from .openai_provider import OpenAIProvider
from .provider import ModelInfo

if TYPE_CHECKING:
    from .xai_auth import XaiAuth

logger = logging.getLogger(__name__)


class XaiOAuthProvider(OpenAIProvider):
    """xAI OAuth provider.

    Overrides only the four entry points that need to inject a fresh
    Bearer token (``check_connection``, ``fetch_models``,
    ``check_model_connection``, ``get_chat_model_instance``).  Probe
    helpers and ``_client`` are inherited unchanged — probes against an
    OAuth provider can 401 harmlessly, leaving the capability flags
    "untested" rather than introducing a sync/async impedance mismatch.
    """

    def _get_auth(self) -> "XaiAuth":
        """Build a fresh :class:`XaiAuth` instance — reads one small
        file and bypasses the need to stash a non-field attribute on
        the pydantic model.  Each call re-reads the credentials file,
        which is what we want when ``qwenpaw xai login`` may have
        rotated tokens on disk.  Raises ``FileNotFoundError`` when
        the login command has not yet run."""
        from .xai_auth import XaiAuth

        return XaiAuth()

    def _bearer_client(self, bearer: str, timeout: float) -> AsyncOpenAI:
        """Build an AsyncOpenAI client bound to a specific bearer."""
        kwargs: dict = {
            "base_url": self.base_url,
            "api_key": bearer,
            "timeout": timeout,
        }
        headers = self._build_default_headers()
        if headers:
            kwargs["default_headers"] = headers
        return AsyncOpenAI(**kwargs)

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        """Refresh the OAuth bearer + hit ``/v1/models`` to confirm
        the account can actually reach the xAI surface."""
        try:
            auth = self._get_auth()
            creds = await auth.ensure_fresh()
        except FileNotFoundError as e:
            return False, f"xAI OAuth not set up: {e}"
        except Exception as e:  # pylint: disable=broad-exception-caught
            return False, f"xAI OAuth refresh failed: {e}"
        client = self._bearer_client(creds.access_token, timeout)
        try:
            await client.models.list(timeout=timeout)
        except APIError as e:
            return False, f"xAI API error: {e}"
        except Exception as e:  # pylint: disable=broad-exception-caught
            return False, f"Unknown error: {e}"
        return True, ""

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        """Fetch the live ``/v1/models`` catalogue using the bearer.

        xAI's catalogue is the source of truth for what an account can
        reach; we surface it verbatim so a freshly-shipped ``grok-*``
        slug appears in the UI's Discover step without a release.
        Discovery failures return an empty list so the UI falls back
        to any models the user previously saved as extra_models.
        """
        try:
            auth = self._get_auth()
            creds = await auth.ensure_fresh()
            client = self._bearer_client(creds.access_token, timeout)
            payload = await client.models.list(timeout=timeout)
            return self._normalize_models_payload(payload)
        except Exception:  # pylint: disable=broad-exception-caught
            return []

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> tuple[bool, str]:
        """Ping a specific model with a 1-token streamed request to
        confirm the OAuth bearer can actually drive it.  Exercises the
        full refresh-on-call path inside :class:`XaiOAuthChatModel`."""
        model_id = (model_id or "").strip()
        if not model_id:
            return False, "Empty model ID"
        try:
            from .xai_oauth_model import XaiOAuthChatModel

            auth = self._get_auth()
            await auth.ensure_fresh()
            model = XaiOAuthChatModel(
                auth=auth,
                model_name=model_id,
                stream=True,
                stream_tool_parsing=False,
                client_kwargs={},
                generate_kwargs={},
            )
            res = await model.client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": "ping"}],
                stream=True,
                max_tokens=1,
            )
            async for _ in res:
                break
            return True, ""
        except FileNotFoundError as e:
            return False, f"xAI OAuth not set up: {e}"
        except Exception as e:  # pylint: disable=broad-exception-caught
            return False, f"xAI OAuth model check failed: {e}"

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        """Return a chat model that refreshes the OAuth bearer per call.

        Bypasses the parent's header-merging logic (DASHSCOPE-specific)
        — xAI doesn't use any of those service-tagging headers.

        Raises ``ValueError`` (not ``FileNotFoundError``) when the user
        has not run ``qwenpaw xai login`` yet: ``create_model_and_formatter``
        call sites catch ``ValueError`` / ``AppBaseException`` but not
        ``FileNotFoundError``, so leaking the raw OS error would crash
        the agent runtime instead of surfacing a clean "please log in"
        message in the UI.
        """
        from .xai_oauth_model import XaiOAuthChatModel

        try:
            auth = self._get_auth()
        except FileNotFoundError as e:
            raise ValueError(
                f"xAI OAuth credentials not set up: {e} — "
                "run `qwenpaw xai login` once to populate ~/.xai/auth.json.",
            ) from e

        return XaiOAuthChatModel(
            auth=auth,
            model_name=model_id,
            stream=True,
            stream_tool_parsing=False,
            client_kwargs={},
            generate_kwargs=self.get_effective_generate_kwargs(model_id),
        )
