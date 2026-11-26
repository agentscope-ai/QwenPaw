# -*- coding: utf-8 -*-
"""Provider configuration during plugin registration."""

import asyncio
import json
import threading

import httpx
from fastapi import FastAPI

from qwenpaw.app.routers.providers import router
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_manager import ProviderManager


async def test_saved_address_survives_plugin_registration(
    isolated_secret_dir,
    monkeypatch,
):
    manager = ProviderManager()
    old, new = "https://old.invalid", "https://new.invalid"
    provider = OpenAIProvider(id="example", name="Example", base_url=old)
    path = manager.plugin_path / "example.json"
    path.write_text(provider.model_dump_json(), encoding="utf-8")
    prepared = threading.Event()
    resume = threading.Event()
    prepare = manager._prepare_plugin_registration

    def pause_after_read(*args, **kwargs):
        registration = prepare(*args, **kwargs)
        prepared.set()
        assert resume.wait(5)
        return registration

    class RegistrationLock(asyncio.Lock):
        """Resume registration as soon as the configuration save queues."""

        async def acquire(self):
            if self.locked():
                resume.set()
            return await super().acquire()

    monkeypatch.setattr(
        manager,
        "_prepare_plugin_registration",
        pause_after_read,
    )
    manager._provider_save_locks[provider.id] = RegistrationLock()
    app = FastAPI()
    app.state.provider_manager = manager
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://app",
    ) as client:
        url = "/models/example/config"
        registration = asyncio.create_task(
            manager.register_plugin_provider_async(
                provider.id,
                OpenAIProvider,
                provider.name,
                old,
                metadata={},
            ),
        )
        try:
            assert await asyncio.to_thread(prepared.wait, 5)
            saved = await asyncio.wait_for(
                client.put(url, json={"base_url": new}),
                5,
            )
            assert saved.status_code == 200
        finally:
            resume.set()
            await asyncio.wait_for(registration, 5)

        assert (await client.get(url)).json()["base_url"] == new
        assert (await client.put(url, json={"enabled": False})).is_success
        assert json.loads(path.read_text(encoding="utf-8"))["base_url"] == new
