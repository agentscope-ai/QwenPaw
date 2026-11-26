# -*- coding: utf-8 -*-
"""Local inference endpoint and management operations owned by one plugin."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from qwenpaw.plugins import PluginBusyError, SDKError
from qwenpaw.plugins.providers import ModelInfo
from .io_helpers import PROVIDER_CLOSE_SECONDS, finish, run_io


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
        # The manager stops independent children concurrently. Its enclosing
        # deadline follows their shared stop policy, not the SDK client default.
        context.resources.connection(
            self,
            "local-model-provider",
            PROVIDER_CLOSE_SECONDS,
        )

    def _guard(self):
        if self.closed or self._failed:
            raise SDKError("Local model provider needs to be reloaded")

    def _resolve_data_directory(self, saved):
        data_dir = Path(
            self.context.config.get(
                "data_dir",
                saved.get("data_dir", self.context.storage.path("runtime")),
            ),
        )
        # Workers resolve staging paths too. Use the same root spelling here
        # so promoting a download through a symlink can compute relative paths.
        return data_dir.expanduser().resolve()

    async def data_directory(self):
        """Resolve owned data without creating a manager or writing settings."""
        saved = await self.context.storage.aread_json("data-root.json", {})
        return self._resolve_data_directory(saved)

    def runtime_status(self):
        """Describe this owner's server without starting or probing it."""
        self._guard()
        if not self._started:
            return {"running": False, "initialized": False}
        return {"initialized": True, **self._manager.get_server_status()}

    async def _start(self):
        if self._manager is not None:
            return
        from .manager import LocalModelManager

        saved = await self.context.storage.aread_json("data-root.json", {})
        data_dir = self._resolve_data_directory(saved)
        if saved.get("data_dir") != str(data_dir):
            await self.context.storage.awrite_json(
                "data-root.json",
                {"data_dir": str(data_dir)},
            )

        async def initialize():
            try:
                self._manager = LocalModelManager()
                await self._manager.start(data_dir)
            except BaseException:
                self._failed = True
                raise
            self._started = True

        await finish(initialize())

    async def manager(self):
        """Return the initialized manager; reads may observe server startup."""
        self._guard()
        if not self._started:
            async with self._lock:
                self._guard()
                await self._start()
        return self._manager

    @asynccontextmanager
    async def _operation(self, initialize=True):
        self._guard()
        async with self._lock:
            self._guard()
            if initialize:
                await self._start()
            yield self._manager

    async def _publish(self, result, model=None):
        """Publish the endpoint and apply an explicit model choice together."""

        async def publish():
            await self.handle.update(
                base_url=f"http://127.0.0.1:{result.port}/v1",
                models=(model,) if model is not None else None,
            )
            self._server_info = result
            if model is not None:
                self._manually_stopped = False
                await self.handle.select(model.id, model_type=model.model_type)

        await finish(publish())
        return result

    async def _stopped(self):
        self._manually_stopped = True
        self._server_info = None
        await self.handle.update(base_url="", models=())
        await self.handle.clear_selection()
        await self.handle.clear_selection(model_type="decision")

    async def start_server(self, model_id):
        async with self._operation() as manager:
            result = await manager.ensure_server(
                model_id,
                before_restart=self._check_restart,
            )
            model = result.model_info
            info = ModelInfo(
                id=model.id,
                name=model.name,
                max_input_length=None,
                is_free=None,
                supports_multimodal=model.supports_multimodal,
                supports_image=model.supports_image,
                supports_video=model.supports_video,
                probe_source=model.probe_source,
                model_type=model.model_type,
            )
            return await self._publish(result, info)

    async def stop_server(self):
        async with self._operation() as manager:

            async def stop():
                await manager.stop_server()
                await self._stopped()

            await finish(stop())

    async def start_runtime_download(self):
        async with self._operation() as manager:

            async def start():
                if await manager.start_runtime_download():
                    await self._stopped()

            # Finish applying the stopped state before releasing the lock
            # if the request is cancelled during runtime download setup.
            await finish(start())

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
            await run_io(manager.remove_downloaded_model, model_id)

    def _check_restart(self, pid):
        active = sum(current == pid for current in self._users.values())
        if active:
            raise PluginBusyError(self.context.plugin_id, active)

    async def _ensure_server(self, model_id):
        status = self._manager.get_server_status()
        if (
            status["running"]
            and status["model_name"] == model_id
            and self._server_info is not None
            and self._server_info.port == status["port"]
            and self._server_info.model_info.id == model_id
        ):
            return self._server_info
        result = await self._manager.ensure_server(
            model_id,
            before_restart=self._check_restart,
        )
        return await self._publish(result)

    @asynccontextmanager
    async def connect(self, context, model_id):
        purpose = context.connection_purpose
        key = object()
        try:
            async with self._operation(
                initialize=purpose == "inference",
            ) as manager:
                if self._manually_stopped or manager is None:
                    raise SDKError(
                        "Start the local server in Local Model Management first",
                    )
                status = manager.get_server_status()
                if purpose == "check":
                    if (
                        not status["running"]
                        or status["model_name"] != model_id.strip()
                    ):
                        raise SDKError(
                            "Start this local model in Local Model Management first",
                        )
                    port = status["port"]
                else:
                    if purpose == "probe" and (
                        self._server_info is None
                        or self._server_info.model_info.id != model_id
                    ):
                        raise SDKError(
                            "This local model is no longer published",
                        )
                    # Management publishes exactly one model. Other catalog
                    # shapes do not identify a single managed server.
                    published = self.handle.published_model_ids
                    if len(published) == 1 and model_id != published[0]:
                        raise SDKError(
                            f"Local Model Management selected "
                            f"{published[0]!r}; cannot serve {model_id!r}",
                        )
                    result = await self._ensure_server(model_id)
                    port = result.port
                    status = manager.get_server_status()
                self._users[key] = status["pid"]
            yield f"http://127.0.0.1:{port}/v1"
        finally:
            self._users.pop(key, None)

    async def close(self):
        async with self._lock:
            if self.closed:
                return
            if self._users:
                raise PluginBusyError(self.context.plugin_id, len(self._users))
            self._failed = True
            if self._manager is not None:
                await self._manager.close()
            self.closed = True
