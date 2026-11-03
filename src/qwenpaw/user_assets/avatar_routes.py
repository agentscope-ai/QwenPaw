# -*- coding: utf-8 -*-
"""Authenticated avatar routes shared by local and hosted consoles."""

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .avatars import AvatarStore, MAX_BYTES


class AvatarSelection(BaseModel):
    image_id: str | None = Field(default=None, max_length=64)


def avatar_router(
    store_provider: Callable[[], AvatarStore],
    owner_dependency: Callable,
) -> APIRouter:
    """Bind storage and trusted identity before registering endpoints."""
    router = APIRouter(prefix="/profile/avatars", tags=["profile"])

    @router.get("")
    async def profile(owner: str = Depends(owner_dependency)):
        return await run_in_threadpool(store_provider().profile, owner)

    @router.post("")
    async def upload(
        request: Request,
        owner: str = Depends(owner_dependency),
    ):
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_BYTES:
                raise HTTPException(413, f"Avatar exceeds {MAX_BYTES} bytes")
            data.extend(chunk)
        try:
            return await run_in_threadpool(
                store_provider().upload,
                owner,
                bytes(data),
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.put("/selection")
    async def select(
        body: AvatarSelection,
        owner: str = Depends(owner_dependency),
    ):
        try:
            return await run_in_threadpool(
                store_provider().select,
                owner,
                body.image_id,
            )
        except KeyError as exc:
            raise HTTPException(404, "Avatar not found") from exc

    @router.get("/{identifier}")
    async def image(
        identifier: str,
        owner: str = Depends(owner_dependency),
    ):
        try:
            data, mime = await run_in_threadpool(
                store_provider().image,
                owner,
                identifier,
            )
        except KeyError as exc:
            raise HTTPException(404, "Avatar not found") from exc
        return Response(
            data,
            media_type=mime,
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router
