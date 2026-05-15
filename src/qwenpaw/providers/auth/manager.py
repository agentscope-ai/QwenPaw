# -*- coding: utf-8 -*-
"""Provider authentication orchestration."""

from __future__ import annotations

from .credential_store import OAuthCredentialStore
from .models import (
    AuthStartRequest,
    AuthStartResult,
    AuthStatusResult,
    ProviderAuthStatus,
    ProviderAuthType,
)
from .registry import ProviderAuthRegistry, auth_registry


class ProviderAuthError(Exception):
    """Transport-neutral auth error for routers and CLIs to map."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class ProviderAuthManager:
    """Coordinate provider auth status, flows, and credential storage."""

    def __init__(
        self,
        provider_manager,
        credential_store: OAuthCredentialStore | None = None,
        registry: ProviderAuthRegistry | None = None,
    ) -> None:
        self.provider_manager = provider_manager
        self.credential_store = credential_store or OAuthCredentialStore()
        self.registry = registry or auth_registry

    async def get_status(
        self,
        provider_id: str,
        flow_id: str | None = None,
    ) -> AuthStatusResult:
        (
            provider,
            provider_type,
        ) = self.provider_manager.get_provider_with_storage_type(provider_id)
        auth_type = provider.auth_type

        if auth_type == ProviderAuthType.NONE or (
            auth_type == ProviderAuthType.API_KEY
            and not provider.require_api_key
        ):
            return AuthStatusResult(status=ProviderAuthStatus.NOT_REQUIRED)

        if auth_type == ProviderAuthType.API_KEY:
            return AuthStatusResult(
                status=(
                    ProviderAuthStatus.AUTHENTICATED
                    if bool(provider.api_key)
                    else ProviderAuthStatus.NOT_CONFIGURED
                ),
            )

        adapter = self.registry.get(provider.id)
        if adapter is None:
            return AuthStatusResult(
                status=ProviderAuthStatus.ERROR,
                message=(
                    f"Provider '{provider.id}' does not support OAuth "
                    "authentication yet"
                ),
            )

        if flow_id:
            return await adapter.poll(provider, flow_id)

        credential = self.credential_store.load(provider.id, provider_type)
        return await adapter.get_status(provider, credential)

    async def start(
        self,
        provider_id: str,
        request: AuthStartRequest,
    ) -> AuthStartResult:
        provider, _ = self.provider_manager.get_provider_with_storage_type(
            provider_id,
        )
        auth_type = provider.auth_type

        if auth_type == ProviderAuthType.NONE or (
            auth_type == ProviderAuthType.API_KEY
            and not provider.require_api_key
        ):
            raise ProviderAuthError(
                400,
                f"Provider '{provider.id}' does not require authentication",
            )
        if auth_type == ProviderAuthType.API_KEY:
            raise ProviderAuthError(
                400,
                f"Provider '{provider.id}' uses API key authentication",
            )

        adapter = self.registry.get(provider.id)
        if adapter is None:
            raise ProviderAuthError(
                400,
                f"Provider '{provider.id}' does not support OAuth "
                "authentication yet",
            )
        if adapter.auth_type != auth_type:
            raise ProviderAuthError(
                400,
                f"Provider '{provider.id}' auth adapter type mismatch",
            )
        return await adapter.start(provider, request)

    async def handle_callback(
        self,
        provider_id: str,
        state: str,
        code: str,
    ) -> AuthStatusResult:
        (
            provider,
            provider_type,
        ) = self.provider_manager.get_provider_with_storage_type(provider_id)
        adapter = self.registry.get(provider.id)
        credential = await adapter.handle_callback(provider, state, code)
        self.credential_store.save(credential, provider_type)
        return await adapter.get_status(provider, credential)

    async def logout(self, provider_id: str) -> AuthStatusResult:
        (
            provider,
            provider_type,
        ) = self.provider_manager.get_provider_with_storage_type(provider_id)
        auth_type = provider.auth_type

        if auth_type == ProviderAuthType.NONE or (
            auth_type == ProviderAuthType.API_KEY
            and not provider.require_api_key
        ):
            return AuthStatusResult(status=ProviderAuthStatus.NOT_REQUIRED)
        if auth_type == ProviderAuthType.API_KEY:
            raise ProviderAuthError(
                400,
                f"Provider '{provider.id}' uses API key authentication "
                "and does not support logout",
            )

        adapter = self.registry.get(provider.id)
        credential = self.credential_store.load(provider.id, provider_type)
        await adapter.logout(provider, credential)
        self.credential_store.delete(provider.id, provider_type)
        return AuthStatusResult(status=ProviderAuthStatus.NOT_CONFIGURED)
