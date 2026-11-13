# -*- coding: utf-8 -*-
"""Shared credential helpers for web search providers."""

from __future__ import annotations

from ....config.context import get_current_workspace_dir
from ....drivers.credentials.store import AsyncCredentialStore
from ....drivers.errors import CredentialNotFoundError
from ....utils.io_utils import run_sync_io


async def read_optional_api_key(ref: str) -> str | None:
    """Read an optional ``api_key`` secret from the current agent's store.

    Resolves the workspace credentials path and performs all filesystem /
    store work in a worker thread so the event loop stays unblocked.
    Returns ``None`` when the workspace is unset, the credential is missing,
    or the secret is blank. Providers should not maintain their own
    plaintext key caches — the shared store owns that lifecycle.
    """
    workspace_dir = get_current_workspace_dir()
    if not workspace_dir:
        return None

    def _read() -> str | None:
        store = AsyncCredentialStore(workspace_dir / "credentials.yaml")
        try:
            record = store.get_sync(ref)
        except CredentialNotFoundError:
            return None
        key = str(record.secrets.get("api_key") or "")
        return key or None

    return await run_sync_io(_read)


__all__ = ["read_optional_api_key"]
