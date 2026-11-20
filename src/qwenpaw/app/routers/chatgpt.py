# -*- coding: utf-8 -*-
"""Local account controls for ChatGPT subscriptions."""

import asyncio
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ...providers.oauth.chatgpt import chatgpt_accounts
from ...providers.provider_manager import ProviderManager
from ...tauri.env import DESKTOP_CORS_ORIGINS
from ..auth import is_loopback_ip, resolve_client_ip
from .providers import get_provider_manager


def require_local(request: Request, response: Response) -> None:
    """Require same-machine browser access and never cache account state."""
    hosts = {f"127.0.0.1", f"localhost", f"::1"}
    origin = request.headers.get(f"origin")
    local_origin = (
        not origin
        or origin in DESKTOP_CORS_ORIGINS
        or urlsplit(origin).hostname in hosts
    )
    if (
        request.url.hostname not in hosts
        or not local_origin
        or not request.client
        or request.client.host not in hosts
        or not is_loopback_ip(resolve_client_ip(request))
    ):
        raise HTTPException(403, f"ChatGPT sign-in is only available locally.")
    response.headers[f"Cache-Control"] = f"no-store"


router = APIRouter(
    prefix=f"/providers/chatgpt",
    tags=[f"chatgpt"],
    dependencies=[Depends(require_local)],
)
account_lock = asyncio.Lock()


class AccountChoice(BaseModel):
    account_id: str | None = None


async def sync_models(manager: ProviderManager, reset: bool = False):
    provider = manager.get_provider(f"openai-chatgpt")
    if provider is None:
        raise HTTPException(404, f"ChatGPT provider not found.")
    snapshot = provider.configuration_snapshot()
    current = await asyncio.to_thread(chatgpt_accounts.status)
    reset = reset and (
        not current[f"sharing"]
        or snapshot.meta.get(f"chatgpt_account") != current[f"active"]
    )
    snapshot.meta[f"chatgpt_account"] = current[f"active"]
    if reset:
        snapshot.models = []
        snapshot.extra_models = []
        snapshot.discovered_models = []
        snapshot.hidden_model_ids = []
        snapshot.removed_model_ids = []
        await manager.save_provider_config_async(snapshot.id, snapshot)
    if current[f"sharing"]:
        try:
            snapshot.discovered_models = await snapshot.fetch_models()
        except Exception as exc:
            raise HTTPException(
                502,
                f"Signed in, but model discovery failed. Retry refresh.",
            ) from exc
        snapshot.models_last_synced_at = datetime.now(timezone.utc).isoformat()
        snapshot.models_last_sync_error = None
        snapshot.enabled = True
        await manager.save_provider_config_async(snapshot.id, snapshot)


@router.get(f"/session")
async def session():
    return await asyncio.to_thread(chatgpt_accounts.status)


@router.post(f"/start")
async def start(body: AccountChoice):
    try:
        return await asyncio.to_thread(chatgpt_accounts.start, body.account_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get(f"/status/{{state}}")
async def status(
    state: str,
    manager: ProviderManager = Depends(get_provider_manager),
):
    async with account_lock:
        attempt = chatgpt_accounts.attempt
        if not attempt or attempt.state != state:
            raise HTTPException(404, f"Sign-in attempt not found.")
        if attempt.status == f"completed":
            await sync_models(manager, reset=True)
            attempt.status = f"ready"
        return {
            f"status": (
                f"completed" if attempt.status == f"ready" else attempt.status
            ),
        }


@router.post(f"/cancel/{{state}}")
async def cancel(state: str):
    await asyncio.to_thread(chatgpt_accounts.cancel, state)
    return {f"ok": True}


@router.post(f"/select")
async def select(
    body: AccountChoice,
    manager: ProviderManager = Depends(get_provider_manager),
):
    async with account_lock:
        if not body.account_id:
            raise HTTPException(400, f"Select a ChatGPT account.")
        try:
            await asyncio.to_thread(chatgpt_accounts.select, body.account_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        await sync_models(manager, reset=True)
        return await session()


@router.post(f"/sign-out")
async def sign_out(manager: ProviderManager = Depends(get_provider_manager)):
    async with account_lock:
        revoked = await asyncio.to_thread(chatgpt_accounts.sign_out)
        await sync_models(manager, reset=True)
        return {f"revoked": revoked}
