# -*- coding: utf-8 -*-
"""Local resource ownership through the real Plugin v2 loader."""

# pylint: disable=protected-access

import asyncio
import importlib
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from qwenpaw.plugins import PluginBusyError, SDKError
from qwenpaw.runtime.provider_turn import ProviderTurn
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.plugins.testing import PluginTestHost

from qwenpaw.plugins.local_model_legacy import bundled_local_source


@asynccontextmanager
async def agent_turn():
    turn = ProviderTurn()
    try:
        with turn.bind():
            yield turn
    finally:
        await turn.close()


@dataclass
class LocalModelInfo:
    id: str
    name: str
    supports_image: bool = True
    supports_multimodal: bool = True
    supports_video: bool = False
    probe_source: str = "probed"
    model_type: str = "chat"


@dataclass
class LocalServerInfo:
    port: int
    model_info: LocalModelInfo


class Backend:
    def __init__(self):
        self.starts = 0
        self.served = None
        self.fail_close = False
        self.port = 43111
        self.removed = []

    async def start(self, data_dir):
        self.data_dir = data_dir

    def get_server_status(self):
        return {
            "running": self.served is not None,
            "model_name": self.served,
            "port": self.port if self.served is not None else None,
            "pid": self.starts if self.served is not None else None,
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

    async def ensure_server(self, model_id, before_restart=None):
        if model_id != self.served:
            if self.served is not None and before_restart is not None:
                before_restart(self.starts)
            self.starts += 1
            self.served = model_id
        return LocalServerInfo(
            port=self.port,
            model_info=LocalModelInfo(
                id=model_id,
                name=model_id,
                supports_image=True,
                supports_multimodal=True,
                supports_video=False,
                probe_source="probed",
            ),
        )

    def remove_downloaded_model(self, model_id):
        if model_id == self.served:
            raise SDKError("Cannot delete a model while it is running")
        self.removed.append(model_id)

    async def stop_server(self):
        self.served = None

    async def close(self):
        if self.fail_close:
            raise RuntimeError("process remains alive")
        await self.stop_server()
        return True


async def load_backend(host, tmp_path, *, data_dir=None):
    ctx = await host.load(
        bundled_local_source(),
        config={"data_dir": str(data_dir or tmp_path / "local_models")},
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


async def test_data_root_normalizes_symlinks(tmp_path):
    target = tmp_path / "models"
    target.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks are unavailable")
    async with PluginTestHost(tmp_path / "host") as host:
        _binding, runtime = await load_backend(
            host,
            tmp_path,
            data_dir=alias,
        )
        manager = await runtime.manager()
        assert manager.data_dir == target.resolve()
        assert await runtime.context.storage.aread_json("data-root.json") == {
            "data_dir": str(target.resolve()),
        }


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
            async with agent_turn():
                for _ in range(2):
                    async with binding.connect("local-A"):
                        pass
                backends.append(runtime._manager)
            assert not runtime._users
            assert runtime._manager.served == "local-A"
        assert backends[0] is backends[1]
        assert runtime._manager.starts == 1
        provider = ProviderManager.get_instance().get_provider("qwenpaw-local")
        assert provider.base_url == "http://127.0.0.1:43111/v1"
        assert provider.extra_models == []


@pytest.mark.parametrize("selected", [False, True])
async def test_doctor_reads_files_and_runtime_without_starting_manager(
    tmp_path,
    selected,
):
    from qwenpaw.plugins.doctor import DOCTOR, DoctorContext, DoctorResult

    async with PluginTestHost(tmp_path / "host") as host:
        _binding, runtime = await load_backend(host, tmp_path)
        contributions = PluginRegistry().get_extensions(DOCTOR)
        assert {check.id for check in contributions} == {
            "local-model",
            "local-server",
        }
        for contribution in contributions:
            await contribution.admit()

        async def check(call):
            notes = []
            for contribution in contributions:
                with contribution.invocation() as spec:
                    notes.extend(await spec.check(call))
            return notes

        requests = []

        async def get_runtime(path):
            requests.append(path)
            response = await host.request("GET", "/api/" + path)
            assert response.status == 200
            return response.json()

        call = DoctorContext(None, None, "http://app", 1, False, get_runtime)
        notes = await check(call)
        assert [note.status for note in notes] == ["SKIP"]
        assert not requests
        directory = await runtime.data_directory()
        assert not directory.exists()
        call = DoctorContext(
            None,
            None,
            "http://app",
            1,
            True,
            get_runtime,
            selected_providers=(
                frozenset({"qwenpaw-local"}) if selected else frozenset()
            ),
        )
        notes = await check(call)
        assert requests == ["local-models/diagnostics"]
        assert [
            note.status for note in notes if isinstance(note, DoctorResult)
        ] == [
            "FAIL" if selected else "SKIP",
            "SKIP",
        ]
        assert runtime._manager is None
        assert not directory.exists()
        assert (
            await runtime.context.storage.aread_json("data-root.json", None)
            is None
        )
        await runtime.start_server("local-A")
        status = await get_runtime("local-models/diagnostics")
        assert status["running"] and status["model_name"] == "local-A"
        assert (await host.unload("local-llamacpp")).quiescent
        assert (
            await host.request("GET", "/api/local-models/diagnostics")
        ).status == 404
        assert not PluginRegistry().get_extensions(DOCTOR)


@pytest.mark.parametrize(
    ("early_close", "failing_finally"),
    [(False, False), (True, True)],
)
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
        binding, _local = await load_backend(host, tmp_path)

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
        assert host.resource_snapshot("local-llamacpp")["active_calls"] == 1

        async def finish():
            if early_close:
                await asyncio.create_task(stream.aclose())
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
        assert host.resource_snapshot("local-llamacpp")["active_calls"] == 0
        async with binding.connect("local-A"):
            pass
        assert (await host.unload("local-llamacpp")).quiescent


async def test_cancelled_agent_close_releases_native_stream(tmp_path):
    from agentscope.message import Msg, TextBlock
    from qwenpaw.runtime.hooks import HookAction, HookResult
    from qwenpaw.runtime.phases import Phase
    from qwenpaw.runtime.runtime import Runtime

    async with PluginTestHost(tmp_path / "host") as host:
        _, local = await load_backend(host, tmp_path)
        closing = asyncio.Event()
        native_stream = None

        async def close():
            closing.set()
            await asyncio.Event().wait()

        async def native():
            async def chunks():
                yield "one"
                yield "two"

            return chunks()

        async def hook(phase, context):
            nonlocal native_stream
            if phase != Phase.PRE_DISPATCH:
                return HookResult()
            context.agent = SimpleNamespace(close=close)
            native_stream = await call_model(
                SimpleNamespace(
                    model="local-A",
                    client=SimpleNamespace(),
                    stream=True,
                ),
                native,
            )
            assert await anext(native_stream) == "one"
            return HookResult(
                HookAction.SHORT_CIRCUIT,
                Msg(
                    name="test",
                    role="assistant",
                    content=[TextBlock(text="done")],
                ),
            )

        workspace = SimpleNamespace(
            agent_id="test",
            workspace_dir=tmp_path,
            plugins=SimpleNamespace(hook_registry=SimpleNamespace(run=hook)),
        )
        stream = Runtime(workspace=workspace, app_services=None).run(
            {"session_id": "test"},
        )
        await anext(stream)
        assert local._users
        request = asyncio.create_task(stream.aclose())
        try:
            await asyncio.wait_for(closing.wait(), timeout=5)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            assert not local._users
            assert (
                host.resource_snapshot("local-llamacpp")["active_calls"] == 0
            )
        finally:
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)
            if native_stream is not None:
                await native_stream.aclose()


async def test_local_crash_and_model_switch_use_existing_backend(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        binding, runtime = await load_backend(host, tmp_path)
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
        with pytest.raises(SDKError, match="Cannot delete"):
            await runtime.remove_downloaded_model("local-B")


async def test_running_stream_prevents_replacing_its_model(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        binding, runtime = await load_backend(host, tmp_path)

        async def native():
            async def chunks():
                yield "one"
                yield "two"

            return chunks()

        turn = ProviderTurn()
        with turn.bind():
            stream = await call_model(
                SimpleNamespace(
                    model="local-A",
                    client=SimpleNamespace(base_url="old"),
                    stream=True,
                ),
                native,
            )
            try:
                assert await anext(stream) == "one"
                async with binding.connect("local-A") as endpoint:
                    assert endpoint == "http://127.0.0.1:43111/v1"
                assert runtime._manager.starts == 1
                with pytest.raises(PluginBusyError):
                    async with binding.connect("local-B"):
                        pytest.fail("The active model was replaced")
                response = await host.request(
                    "POST",
                    "/api/local-models/server",
                    json={"model_id": "local-B"},
                )
                assert response.status == 409
                assert runtime._manager.served == "local-A"
                assert await anext(stream) == "two"
                await stream.aclose()
                async with binding.connect("local-B"):
                    assert runtime._manager.served == "local-B"
            finally:
                await stream.aclose()
                await turn.close()


async def test_connection_check_keeps_the_running_local_model(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.providers import ProviderManager
    from qwenpaw.providers.openai_provider import OpenAIProvider
    from qwenpaw.providers.provider import ModelConnectionResult

    async with PluginTestHost(tmp_path / "host") as host:
        _, runtime = await load_backend(host, tmp_path)
        manager = ProviderManager.get_instance()
        cold = await manager.check_provider_model("qwenpaw-local", "local-A")
        assert not cold.success
        assert runtime._manager is None
        server = await runtime.start_server("local-A")
        checked = []
        entered, release = asyncio.Event(), asyncio.Event()

        async def probe(provider, model_id, timeout):
            checked.append((provider.base_url, model_id))
            entered.set()
            await release.wait()
            return ModelConnectionResult(success=True)

        monkeypatch.setattr(OpenAIProvider, "check_model_connection", probe)
        other = await manager.check_provider_model("qwenpaw-local", "local-B")
        assert not other.success
        assert other.verification == "unverified"
        check = asyncio.create_task(
            manager.check_provider_model("qwenpaw-local", "local-A"),
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            with pytest.raises(PluginBusyError):
                await runtime.start_server("local-B")
        finally:
            release.set()
            current = await check
        assert current.success
        assert checked == [(f"http://127.0.0.1:{server.port}/v1", "local-A")]
        assert runtime._manager.served == "local-A"
        assert runtime._manager.starts == 1
        selected = manager.load_active_model()
        assert (selected.provider_id, selected.model) == (
            "qwenpaw-local",
            "local-A",
        )
        await runtime.start_server("local-B")
        assert runtime._manager.served == "local-B"


async def test_cancelled_first_request_leaves_the_local_manager_ready(
    tmp_path,
    monkeypatch,
):
    async with PluginTestHost(tmp_path / "host") as host:
        _, runtime = await load_backend(host, tmp_path)
        entered, resume = asyncio.Event(), asyncio.Event()
        start = Backend.start

        async def initialize(backend, data_dir):
            await start(backend, data_dir)
            entered.set()
            await resume.wait()

        monkeypatch.setattr(Backend, "start", initialize)
        request = asyncio.create_task(runtime.manager())
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
        finally:
            request.cancel()
            resume.set()
            with pytest.raises(asyncio.CancelledError):
                await request

        server = await runtime.start_server("local-A")
        assert server.model_info.id == "local-A"
        manager = await runtime.manager()
        assert manager.data_dir == (tmp_path / "local_models").resolve()


async def test_cancelled_model_switch_keeps_the_new_endpoint(
    tmp_path,
    monkeypatch,
):
    async with PluginTestHost(tmp_path / "host") as host:
        binding, runtime = await load_backend(host, tmp_path)
        first = await runtime.start_server("local-A")
        await runtime.stop_server()
        runtime._manager.port = first.port + 1
        endpoint = f"http://127.0.0.1:{first.port + 1}/v1"
        update = runtime.handle.update
        entered, resume = asyncio.Event(), asyncio.Event()

        async def publish(**config):
            if config.get("base_url") == endpoint:
                entered.set()
                await resume.wait()
            return await update(**config)

        monkeypatch.setattr(runtime.handle, "update", publish)
        request = asyncio.create_task(runtime.start_server("local-B"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
        finally:
            request.cancel()
            resume.set()
            with pytest.raises(asyncio.CancelledError):
                await request

        from qwenpaw.providers import ProviderManager

        assert (
            ProviderManager.get_instance().load_active_model().model
            == "local-B"
        )
        assert binding.provider().base_url == endpoint
        async with binding.connect("local-B") as prepared:
            assert prepared == endpoint
        assert runtime._manager.starts == 2


async def test_multimodal_probe_persists_result_after_runtime_restarts(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.providers.multimodal_prober import ProbeResult
    from qwenpaw.providers.openai_provider import OpenAIProvider
    from qwenpaw.providers.provider_manager import ProviderManager

    async with PluginTestHost(tmp_path / "host") as host:
        binding, runtime = await load_backend(host, tmp_path)
        await runtime.start_server("local-A")
        manager = ProviderManager.get_instance()
        from fastapi import HTTPException
        from qwenpaw.app.routers.providers import probe_model_multimodal

        with pytest.raises(HTTPException) as stale:
            await probe_model_multimodal(manager, "qwenpaw-local", "local-B")
        assert stale.value.status_code == 400
        assert "no longer published" in stale.value.detail
        assert runtime._manager.served == "local-A"
        assert manager.load_active_model().model == "local-A"

        runtime._manager.served = None
        runtime._manager.port = 43112
        endpoint = "http://127.0.0.1:43112/v1"

        async def probe(provider, model_id, _timeout, image_only):
            assert provider.base_url == endpoint
            assert model_id == "local-A"
            assert image_only
            return ProbeResult(supports_image=False)

        monkeypatch.setattr(OpenAIProvider, "probe_model_multimodal", probe)
        result = await asyncio.wait_for(
            manager.probe_model_multimodal(
                "qwenpaw-local",
                "local-A",
                image_only=True,
            ),
            timeout=5,
        )
        assert result["supports_image"] is False
        provider = manager.get_provider("qwenpaw-local")
        assert provider.base_url == endpoint
        assert provider.get_model_info("local-A").supports_image is False
        async with binding.connect("local-A") as prepared:
            assert prepared == endpoint
        assert runtime._manager.starts == 2


async def test_turn_lease_survives_between_model_calls(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        binding, runtime = await load_backend(host, tmp_path)
        between_calls, finish = asyncio.Event(), asyncio.Event()

        async def run():
            async with agent_turn():
                async with binding.connect("local-A"):
                    pass
                between_calls.set()
                await finish.wait()

        task = asyncio.create_task(run())
        await between_calls.wait()
        try:
            with pytest.raises(PluginBusyError):
                await host.reload("local-llamacpp")
            await runtime.stop_server()
            assert runtime._manager.served is None
            await runtime.start_server("local-B")
            assert runtime._manager.served == "local-B"
        finally:
            finish.set()
            await task
        await runtime.start_server("local-B")
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
        await runtime.start_server("local-A")
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
    monkeypatch.setitem(sys.modules, "modelscope_hub", None)
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
        manager.ensure_server = AsyncMock(
            return_value=types.LocalServerInfo(port=43111, model_info=model),
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
        saved_model = binding.provider().extra_models[0].model_copy(deep=True)
        async with binding.connect("local-A"):
            pass
        provider = manager.get_provider("qwenpaw-local")
        model = provider.extra_models[0]
        assert model == saved_model
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
            assert manager.active_model == cloud

        async def start(model_id):
            started = await host.request(
                "POST",
                "/api/local-models/server",
                json={"model_id": model_id},
            )
            assert started.status == 200
            selected = ModelSlotConfig(
                provider_id="qwenpaw-local",
                model=model_id,
            )
            assert manager.load_active_model() == selected
            return selected

        first = await start("local-A")
        async with agent_turn():
            async with binding.connect(first.model):
                assert runtime._manager.served == first.model
            selected = await start("local-B")
            # The same turn calls A again after a tool returns.
            starts = runtime._manager.starts
            with pytest.raises(SDKError, match="local-B"):
                async with binding.connect(first.model):
                    pytest.fail("Old request replaced the selected model")
            assert runtime._manager.served == selected.model
            assert runtime._manager.starts == starts
            assert manager.load_active_model() == selected
            (published,) = binding.provider().extra_models
            assert published.id == selected.model
            assert published.supports_image is True
            assert published.probe_source == "probed"
        async with binding.connect(selected.model):
            assert runtime._manager.served == "local-B"
        stopped = await host.request("DELETE", "/api/local-models/server")
        assert stopped.status == 200
        assert manager.active_model is None
        assert manager.load_active_model() is None


@pytest.mark.parametrize("restore_first", [False, True])
async def test_reload_preserves_managed_model_before_and_after_restore(
    tmp_path,
    restore_first,
):
    from qwenpaw.providers import ProviderManager

    async with PluginTestHost(tmp_path / "host") as host:
        await load_backend(host, tmp_path)
        response = await host.request(
            "POST",
            "/api/local-models/server",
            json={"model_id": "local-B"},
        )
        assert response.status == 200
        assert (await host.unload("local-llamacpp")).quiescent
        binding, runtime = await load_backend(host, tmp_path)
        if restore_first:
            await binding.restore_selected()

        backend = await runtime.manager()
        status = backend.get_server_status()
        assert status["running"] is restore_first
        with pytest.raises(SDKError, match="local-B"):
            async with binding.connect("local-A"):
                pytest.fail("An Agent replaced the saved local model")
        assert backend.get_server_status() == status
        assert (
            ProviderManager.get_instance().load_active_model().model
            == "local-B"
        )
        assert [model.id for model in binding.provider().extra_models] == [
            "local-B",
        ]

        async with binding.connect("local-B"):
            assert backend.served == "local-B"
            assert backend.starts == 1


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
        async with agent_turn():
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
            assert (
                await host.request(
                    "DELETE",
                    "/api/local-models/models/local-C",
                )
            ).status == 200
            assert runtime._manager.removed == ["local-C"]
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
        await runtime.start_server("local-A")
        manager = ProviderManager.get_instance()
        selection = ModelSlotConfig(
            provider_id=selected_provider,
            model="local-A",
        )
        await manager.save_active_model_async(selection)
        async with agent_turn():
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


@pytest.mark.parametrize("operation", ["stop", "runtime-download"])
async def test_cancelled_server_stop_keeps_provider_in_sync(
    tmp_path,
    monkeypatch,
    operation,
):
    from qwenpaw.providers import ProviderManager

    async with PluginTestHost(tmp_path / "host") as host:
        binding, runtime = await load_backend(host, tmp_path)
        await runtime.start_server("local-A")
        manager = await runtime.manager()
        entered = asyncio.Event()
        release = asyncio.Event()

        stop = manager.stop_server

        async def stop_and_wait():
            await stop()
            entered.set()
            await release.wait()
            return True

        monkeypatch.setattr(
            manager,
            "stop_server" if operation == "stop" else "start_runtime_download",
            stop_and_wait,
        )
        request = asyncio.create_task(
            host.request("DELETE", "/api/local-models/server")
            if operation == "stop"
            else host.request("POST", "/api/local-models/server/download"),
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            request.cancel()
            await asyncio.sleep(0)
            assert not request.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await request
        finally:
            release.set()
            await asyncio.gather(request, return_exceptions=True)

        assert manager.served is None
        assert binding.provider().base_url == ""
        assert ProviderManager.get_instance().load_active_model() is None
        with pytest.raises(SDKError, match="Local Model Management"):
            async with binding.connect("local-A"):
                pytest.fail("The stopped server restarted")


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


@pytest.mark.parametrize("cross_task", [False, True])
async def test_turn_end_closes_open_model_stream(tmp_path, cross_task):
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
        with turn.bind():
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
                if cross_task:
                    await asyncio.create_task(turn.close())
                else:
                    await turn.close()
                assert (
                    closed.is_set()
                ), "Turn ended but HTTP producer is still suspended"
                assert not runtime._users
            finally:
                await stream.aclose()
                await turn.close()
        async with _binding.connect("local-A"):
            assert runtime._users
        assert not runtime._users


async def test_turn_releases_sibling_stream_when_one_close_fails(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        _, runtime = await load_backend(host, tmp_path)
        model = SimpleNamespace(
            qwenpaw_provider_id="qwenpaw-local",
            model="local-A",
            client=SimpleNamespace(base_url="old"),
            stream=True,
        )

        async def native(fail):
            async def chunks():
                try:
                    yield "one"
                finally:
                    if fail:
                        raise RuntimeError("stream cleanup failed")

            return chunks()

        turn = ProviderTurn()
        with turn.bind():
            first = await call_model(model, lambda: native(True))
            assert await anext(first) == "one"
            second = await call_model(model, lambda: native(False))
        try:
            assert await anext(second) == "one"
            with pytest.raises(RuntimeError, match="stream cleanup failed"):
                await turn.close()
            assert not runtime._users
            await host.reload("local-llamacpp")
        finally:
            await first.aclose()
            await second.aclose()


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
            async with agent_turn():
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
        with turn.bind():
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
