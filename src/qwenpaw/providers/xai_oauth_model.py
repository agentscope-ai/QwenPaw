# -*- coding: utf-8 -*-
"""xAI OAuth chat-completions adapter.

xAI's chat surface (``https://api.x.ai/v1/chat/completions``) is
OpenAI-compatible — same request/response shapes, same SSE streaming
contract.  So unlike the Codex OAuth bridge (which translates
chat→Responses), this wrapper only needs to inject a fresh Bearer
token before each outbound request.

We do this by subclassing :class:`OpenAIChatModelCompat`, wrapping
``self.client.chat.completions.create`` so it ``await``-refreshes
the OAuth token via :class:`XaiAuth` before delegating to the real
SDK call with the freshly minted bearer.
"""

from __future__ import annotations

import logging
from typing import Any

from .openai_chat_model_compat import OpenAIChatModelCompat
from .xai_auth import DEFAULT_XAI_BASE_URL, XaiAuth

logger = logging.getLogger(__name__)


class XaiOAuthChatModel(OpenAIChatModelCompat):
    """Drop-in chat model that swaps in OAuth-refreshed bearer per call.

    ``auth`` owns the credential file and refresh schedule — we just
    pull a fresh access_token off it on every call edge.  The
    underlying ``AsyncOpenAI`` client is constructed with a placeholder
    ``api_key`` that gets overwritten before each request.
    """

    def __init__(
        self,
        *,
        auth: XaiAuth,
        model_name: str,
        stream: bool = True,
        stream_tool_parsing: bool = False,
        client_kwargs: dict[str, Any] | None = None,
        generate_kwargs: dict[str, Any] | None = None,
    ) -> None:
        ck = dict(client_kwargs or {})
        ck.setdefault("base_url", auth.base_url)
        # api_key is required by the OpenAI SDK constructor.  We pass
        # a placeholder that's immediately overwritten by ``_install``
        # on each call edge — never reaches the wire.
        super().__init__(
            model_name=model_name,
            stream=stream,
            api_key="oauth-placeholder",
            stream_tool_parsing=stream_tool_parsing,
            client_kwargs=ck,
            generate_kwargs=dict(generate_kwargs or {}),
        )
        self._auth = auth
        self._install_wrapper()

    def _install_wrapper(self) -> None:
        original_create = self.client.chat.completions.create

        async def _wrapped(*args: Any, **kwargs: Any) -> Any:
            # Refresh inside the call, not at construction time — the
            # model instance can outlive the access_token TTL by hours
            # when an agent session sits idle between turns.
            creds = await self._auth.ensure_fresh()
            self.client.api_key = creds.access_token
            return await original_create(*args, **kwargs)

        # Deliberate wrapper swap — replace bound method on the
        # SDK's completions singleton so every call edge refreshes.
        setattr(self.client.chat.completions, "create", _wrapped)

    @property
    def base_url(self) -> str:
        return self._auth.base_url or DEFAULT_XAI_BASE_URL
