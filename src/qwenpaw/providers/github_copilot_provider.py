# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""GitHub Copilot built-in provider.

This provider authenticates the user via the GitHub OAuth device-code
flow (no API key required) and routes chat completions through the
Copilot REST API, which is OpenAI-compatible.

Architecture overview:

* :class:`~qwenpaw.providers.oauth.CopilotOAuthService` owns the OAuth
  state and asynchronously refreshes the short-lived Copilot API token.
* :class:`~qwenpaw.providers.oauth.CopilotAuth` (an ``httpx.Auth``
  subclass) injects the latest token on every outgoing request, so the
  underlying ``AsyncOpenAI`` client never goes stale.
* This provider class delegates ``check_connection`` /
  ``check_model_connection`` to the inherited :class:`OpenAIProvider`
  implementation, but overrides ``fetch_models`` to handle the
  enterprise plan's lack of ``/models``, and overrides
  ``probe_model_multimodal`` to avoid burning Copilot quota on probes
  (we ship a static catalog with documented multimodal flags instead).
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, List

from openai import APIError, AsyncOpenAI

from .openai_provider import OpenAIProvider
from .provider import ModelInfo
from .oauth import (
    CopilotOAuthService,
    get_oauth_service,
)

if TYPE_CHECKING:
    from agentscope.model import ChatModelBase
    from .multimodal_prober import ProbeResult

logger = logging.getLogger(__name__)


# Static catalog of well-known Copilot models with documented multimodal
# capabilities.  Discovery (via /models) supplements this catalog at
# runtime; the static seed ensures multimodal flags are correct even
# when discovery is unavailable (enterprise plans, network errors...).
GITHUB_COPILOT_MODELS: List[ModelInfo] = [
    ModelInfo(
        id="gpt-4o",
        name="GPT-4o",
        supports_image=True,
        supports_video=False,
        probe_source="documentation",
    ),
    ModelInfo(
        id="gpt-4o-mini",
        name="GPT-4o mini",
        supports_image=True,
        supports_video=False,
        probe_source="documentation",
    ),
    ModelInfo(
        id="gpt-4.1",
        name="GPT-4.1",
        supports_image=True,
        supports_video=False,
        probe_source="documentation",
    ),
    ModelInfo(
        id="o1",
        name="OpenAI o1",
        supports_image=False,
        supports_video=False,
        probe_source="documentation",
    ),
    ModelInfo(
        id="o3-mini",
        name="OpenAI o3-mini",
        supports_image=False,
        supports_video=False,
        probe_source="documentation",
    ),
    ModelInfo(
        id="claude-3.5-sonnet",
        name="Claude 3.5 Sonnet",
        supports_image=True,
        supports_video=False,
        probe_source="documentation",
    ),
    ModelInfo(
        id="claude-3.7-sonnet",
        name="Claude 3.7 Sonnet",
        supports_image=True,
        supports_video=False,
        probe_source="documentation",
    ),
    ModelInfo(
        id="claude-sonnet-4",
        name="Claude Sonnet 4",
        supports_image=True,
        supports_video=False,
        probe_source="documentation",
    ),
    ModelInfo(
        id="gemini-2.0-flash-001",
        name="Gemini 2.0 Flash",
        supports_image=True,
        supports_video=False,
        probe_source="documentation",
    ),
]


def _meta_string(meta: dict, key: str, default: str) -> str:
    """Return ``meta[key]`` as str when non-empty, else ``default``."""
    value = meta.get(key)
    if isinstance(value, str) and value:
        return value
    return default


