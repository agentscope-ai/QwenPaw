# -*- coding: utf-8 -*-
"""Local resource ownership through the real Plugin v2 loader."""

# pylint: disable=protected-access

import asyncio
import importlib
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from qwenpaw.plugins import PluginBusyError
from qwenpaw.plugins._providers import ProviderTurn
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.plugins.testing import PluginTestHost

from qwenpaw.plugins.local_model_legacy import bundled_local_source


@dataclass
class LocalModelInfo:
    id: str
    name: str
    supports_image: bool = True
    supports_multimodal: bool = True
    supports_video: bool = False
    probe_source: str = "probed"


@dataclass
class LocalServerInfo:
    port: int
    model_info: LocalModelInfo


class Backend:
    def __init__(self):
        self.starts = 0
        self.served = None
        self.fail_close = False

    async def start(self, data_dir):
        self.data_dir = data_dir

    def get_server_status(self):
        return {
            "running": self.served is not None,
            "model_name": self.served,
            "port": 43111 if self.served is not None else None,
        }

    def list_downloaded_models(self):
        return []

    def check_installability(self):
        return True, ""

    def check_installation(self):
        return True, ""

    def is_server_transitioning(self):
        return False

    async def server_ready(self, timeout=120):
        assert timeout > 0
        return self.served is not None

    async def start_runtime_download(self):
        was_running = self.served is not None
        self.served = None
        return was_running

    async def ensure_server(self, model_id):
        if model_id != self.served:
            self.starts += 1
            self.served = model_id
        return LocalServerInfo(
            port=43111,
            model_info=LocalModelInfo(
                id=model_id,
                name=model_id,
                supports_image=True,
                supports_multimodal=True,
                supports_video=False,
                probe_source="probed",
            ),
        )

    async def stop_server(self):
        self.served = None

    async def close(self):
        if self.fail_close:
            raise RuntimeError("process remains alive")
        await self.stop_server()
        return True


async def load_backend(host, tmp_path):
    ctx = await host.load(
        bundled_local_source(),
        config={"data_dir": str(tmp_path / "local_models")},
    )
    binding = (
        PluginRegistry()
        .get_provider("qwenpaw-local")
        .provider_class._sdk_binding
    )
    runtime = binding.spec.connect.__self__
    package = type(runtime).__module__.rsplit(".", 1)[0]
    manager = importlib.import_module(package + ".manager")
    original = manager.LocalModelManager
    manager.LocalModelManager = Backend
    ctx.resources.defer(
        lambda: setattr(manager, "LocalModelManager", original),
    )
    return binding, runtime


async def call_model(model, call):
    binding = (
        PluginRegistry()
        .get_provider("qwenpaw-local")
        .provider_class._sdk_binding
    )
    model._call_native = call
    model.client.with_options = SimpleNamespace
    return await binding.call(model)


async def test_registration_is_lazy_and_server_reused(tmp_path):
    from qwenpaw.providers.provider_manager import ProviderManager

    async with PluginTestHost(tmp_path / "host") as host:
        binding, runtime = await load_backend(host, tmp_path)
        assert (
            ProviderManager.get_instance()
            .get_provider("copaw-local")
            ._sdk_binding
            is binding
        )
        assert runtime._manager is None
        backends = []
        for _ in range(2):
            turn = ProviderTurn()
            try:
                for _ in range(2):
                    async with binding.connect("local-A"):
                        pass
                backends.append(runtime._manager)
            finally:
                await turn.close()
            assert not runtime._users
            assert runtime._manager.served == "local-A"
        assert backends[0] is backends[1]
        assert runtime._manager.starts == 1
        provider = ProviderManager.get_instance().get_provider("qwenpaw-local")
        assert provider.base_url == "http://127.0.0.1:43111/v1"
        assert provider.extra_models[0].supports_image is True
        assert provider.extra_models[0].probe_source == "probed"


