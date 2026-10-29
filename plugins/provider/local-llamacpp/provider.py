# -*- coding: utf-8 -*-
"""Local inference endpoint and management operations owned by one plugin."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from qwenpaw.plugins import PluginBusyError, SDKError
from qwenpaw.plugins.providers import ModelInfo
from .io_helpers import run_io


class LocalProvider:
    def __init__(self, context):
        self.context = context
        self.handle = None
        self._manager = None
        self._lock = asyncio.Lock()
        self._users = {}
        self._server_info = None
        self._failed = False
        self._started = False
        self._manually_stopped = False
        self.closed = False

    def activate(self, context):
        context.resources.connection(self, "local-model-provider")

    def _guard(self):
        if self.closed or self._failed:
            raise SDKError("Local model provider needs to be reloaded")

    async def _start(self):
        if self._manager is not None:
            return
        from .manager import LocalModelManager

        saved = await self.context.storage.aread_json("data-root.json", {})
        data_dir = Path(
            self.context.config.get(
                "data_dir",
                saved.get("data_dir", self.context.storage.path("runtime")),
            ),
        )
        if saved.get("data_dir") != str(data_dir):
            await self.context.storage.awrite_json(
                "data-root.json",
                {"data_dir": str(data_dir)},
            )
        try:
            self._manager = LocalModelManager()
            await self._manager.start(data_dir)
            self._started = True
        except BaseException:
            self._failed = True
            raise

    async def manager(self):
        """Return the initialized manager; reads may observe server startup."""
        self._guard()
        if not self._started:
            async with self._lock:
                self._guard()
                await self._start()
        return self._manager

    @asynccontextmanager
    async def _operation(self):
        self._guard()
        async with self._lock:
            self._guard()
            await self._start()
            yield self._manager

    async def _publish(self, result):
        model = result.model_info
        await self.handle.update(
            base_url=f"http://127.0.0.1:{result.port}/v1",
            models=(
                ModelInfo(
                    id=model.id,
                    name=model.name,
                    max_input_length=None,
                    is_free=None,
                    supports_multimodal=model.supports_multimodal,
                    supports_image=model.supports_image,
                    supports_video=model.supports_video,
                    probe_source=model.probe_source,
                ),
            ),
        )
        self._server_info = result
        return result

    async def _stopped(self):
        self._manually_stopped = True
        self._server_info = None
        await self.handle.update(base_url="", models=())
        await self.handle.clear_selection()

    async def ensure_server(self, model_id):
        async with self._operation() as manager:
            result = await manager.ensure_server(model_id)
            await self._publish(result)
            self._manually_stopped = False
            return result

    async def stop_server(self):
        async with self._operation() as manager:
            await manager.stop_server()
            await self._stopped()

    async def start_runtime_download(self):
        async with self._operation() as manager:
            stopped = await manager.start_runtime_download()
            if stopped:
                await self._stopped()

    async def cancel_runtime_download(self):
        async with self._operation() as manager:
            await run_io(manager.cancel_runtime_download)

    async def start_model_download(self, model_id, *, source=None):
        async with self._operation() as manager:
            await run_io(manager.start_model_download, model_id, source=source)

    async def cancel_model_download(self):
        async with self._operation() as manager:
            await run_io(manager.cancel_model_download)

    async def remove_downloaded_model(self, model_id):
        async with self._operation() as manager:
            status = manager.get_server_status()
            if status["running"] and status["model_name"] == model_id:
                raise SDKError("Cannot delete a model while it is running")
            await run_io(manager.remove_downloaded_model, model_id)

    async def _ensure_server(self, model_id):
        status = self._manager.get_server_status()
        if (
            status["running"]
            and status["model_name"] == model_id
            and self._server_info is not None
        ):
            return self._server_info
        result = await self._manager.ensure_server(model_id)
        return await self._publish(result)

    @asynccontextmanager
    async def connect(self, _context, model_id):
        key = object()
        try:
            async with self._operation():
                if self._manually_stopped:
                    raise SDKError(
                        "Start the local server in "
                        "Local Model Management first",
                    )
                result = await self._ensure_server(model_id)
                self._users[key] = model_id
            yield f"http://127.0.0.1:{result.port}/v1"
        finally:
            self._users.pop(key, None)

    async def close(self):
        if self.closed:
            return
        if self._users:
            raise PluginBusyError(self.context.plugin_id, len(self._users))
        async with self._lock:
            self._failed = True
            if self._manager is not None:
                await self._manager.close()
            self.closed = True