class GitHubCopilotProvider(OpenAIProvider):
    """First-class GitHub Copilot provider with OAuth device-flow auth."""

    # ------------------------------------------------------------------
    # OAuth service plumbing
    # ------------------------------------------------------------------

    def _service(self) -> CopilotOAuthService:
        """Return (creating if needed) the OAuth service for this provider.

        The service is process-global, keyed by provider ``id``, so it is
        shared between the FastAPI router and any chat invocations.
        """

        def _factory() -> CopilotOAuthService:
            client_id = (
                os.environ.get("QWENPAW_GITHUB_COPILOT_CLIENT_ID")
                or _meta_string(self.meta, "client_id", "")
                or None
            )
            kwargs: dict[str, Any] = {}
            if client_id:
                kwargs["client_id"] = client_id
            kwargs["editor_version"] = _meta_string(
                self.meta,
                "editor_version",
                "vscode/1.95.0",
            )
            kwargs["plugin_version"] = _meta_string(
                self.meta,
                "plugin_version",
                f"qwenpaw/{_get_qwenpaw_version()}",
            )
            kwargs["user_agent"] = _meta_string(
                self.meta,
                "user_agent",
                f"QwenPaw/{_get_qwenpaw_version()}",
            )
            service = CopilotOAuthService(provider_id=self.id, **kwargs)

            # Prefer the encrypted CopilotTokenStore as the durable
            # source of truth.  Fall back to the legacy provider-config
            # field for backwards compatibility with installs created
            # before the token store became the single writer.
            persisted = service.token_store.load()
            if persisted and persisted.get("oauth_access_token"):
                service.seed_session(
                    persisted["oauth_access_token"],
                    persisted.get("github_login", ""),
                )
            elif self.oauth_access_token:
                service.seed_session(
                    self.oauth_access_token,
                    self.oauth_user_login,
                )
            return service

        return get_oauth_service(self.id, factory=_factory)

    # ------------------------------------------------------------------
    # Provider overrides
    # ------------------------------------------------------------------

    async def _compute_is_authenticated(  # type: ignore[override]
        self,
    ) -> bool:
        return self._service().is_authenticated

    def _client(self, timeout: float = 5) -> AsyncOpenAI:
        """AsyncOpenAI client wired to the Copilot REST endpoint with
        per-request OAuth-driven Bearer authentication."""
        service = self._service()
        # Use the cached endpoint if known, otherwise fall back to the
        # public default (will be overridden once the first token
        # exchange succeeds).
        token = service._copilot_token  # noqa: SLF001
        base_url = (
            (token.api_endpoint if token else None)
            or self.base_url
            or "https://api.githubcopilot.com"
        )
        # Reuse a single shared httpx.AsyncClient owned by the OAuth
        # service so repeated check_connection / fetch_models calls do
        # not leak sockets/file-descriptors.  Per-request timeouts
        # passed to OpenAI methods (e.g. ``models.list(timeout=...)``)
        # still take precedence over the client default.
        http_client = service.get_or_create_http_client()
        # AsyncOpenAI accepts an http_client kwarg; api_key is required
        # but unused (auth is applied per-request by CopilotAuth).
        return AsyncOpenAI(
            base_url=base_url,
            api_key="copilot-oauth",  # placeholder; CopilotAuth replaces it
            timeout=timeout,
            http_client=http_client,
        )

    async def check_connection(  # type: ignore[override]
        self,
        timeout: float = 5,
    ) -> tuple[bool, str]:
        if not self._service().is_authenticated:
            return False, (
                "GitHub Copilot is not authenticated. "
                "Sign in with your GitHub account to continue."
            )
        return await super().check_connection(timeout=timeout)

    async def fetch_models(  # type: ignore[override]
        self,
        timeout: float = 5,
    ) -> List[ModelInfo]:
        """Fetch Copilot models, falling back to the static catalog.

        * Free / Pro plans expose ``GET /models`` — we merge the
          discovered IDs with the static seed (preserving multimodal
          annotations from the seed).
        * Enterprise plans return 404 for ``/models``; in that case we
          return the static catalog unchanged.
        """
        seed_by_id = {m.id: m for m in GITHUB_COPILOT_MODELS}

        if not self._service().is_authenticated:
            return list(GITHUB_COPILOT_MODELS)

        try:
            client = self._client(timeout=timeout)
            payload = await client.models.list(timeout=timeout)
            discovered = self._normalize_models_payload(payload)
        except APIError as exc:
            logger.info(
                "GitHub Copilot /models discovery failed (%s); "
                "returning static catalog.",
                exc,
            )
            return list(GITHUB_COPILOT_MODELS)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "Unexpected error while listing Copilot models; "
                "returning static catalog.",
                exc_info=True,
            )
            return list(GITHUB_COPILOT_MODELS)

        merged: List[ModelInfo] = []
        seen: set[str] = set()
        for model in discovered:
            seed = seed_by_id.get(model.id)
            if seed is not None:
                # Preserve documented multimodal flags from the seed.
                model.supports_image = seed.supports_image
                model.supports_video = seed.supports_video
                if (
                    seed.supports_image is not None
                    or seed.supports_video is not None
                ):
                    model.supports_multimodal = bool(
                        seed.supports_image or seed.supports_video,
                    )
                model.probe_source = seed.probe_source
                if seed.name and (not model.name or model.name == model.id):
                    model.name = seed.name
            seen.add(model.id)
            merged.append(model)
        # Append any seed models the discovery API didn't return.
        for seed in GITHUB_COPILOT_MODELS:
            if seed.id not in seen:
                merged.append(seed)
        return merged

    async def probe_model_multimodal(  # type: ignore[override]
        self,
        model_id: str,
        timeout: float = 10,
        image_only: bool = False,
    ) -> "ProbeResult":
        """Skip live probing — return the documented capability instead.

        Live probing through Copilot's chat endpoint costs the user
        quota and can be flaky.  We instead trust the static catalog
        (:data:`GITHUB_COPILOT_MODELS`); when a model is unknown, we
        return an empty :class:`ProbeResult` so the caller can decide
        what to do.
        """
        from .multimodal_prober import ProbeResult

        for seed in GITHUB_COPILOT_MODELS:
            if seed.id == model_id:
                return ProbeResult(
                    supports_image=bool(seed.supports_image),
                    supports_video=bool(seed.supports_video),
                    image_message="documented",
                    video_message="documented",
                )
        return ProbeResult(
            image_message="Skipped: model not in Copilot catalog",
            video_message="Skipped: model not in Copilot catalog",
        )

    def get_chat_model_instance(  # type: ignore[override]
        self,
        model_id: str,
    ) -> "ChatModelBase":
        from .openai_chat_model_compat import OpenAIChatModelCompat

        service = self._service()
        # Decide base_url at construction time; the http_client+auth
        # below take care of token freshness.
        token = service._copilot_token  # noqa: SLF001
        base_url = (
            (token.api_endpoint if token else None)
            or self.base_url
            or "https://api.githubcopilot.com"
        )

        # Reuse the shared httpx.AsyncClient owned by the OAuth service
        # so chat sessions don't each open (and forget to close) their
        # own socket pool.
        http_client = service.get_or_create_http_client()
        client_kwargs: dict[str, Any] = {
            "base_url": base_url,
            "http_client": http_client,
        }

        return OpenAIChatModelCompat(
            model_name=model_id,
            stream=True,
            api_key="copilot-oauth",  # ignored; CopilotAuth replaces it
            stream_tool_parsing=False,
            client_kwargs=client_kwargs,
            generate_kwargs=self.get_effective_generate_kwargs(model_id),
        )


def _get_qwenpaw_version() -> str:
    try:
        from qwenpaw.__version__ import __version__

        return str(__version__)
    except Exception:  # pylint: disable=broad-except
        return "0.0.0"


# ---------------------------------------------------------------------------
# Singleton built-in instance — registered by ProviderManager._init_builtins
# ---------------------------------------------------------------------------

PROVIDER_GITHUB_COPILOT = GitHubCopilotProvider(
    id="github-copilot",
    name="GitHub Copilot",
    base_url="https://api.githubcopilot.com",
    chat_model="OpenAIChatModel",
    api_key_prefix="",
    require_api_key=False,
    freeze_url=True,
    support_model_discovery=True,
    support_connection_check=True,
    auth_type="oauth_device_code",
    models=list(GITHUB_COPILOT_MODELS),
    meta={
        "api_key_url": "https://github.com/settings/copilot",
        "api_key_hint": (
            "GitHub Copilot uses OAuth device-code authentication. "
            "Click 'Sign in with GitHub' to authorize QwenPaw."
        ),
    },
)