@pytest.mark.parametrize("early_close", [False, True])
@pytest.mark.parametrize("failing_finally", [False, True])
async def test_runtime_releases_provider_even_if_finally_hook_fails(
    tmp_path,
    early_close,
    failing_finally,
):
    from agentscope.message import Msg, TextBlock
    from qwenpaw.runtime.hooks import HookAction, HookResult
    from qwenpaw.runtime.phases import Phase
    from qwenpaw.runtime.runtime import Runtime

    async with PluginTestHost(tmp_path / "host") as host:
        binding, local = await load_backend(host, tmp_path)

        async def hook(phase, _context):
            if phase == Phase.PRE_DISPATCH:
                async with binding.connect("local-A"):
                    pass
                return HookResult(
                    HookAction.SHORT_CIRCUIT,
                    Msg(
                        name="test",
                        role="assistant",
                        content=[TextBlock(text="done")],
                    ),
                )
            if phase == Phase.FINALLY and failing_finally:
                raise RuntimeError("final hook failed")
            return HookResult()

        workspace = SimpleNamespace(
            agent_id="test",
            workspace_dir=tmp_path,
            plugins=SimpleNamespace(hook_registry=SimpleNamespace(run=hook)),
        )
        runtime = Runtime(workspace=workspace, app_services=None)
        stream = runtime.run({"session_id": "test"})
        await anext(stream)
        assert local._users

        async def finish():
            if early_close:
                await stream.aclose()
            else:
                async for _ in stream:
                    pass

        try:
            if failing_finally:
                with pytest.raises(RuntimeError, match="final hook failed"):
                    await finish()
            else:
                await finish()
        finally:
            await stream.aclose()
        assert not local._users
        assert (await host.unload("local-llamacpp")).quiescent


async def test_local_crash_and_model_switch_use_existing_backend(tmp_path):
    from qwenpaw.plugins.errors import SDKError

    async with PluginTestHost(tmp_path / "host") as host:
        binding, runtime = await load_backend(host, tmp_path)
        turn = ProviderTurn()
        try:
            async with binding.connect("local-A"):
                pass
            runtime._manager.served = None  # Native process exited.
            async with binding.connect("local-A"):
                pass
            assert runtime._manager.starts == 2
            async with binding.connect("local-B"):
                pass
            assert runtime._manager.starts == 3
            assert runtime._manager.served == "local-B"
        finally:
            await turn.close()
        with pytest.raises(SDKError, match="Cannot delete"):
            await runtime.remove_downloaded_model("local-B")


