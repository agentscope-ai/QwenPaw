# -*- coding: utf-8 -*-
"""Find community links for old installs without changing provenance."""

import asyncio
import time
from urllib.parse import quote

import httpx

from .community_feedback import (
    PLATFORM_URL,
    FeedbackLinkError,
    _data,
    _detail_id,
)
from ..installation_origin import origin_from_platform_url

# Cache only public identity, never installation version or account data.
_CACHE: dict[str, tuple[float, dict | None]] = {}
_PENDING: dict[str, asyncio.Task] = {}


def _item_origin(item: object, plugin_id: str, is_app: bool) -> dict | None:
    if not isinstance(item, dict):
        return None
    try:
        identifier = _detail_id(item.get("details_url"), "plugins")
    except FeedbackLinkError:
        return None
    identity = item.get("id")
    if identifier != plugin_id or not isinstance(identity, str):
        return None
    return origin_from_platform_url(
        f"{PLATFORM_URL}/plugins/{quote(identity, safe='@/')}",
        "app" if is_app else "plugin",
    )


async def _lookup(plugin_id: str, client: httpx.AsyncClient) -> dict | None:
    response = await client.get(
        f"{PLATFORM_URL}/api/v1/plugins/{quote(plugin_id, safe='')}",
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    detail = _data(response.json())
    if detail.get("plugin_id") != plugin_id:
        raise FeedbackLinkError("Platform plugin ID does not match")
    tech_type = detail.get("tech_type")
    is_app = isinstance(tech_type, dict) and tech_type.get("code") == "app"
    matches = {}
    for page in range(1, 4):
        response = await client.get(
            f"{PLATFORM_URL}/openapi/v1/plugins",
            params={
                "search": plugin_id,
                "page_number": page,
                "page_size": 100,
            },
        )
        response.raise_for_status()
        data = _data(response.json())
        items = data.get("plugins")
        if not isinstance(items, list):
            raise FeedbackLinkError("Invalid marketplace response")
        for item in items:
            origin = _item_origin(item, plugin_id, is_app)
            if origin:
                matches[origin["resource_id"]] = origin
        total = data.get("total")
        if len(items) < 100 or isinstance(total, int) and page * 100 >= total:
            break
    else:
        # An incomplete result set cannot establish a unique counterpart.
        raise FeedbackLinkError("Marketplace search is incomplete")
    if len(matches) > 1:
        raise FeedbackLinkError("Marketplace plugin identity is ambiguous")
    return next(iter(matches.values()), None)


async def _cached_lookup(plugin_id: str) -> dict | None:
    cached = _CACHE.get(plugin_id)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
        async with asyncio.timeout(8):
            origin = await _lookup(plugin_id, client)
    if len(_CACHE) >= 512:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[plugin_id] = (time.monotonic() + (1800 if origin else 60), origin)
    return origin


def _lookup_done(plugin_id: str, task: asyncio.Task) -> None:
    if _PENDING.get(plugin_id) is task:
        _PENDING.pop(plugin_id, None)
    if not task.cancelled():
        task.exception()  # Consume errors even if every request disconnected.


async def _shared_lookup(plugin_id: str) -> dict | None:
    task = _PENDING.get(plugin_id)
    if task is None:
        task = asyncio.create_task(_cached_lookup(plugin_id))
        _PENDING[plugin_id] = task
        task.add_done_callback(lambda done: _lookup_done(plugin_id, done))
    return await asyncio.shield(task)


async def community_plugin_resources(
    plugins: list[dict],
) -> tuple[list[dict], list[str]]:
    """Return exact community associations and retryable lookup IDs."""
    limit = asyncio.Semaphore(4)

    async def resolve(item: dict) -> tuple[dict | None, str | None]:
        origin = item.get("installation_origin")
        if not origin:
            try:
                async with asyncio.timeout(9):
                    async with limit:
                        origin = await _shared_lookup(item["id"])
            except (
                httpx.HTTPError,
                FeedbackLinkError,
                TimeoutError,
                ValueError,
            ):
                return None, item["id"]
        if not origin:
            return None, None
        origin = {**origin, "installed_version": item.get("version", "")}
        return {
            "name": item["name"],
            "local_id": item["id"],
            "origin": origin,
            "description": str(item.get("description", ""))[:1000],
            "status": {"enabled": item["enabled"], "loaded": item["loaded"]},
        }, None

    results = await asyncio.gather(*(resolve(item) for item in plugins))
    return (
        [resource for resource, _ in results if resource],
        [identifier for _, identifier in results if identifier],
    )
