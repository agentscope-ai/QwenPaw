# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI

from api.dependencies import creator_error_handler
from api.router import router
from domain.errors import CreatorError
from services.project_files.facade import clear_creator_file_service_registry


@pytest.fixture()
def api_runtime_root(tmp_path, monkeypatch):
    root = tmp_path / "creator-api"
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(root))
    root.mkdir(parents=True)
    clear_creator_file_service_registry()
    try:
        yield root
    finally:
        clear_creator_file_service_registry()


@pytest.fixture()
def app(api_runtime_root):
    application = FastAPI()
    application.add_exception_handler(CreatorError, creator_error_handler)
    application.include_router(router)
    return application


@pytest.fixture()
def run_scenario():
    """Drive ``await scenario(client)`` against an in-process ASGI app."""

    def _run(app, scenario):
        async def _go():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
            ) as client:
                return await scenario(client)

        return asyncio.run(_go())

    return _run


@pytest.fixture()
def api_request(run_scenario):
    """One-shot in-process API call for single-request tests."""

    def _request(app, method, url, **kwargs):
        return run_scenario(
            app,
            lambda client: client.request(method, url, **kwargs),
        )

    return _request