async def test_turn_lease_survives_between_model_calls(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        binding, runtime = await load_backend(host, tmp_path)
        between_calls, finish = asyncio.Event(), asyncio.Event()

        async def run():
            turn = ProviderTurn()
            try:
                async with binding.connect("local-A"):
                    pass
                between_calls.set()
                await finish.wait()
            finally:
                await turn.close()

        task = asyncio.create_task(run())
        await between_calls.wait()
        try:
            with pytest.raises(PluginBusyError):
                await host.reload("local-llamacpp")
            await runtime.stop_server()
            assert runtime._manager.served is None
            await runtime.ensure_server("local-B")
            assert runtime._manager.served == "local-B"
        finally:
            finish.set()
            await task
        await runtime.ensure_server("local-B")
        assert runtime._manager.starts == 2
        assert (await host.unload("local-llamacpp")).quiescent


@pytest.mark.parametrize("consume", [False, True])
async def test_direct_stream_releases_even_when_closed_before_read(
    tmp_path,
    consume,
):
    async with PluginTestHost(tmp_path / "host") as host:
        _binding, runtime = await load_backend(host, tmp_path)
        model = SimpleNamespace(
            qwenpaw_provider_id="qwenpaw-local",
            model="local-A",
            client=SimpleNamespace(base_url="old-port"),
            stream=True,
        )

        async def native():
            async def chunks():
                yield "one"
                yield "two"

            return chunks()

        # Creation may happen in a task which ends before stream consumption.
        stream = await asyncio.create_task(call_model(model, native))
        if consume:
            assert await anext(stream) == "one"
            assert model.client.base_url == "old-port"
            with pytest.raises(PluginBusyError):
                await host.reload("local-llamacpp")
            await runtime.stop_server()
            assert runtime._manager.served is None
        else:
            assert runtime._manager is None
        await stream.aclose()
        await runtime.stop_server()


async def test_failed_close_retains_backend_until_retry(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        _binding, runtime = await load_backend(host, tmp_path)
        await runtime.ensure_server("local-A")
        runtime._manager.fail_close = True
        try:
            result = await host.reload("local-llamacpp")
            assert not result.ok
            assert not runtime.closed
            assert runtime._manager.served == "local-A"
        finally:
            runtime._manager.fail_close = False
        assert (await host.unload("local-llamacpp")).quiescent
        assert PluginRegistry().get_provider("qwenpaw-local") is None


async def test_bundle_load_does_not_import_backend_or_download_packages(
    tmp_path,
    monkeypatch,
):
    import sys

    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    monkeypatch.setitem(sys.modules, "modelscope", None)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(bundled_local_source())
        binding = (
            PluginRegistry()
            .get_provider("qwenpaw-local")
            .provider_class._sdk_binding
        )
        runtime = binding.spec.connect.__self__
        assert runtime._manager is None
        package = type(runtime).__module__.rsplit(".", 1)[0]
        hardware = importlib.import_module(package + ".hardware")
        monkeypatch.setattr(hardware, "get_os_name", lambda: "linux")
        monkeypatch.setattr(hardware, "get_architecture", lambda: "x64")
        # Registration and installed-model management do not import
        # download SDKs.
        config = (await runtime.manager()).get_config()
        assert config.max_context_length == 65536
        assert (await host.unload("local-llamacpp")).quiescent


async def test_local_dataclasses_preserve_management_http_responses(tmp_path):
    from unittest.mock import AsyncMock
    from qwenpaw.providers.model_info import ModelInfo
    from qwenpaw.plugins.providers import ModelInfo as SDKModelInfo

    async with PluginTestHost(tmp_path / "host") as host:
        _binding, runtime = await load_backend(host, tmp_path)
        package = type(runtime).__module__.rsplit(".", 1)[0]
        types = importlib.import_module(package + ".model_types")
        model = types.LocalModelInfo(
            id="owner/model",
            name="Model",
            downloaded=True,
            source=types.DownloadSource.HUGGINGFACE,
            supports_image=True,
        )
        manager = await runtime.manager()
        manager.get_config = lambda: types.LocalModelConfig(port=43111)
        manager.get_recommended_models = lambda: [model]
        manager.list_downloaded_models = lambda: []
        runtime.ensure_server = AsyncMock(
            return_value=types.LocalServerInfo(port=43111, model_info=model),
        )
        await runtime.handle.update(
            models=(
                SDKModelInfo(
                    id=model.id,
                    name=model.name,
                    supports_multimodal=False,
                ),
            ),
        )
        config = await host.request("GET", "/api/local-models/config")
        assert config.status == 200
        assert config.json() == {"max_context_length": 65536, "port": 43111}
        models = await host.request("GET", "/api/local-models/models")
        assert models.status == 200
        assert models.json()[0]["source"] == "huggingface"
        started = await host.request(
            "POST",
            "/api/local-models/server",
            json={"model_id": model.id},
        )
        assert started.status == 200
        assert started.json()["model_info"]["supports_image"] is True
        assert started.json()["model_info"]["source"] == "builtin"
        assert ModelInfo.model_validate(started.json()["model_info"]) == (
            ModelInfo(id=model.id, name=model.name, supports_image=True)
        )
        invalid = await host.request(
            "PUT",
            "/api/local-models/config",
            json={"port": 0},
        )
        assert invalid.status == 422


async def test_existing_provider_settings_and_path_survive_unload(tmp_path):
    from qwenpaw.providers.provider_manager import ProviderManager

    async with PluginTestHost(tmp_path / "host") as host:
        binding, _runtime = await load_backend(host, tmp_path)
        manager = ProviderManager.get_instance()
        await manager.update_provider_async(
            "qwenpaw-local",
            {"base_url": "http://127.0.0.1:43111/v1"},
        )
        await manager.update_provider_async(
            "qwenpaw-local",
            {
                "generate_kwargs": {"temperature": 0.3},
                "extra_models": [
                    {
                        "id": "local-A",
                        "name": "A",
                        "is_free": True,
                        "max_input_length": 65536,
                        "max_input_length_configured": True,
                        "generate_kwargs": {"top_p": 0.7},
                    },
                ],
            },
        )
        path = manager._provider_config_path("qwenpaw-local")
        assert path == manager.plugin_path / "qwenpaw-local.json"
        assert (
            manager.get_provider("qwenpaw-local").extra_models[0].is_free
        ), "before connect"
        async with binding.connect("local-A"):
            pass
        provider = manager.get_provider("qwenpaw-local")
        model = provider.extra_models[0]
        assert model.max_input_length == 65536
        assert model.max_input_length_configured
        assert model.is_free
        assert model.generate_kwargs == {"top_p": 0.7}
        assert model.supports_image
        assert (
            len(
                [
                    p
                    for p in await manager.list_provider_info()
                    if p.id == "qwenpaw-local"
                ],
            )
            == 1
        )
        await binding.update(generate_kwargs={"temperature": 0.6})
        await manager.activate_model("qwenpaw-local", "local-A")
        await host.unload("local-llamacpp")
        assert manager.get_provider("qwenpaw-local") is None
        assert path.exists()
        binding, _runtime = await load_backend(host, tmp_path)
        restored = manager.get_provider("qwenpaw-local")
        assert restored.generate_kwargs == {"temperature": 0.6}
        assert restored.extra_models == provider.extra_models
        assert manager.active_model.model == "local-A"
        assert manager._provider_config_path("qwenpaw-local") == path
        assert restored.get_chat_model_instance("local-A") is not None


async def test_only_explicit_server_start_selects_the_model(tmp_path):
    from qwenpaw.providers.provider_manager import (
        ProviderManager,
        ModelSlotConfig,
    )

    async with PluginTestHost(tmp_path / "host") as host:
        binding, runtime = await load_backend(host, tmp_path)
        manager = ProviderManager.get_instance()
        cloud = ModelSlotConfig(provider_id="openai", model="cloud")
        await manager.save_active_model_async(cloud)
        async with binding.connect("local-A"):
            pass
        assert manager.active_model == cloud
        for model_id in ("local-A", "local-B"):
            started = await host.request(
                "POST",
                "/api/local-models/server",
                json={"model_id": model_id},
            )
            assert started.status == 200
            assert runtime._manager.served == model_id
            assert manager.active_model.provider_id == "qwenpaw-local"
            assert manager.active_model.model == model_id
            assert manager.load_active_model() == manager.active_model
        stopped = await host.request("DELETE", "/api/local-models/server")
        assert stopped.status == 200
        assert manager.active_model is None
        assert manager.load_active_model() is None


async def test_restore_failure_preserves_settings_and_allows_retry(
    tmp_path,
    monkeypatch,
):
    from unittest.mock import AsyncMock
    from qwenpaw.plugins._providers import restore_selected_providers
    from qwenpaw.plugins.providers import ModelInfo
    from qwenpaw.providers.provider_manager import ProviderManager

    async with PluginTestHost(tmp_path / "host") as host:
        binding, runtime = await load_backend(host, tmp_path)
        await runtime.handle.update(
            base_url="http://127.0.0.1:43111/v1",
            models=(ModelInfo("local-A", "A", supports_multimodal=False),),
            generate_kwargs={"temperature": 0.3},
        )
        await runtime.handle.select("local-A")
        manager = ProviderManager.get_instance()
        path = manager._provider_config_path("qwenpaw-local")
        before = path.read_bytes()
        pending = []
        with monkeypatch.context() as patch:
            patch.setattr(
                Backend,
                "ensure_server",
                AsyncMock(side_effect=RuntimeError("not installed")),
            )
            patch.setattr(
                binding.context.resources,
                "task",
                lambda operation, name: pending.append(operation),
            )
            restore_selected_providers(PluginRegistry())
            assert len(pending) == 1
            await asyncio.gather(*pending)
        assert path.read_bytes() == before
        assert manager.active_model.model == "local-A"
        async with binding.connect("local-A"):
            pass
        assert runtime._manager.served == "local-A"
        assert binding.provider().generate_kwargs == {"temperature": 0.3}


async def test_management_routes_follow_plugin_lifecycle(tmp_path):
    from qwenpaw.providers.provider_manager import ProviderManager

    async with PluginTestHost(tmp_path / "host") as host:
        assert (
            await host.request("GET", "/api/local-models/server")
        ).status == 404
        assert (
            await host.request("GET", "/api/local-models/config")
        ).status == 404
        binding, runtime = await load_backend(host, tmp_path)
        response = await host.request(
            "POST",
            "/api/local-models/server",
            json={"model_id": "local-A"},
        )
        assert response.status == 200
        response = await host.request("GET", "/api/local-models/server")
        assert response.json()["available"]
        assert (
            await host.request("GET", "/api/local-models/unknown")
        ).status == 404
        turn = ProviderTurn()
        try:
            async with binding.connect("local-A"):
                pass
            repeated = await host.request(
                "POST",
                "/api/local-models/server",
                json={"model_id": "local-A"},
            )
            assert repeated.status == 200
            switched = await host.request(
                "POST",
                "/api/local-models/server",
                json={"model_id": "local-B"},
            )
            assert switched.status == 200
            assert runtime._manager.served == "local-B"
            removed = []
            runtime._manager.remove_downloaded_model = removed.append
            assert (
                await host.request(
                    "DELETE",
                    "/api/local-models/models/local-C",
                )
            ).status == 200
            assert removed == ["local-C"]
            assert (
                await host.request(
                    "DELETE",
                    "/api/local-models/models/local-B",
                )
            ).status == 409
            assert runtime._manager.served == "local-B"
            for method, path in [
                ("DELETE", "server"),
                ("POST", "server/download"),
            ]:
                assert (
                    await host.request(method, f"/api/local-models/{path}")
                ).status == 200
            assert runtime._manager.served is None
        finally:
            await turn.close()
        response = await host.request(
            "POST",
            "/api/local-models/server/download",
        )
        assert response.status == 200
        manager = ProviderManager.get_instance()
        assert (
            manager.active_model is None
            or manager.active_model.provider_id != "qwenpaw-local"
        )
        assert (await host.unload("local-llamacpp")).quiescent
        response = await host.request("GET", "/api/local-models/server")
        assert response.status == 404
        assert (
            await host.request("DELETE", "/api/local-models/server")
        ).status == 404


@pytest.mark.parametrize("operation", ["stop", "runtime-download"])
@pytest.mark.parametrize("selected_provider", ["qwenpaw-local", "openai"])
async def test_stopping_service_clears_only_local_default_selection(
    tmp_path,
    operation,
    selected_provider,
):
    from qwenpaw.providers.provider_manager import (
        ProviderManager,
        ModelSlotConfig,
    )

    async with PluginTestHost(tmp_path / "host") as host:
        binding, runtime = await load_backend(host, tmp_path)
        await runtime.ensure_server("local-A")
        manager = ProviderManager.get_instance()
        selection = ModelSlotConfig(
            provider_id=selected_provider,
            model="local-A",
        )
        await manager.save_active_model_async(selection)
        turn = ProviderTurn()
        try:
            async with binding.connect("local-A"):
                pass
            response = await host.request(
                "DELETE" if operation == "stop" else "POST",
                "/api/local-models/server"
                if operation == "stop"
                else "/api/local-models/server/download",
            )
            assert response.status == 200
            assert runtime._manager.served is None
            provider = manager.get_provider("qwenpaw-local")
            assert provider.base_url == ""
            assert provider.extra_models == []
            expected = (
                None if selected_provider == "qwenpaw-local" else selection
            )
            assert manager.active_model == expected
            assert manager.load_active_model() == expected
        finally:
            await turn.close()


async def test_model_list_and_download_progress_do_not_publish_provider_state(
    tmp_path,
):
    async with PluginTestHost(tmp_path / "host") as host:
        binding, runtime = await load_backend(host, tmp_path)
        manager = await runtime.manager()
        manager.get_recommended_models = lambda: []
        manager.get_model_download_progress = lambda: {
            "status": "completed",
            "downloaded_bytes": 1,
            "speed_bytes_per_sec": 0.0,
        }
        before = binding.provider().model_dump()
        for path in ["models", "models/download"]:
            assert (
                await host.request("GET", f"/api/local-models/{path}")
            ).status == 200
        assert binding.provider().model_dump() == before


@pytest.mark.parametrize("source", ["auto", "modelscope", "huggingface"])
async def test_download_route_preserves_the_selected_source(tmp_path, source):
    async with PluginTestHost(tmp_path / "host") as host:
        _binding, runtime = await load_backend(host, tmp_path)
        manager = await runtime.manager()
        downloads = []
        manager.start_model_download = (
            lambda model, *, source: downloads.append((model, source.value))
        )
        response = await host.request(
            "POST",
            "/api/local-models/models/download",
            json={"model_name": "local-A", "source": source},
        )
        assert response.status == 200
        assert downloads == [("local-A", source)]


async def test_turn_end_closes_open_model_stream(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        _binding, runtime = await load_backend(host, tmp_path)
        closed = asyncio.Event()

        async def native():
            async def chunks():
                try:
                    yield "one"
                    yield "two"
                finally:
                    closed.set()

            return chunks()

        turn = ProviderTurn()
        stream = await call_model(
            SimpleNamespace(
                qwenpaw_provider_id="qwenpaw-local",
                model="local-A",
                client=SimpleNamespace(base_url="old"),
                stream=True,
            ),
            native,
        )
        try:
            assert await anext(stream) == "one"
            await turn.close()
            assert (
                closed.is_set()
            ), "Turn ended but HTTP producer is still suspended"
            assert not runtime._users
        finally:
            await stream.aclose()
            await turn.close()


async def test_cross_task_consumption_keeps_original_turn(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        _binding, runtime = await load_backend(host, tmp_path)
        created = asyncio.get_running_loop().create_future()
        finish = asyncio.Event()

        async def native():
            async def chunks():
                yield "one"
                yield "two"

            return chunks()

        async def owner():
            turn = ProviderTurn()
            try:
                created.set_result(
                    await call_model(
                        SimpleNamespace(
                            qwenpaw_provider_id="qwenpaw-local",
                            model="local-A",
                            client=SimpleNamespace(base_url="old"),
                            stream=True,
                        ),
                        native,
                    ),
                )
                await finish.wait()
            finally:
                await turn.close()

        task = asyncio.create_task(owner())
        stream = await created
        try:
            assert await anext(stream) == "one"
            await stream.aclose()
            with pytest.raises(PluginBusyError):
                await host.reload("local-llamacpp")
            await runtime.stop_server()
            assert runtime._manager.served is None
        finally:
            finish.set()
            await task
        assert not runtime._users


async def test_stream_cannot_start_after_owning_turn_ends(tmp_path):
    from qwenpaw.plugins.errors import StaleContextError

    async with PluginTestHost(tmp_path / "host") as host:
        _binding, runtime = await load_backend(host, tmp_path)

        async def native():
            raise AssertionError("Native call must not start")

        turn = ProviderTurn()
        stream = await call_model(
            SimpleNamespace(
                qwenpaw_provider_id="qwenpaw-local",
                model="local-A",
                client=SimpleNamespace(base_url="old"),
                stream=True,
            ),
            native,
        )
        await turn.close()
        with pytest.raises(StaleContextError):
            await anext(stream)
        assert runtime._manager is None
