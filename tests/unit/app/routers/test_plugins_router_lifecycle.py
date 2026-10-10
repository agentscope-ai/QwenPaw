# -*- coding: utf-8 -*-
"""Plugin routes delegate lifecycle work and report real completion.

Router tests cover loader wiring, compatibility helpers, archive safety,
HTTP errors, and metadata. Registration and revocation belong to the
lifecycle tests rather than removed router bookkeeping helpers.
"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument
# pylint: disable=use-implicit-booleaness-not-comparison
from __future__ import annotations

import io
import json
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import plugins as plugins_module
from qwenpaw.app.routers.plugins import (
    _DOWNLOAD_TIMEOUT,
    _async_download,
    _load_plugin_with_optional_force_reinstall,
    _extract_downloaded_plugin_zip,
    _extract_plugin_zip_bytes,
    install_plugin,
    install_plugin_source,
    search_market_plugins,
    uninstall_plugin_source,
    upload_plugin,
)


@pytest.fixture(autouse=True)
def isolated_plugin_settings(monkeypatch):
    """Do not read real plugin settings for route metadata assertions."""
    monkeypatch.setattr(plugins_module, "_plugin_config_row", lambda _id: {})


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


def _zip_bytes(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buffer.getvalue()


def _record(plugin_id: str = "plug", meta: dict | None = None) -> Any:
    """A loaded-plugin record stand-in (only the fields routes read)."""
    manifest = SimpleNamespace(
        id=plugin_id,
        name=f"{plugin_id} display name",
        version="1.2.3",
        description="desc",
        author="auth",
        plugin_type="general",
        entry=SimpleNamespace(frontend="ui/index.js"),
        meta=meta if meta is not None else {},
    )
    return SimpleNamespace(
        manifest=manifest,
        source_path=Path("/nonexistent/plugin"),
        enabled=True,
        status="active",
        diagnostics=[],
    )


def _app(
    loader: Any = None,
    provider_manager: Any = None,
) -> Any:
    app = MagicMock(name="App")
    app.state.plugin_loader = loader
    app.state.provider_manager = provider_manager
    return app


def _request(app: Any) -> Any:
    return SimpleNamespace(app=app)


class _LifecycleStub:
    """Async context manager recording enter/exit order."""

    def __init__(self, log: list[str], name: str) -> None:
        self._log = log
        self._name = name

    async def __aenter__(self) -> None:
        self._log.append(f"{self._name}:enter")

    async def __aexit__(self, *exc: Any) -> None:
        self._log.append(f"{self._name}:exit")


def _loader_stub(
    log: list[str],
    *,
    record: Any = None,
    registry: Any = None,
    load_result: Any = "LOADED",
) -> MagicMock:
    """A PluginLoader stand-in recording lifecycle and load calls."""
    loader = MagicMock(name="PluginLoader")
    loader.get_loaded_plugin.return_value = record
    loader.get_all_loaded_plugins.return_value = (
        {record.manifest.id: record} if record is not None else {}
    )
    loader.registry = registry if registry is not None else MagicMock()
    loader.plugin_lifecycle.side_effect = lambda plugin_id: _LifecycleStub(
        log,
        f"lifecycle({plugin_id})",
    )
    loader.unload_plugin = AsyncMock(
        side_effect=lambda *a, **k: log.append("unload_plugin"),
    )

    def _load(**kwargs):
        log.append(
            "load_plugin_from_path:"
            f"force={kwargs.get('force')}:"
            f"before={kwargs.get('before_force_unload') is not None}:"
            f"after={kwargs.get('after_force_unload') is not None}",
        )
        return load_result

    loader.load_plugin_from_path = AsyncMock(side_effect=_load)
    return loader


class TestZipExtractionHelpers:
    def test_extract_bytes_returns_plugin_dir_and_removes_zip(self, tmp_path):
        content = _zip_bytes({"plugin.json": '{"id": "p"}', "a.txt": "A"})
        result = _extract_plugin_zip_bytes(content, tmp_path)
        assert result == tmp_path
        assert (tmp_path / "plugin.json").exists()
        assert not (tmp_path / "plugin.zip").exists()

    def test_extract_bytes_finds_nested_plugin_dir(self, tmp_path):
        content = _zip_bytes({"inner/plugin.json": '{"id": "p"}'})
        assert _extract_plugin_zip_bytes(content, tmp_path) == (
            tmp_path / "inner"
        )

    def test_extract_bytes_rejects_zip_slip(self, tmp_path):
        content = _zip_bytes({"../escape.txt": "evil"})
        with pytest.raises(ValueError, match="Zip Slip"):
            _extract_plugin_zip_bytes(content, tmp_path)
        assert not (tmp_path.parent / "escape.txt").exists()

    def test_extract_bytes_without_manifest_raises(self, tmp_path):
        with pytest.raises(ValueError, match="No plugin.json"):
            _extract_plugin_zip_bytes(_zip_bytes({"a.txt": "A"}), tmp_path)

    def test_extract_downloaded_removes_the_zip(self, tmp_path):
        zip_path = tmp_path / "downloaded.zip"
        zip_path.write_bytes(_zip_bytes({"plugin.json": '{"id": "p"}'}))
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        assert _extract_downloaded_plugin_zip(zip_path, out_dir) == out_dir
        assert not zip_path.exists()
        assert (out_dir / "plugin.json").exists()

    def test_extract_downloaded_propagates_zip_slip(self, tmp_path):
        zip_path = tmp_path / "downloaded.zip"
        zip_path.write_bytes(_zip_bytes({"../escape.txt": "evil"}))
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        with pytest.raises(ValueError, match="Zip Slip"):
            _extract_downloaded_plugin_zip(zip_path, out_dir)


# ---------------------------------------------------------------------------
# _async_download
# ---------------------------------------------------------------------------


class _FakeResponse:
    """urlopen() stand-in: a context manager yielding sized chunks."""

    def __init__(self, payload: bytes, chunk: int = 4) -> None:
        self._payload = payload
        self._chunk = chunk
        self._pos = 0
        self.read_sizes: list[int] = []

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        data = self._payload[self._pos : self._pos + min(size, self._chunk)]
        self._pos += len(data)
        return data


class TestAsyncDownload:
    async def test_writes_the_full_payload(self, tmp_path):
        dest = tmp_path / "out.bin"
        response = _FakeResponse(b"hello world")
        seen: dict[str, Any] = {}

        def _urlopen(url, timeout=None):
            seen["url"] = url
            seen["timeout"] = timeout
            return response

        with patch(
            "qwenpaw.app.routers.plugins.urllib.request.urlopen",
            side_effect=_urlopen,
        ):
            await _async_download("https://example.test/p.zip", dest)
        assert dest.read_bytes() == b"hello world"
        assert seen["url"] == "https://example.test/p.zip"
        assert seen["timeout"] == _DOWNLOAD_TIMEOUT
        assert response.read_sizes and response.read_sizes[0] == 65536

    async def test_size_cap_aborts_the_download(
        self,
        tmp_path,
        monkeypatch,
    ):
        dest = tmp_path / "out.bin"
        monkeypatch.setattr(plugins_module, "_MAX_DOWNLOAD_BYTES", 4)
        with patch(
            "qwenpaw.app.routers.plugins.urllib.request.urlopen",
            side_effect=lambda url, timeout=None: _FakeResponse(b"x" * 64),
        ):
            with pytest.raises(RuntimeError, match="Download aborted"):
                await _async_download("https://example.test/big.zip", dest)
        # only what fit under the cap was written; the rest is dropped
        assert dest.stat().st_size == 4

    async def test_urlopen_failure_propagates(self, tmp_path):
        dest = tmp_path / "out.bin"
        with patch(
            "qwenpaw.app.routers.plugins.urllib.request.urlopen",
            side_effect=OSError("network down"),
        ):
            with pytest.raises(OSError, match="network down"):
                await _async_download("https://example.test/p.zip", dest)
        assert not dest.exists()


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------


def _client(loader: Any = None, provider_manager: Any = None):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from qwenpaw.app.routers.plugins import router as plugins_router

    app = FastAPI()
    app.state.plugin_loader = loader
    app.state.provider_manager = provider_manager
    app.include_router(plugins_router, prefix="/api")
    return TestClient(app)


class TestListPluginsRoute:
    def test_without_loader_falls_back_to_disk_scan(self, tmp_path):
        monkey = tmp_path / "plugins"
        monkey.mkdir()
        (monkey / "on-disk").mkdir()
        (monkey / "on-disk" / "plugin.json").write_text(
            json.dumps({"id": "on-disk", "name": "Disk", "version": "9.9"}),
            encoding="utf-8",
        )
        with patch(
            "qwenpaw.config.utils.get_plugins_dir",
            return_value=monkey,
        ):
            response = _client(None).get("/api/plugins")
        assert response.status_code == 200
        assert response.json() == [
            {
                "id": "on-disk",
                "name": "Disk",
                "version": "9.9",
                "description": "",
                "author": "",
                "enabled": True,
                "loaded": False,
                "plugin_type": "general",
                "frontend_entry": None,
            },
        ]

    def test_with_loader_reports_loaded_records(self):
        record = _record("plug", meta={"tool_name": "alpha"})
        loader = MagicMock()
        loader.get_all_loaded_plugins.return_value = {"plug": record}
        response = _client(loader).get("/api/plugins")
        assert response.status_code == 200
        assert response.json() == [
            {
                "id": "plug",
                "name": "plug display name",
                "version": "1.2.3",
                "description": "desc",
                "author": "auth",
                "enabled": True,
                "loaded": True,
                "status": "active",
                "diagnostics": [],
                "plugin_type": "general",
                "frontend_entry": "ui/index.js",
            },
        ]

    def test_empty_loader_returns_empty_list(self):
        loader = MagicMock()
        loader.get_all_loaded_plugins.return_value = {}
        assert _client(loader).get("/api/plugins").json() == []


class TestGetPluginStatusRoute:
    def test_loaded_plugin_reports_runtime_state(self):
        loader = MagicMock()
        loader.get_loaded_plugin.return_value = _record("plug")
        response = _client(loader).get("/api/plugins/plug/status")
        assert response.status_code == 200
        assert response.json() == {
            "id": "plug",
            "loaded": True,
            "enabled": True,
            "status": "active",
            "diagnostics": [],
            "version": "1.2.3",
        }

    def test_on_disk_but_not_loaded(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        (plugins_dir / "plug").mkdir(parents=True)
        (plugins_dir / "plug" / "plugin.json").write_text(
            "{}",
            encoding="utf-8",
        )
        loader = MagicMock()
        loader.get_loaded_plugin.return_value = None
        with patch(
            "qwenpaw.config.utils.get_plugins_dir",
            return_value=plugins_dir,
        ):
            response = _client(loader).get("/api/plugins/plug/status")
        assert response.json() == {
            "id": "plug",
            "loaded": False,
            "enabled": True,
        }

    def test_unknown_plugin_is_404(self, tmp_path):
        loader = MagicMock()
        loader.get_loaded_plugin.return_value = None
        with patch(
            "qwenpaw.config.utils.get_plugins_dir",
            return_value=tmp_path / "plugins",
        ):
            response = _client(loader).get("/api/plugins/ghost/status")
        assert response.status_code == 404
        assert "ghost" in response.json()["detail"]

    def test_dir_without_manifest_is_404(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        (plugins_dir / "plug").mkdir(parents=True)
        loader = MagicMock()
        loader.get_loaded_plugin.return_value = None
        with patch(
            "qwenpaw.config.utils.get_plugins_dir",
            return_value=plugins_dir,
        ):
            response = _client(loader).get("/api/plugins/plug/status")
        assert response.status_code == 404


class TestLoaderNotReady:
    """Every mutating route must 503 before the loader exists."""

    def test_install_is_503(self):
        response = _client(None).post(
            "/api/plugins/install",
            json={"source": "/tmp/x"},
        )
        assert response.status_code == 503
        assert "not ready" in response.json()["detail"]

    def test_uninstall_is_503(self):
        response = _client(None).delete("/api/plugins/plug")
        assert response.status_code == 503

    def test_upload_is_503(self):
        response = _client(None).post(
            "/api/plugins/upload",
            files={"file": ("p.zip", _zip_bytes({"plugin.json": "{}"}))},
        )
        assert response.status_code == 503

    async def test_install_source_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="not ready"):
            await install_plugin_source("/tmp/x", app=_app(None))

    async def test_uninstall_source_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="not ready"):
            await uninstall_plugin_source("plug", app=_app(None))


# ---------------------------------------------------------------------------
# _load_plugin_with_optional_force_reinstall
# ---------------------------------------------------------------------------


class TestLoadPluginWithOptionalForceReinstall:
    @pytest.mark.parametrize("force", [False, True])
    async def test_delegates_transaction_and_forwards_pawport_flags(
        self,
        tmp_path,
        force,
    ):
        log = []
        loader = _loader_stub(log)
        record = _record()

        async def load(**kwargs):
            if force:
                kwargs["before_force_unload"]("plug")
            assert "after_force_unload" not in kwargs
            assert "after_load" not in kwargs
            return record

        loader.load_plugin_from_path.side_effect = load
        with (
            patch(
                "qwenpaw.config.utils.get_plugins_dir",
                return_value=tmp_path,
            ),
        ):
            result = await _load_plugin_with_optional_force_reinstall(
                loader,
                _request(_app(loader)),
                tmp_path,
                force=force,
                reload_agents=False,
                pawport_owner={"owner": "pawport"},
                recover_incomplete=True,
            )
        assert result is record
        kwargs = loader.load_plugin_from_path.call_args.kwargs
        assert kwargs["source_path"] == tmp_path
        assert kwargs["install_dir"] == tmp_path
        assert kwargs["force"] is force
        assert (kwargs["before_force_unload"] is not None) is force
        assert kwargs["pawport_owner"] == {"owner": "pawport"}
        assert kwargs["recover_incomplete"] is True
        loader.unload_plugin.assert_not_awaited()


# ---------------------------------------------------------------------------
# install_plugin_source / uninstall_plugin_source
# ---------------------------------------------------------------------------


class TestInstallPluginSource:
    async def test_local_path_is_resolved_and_loaded(self, tmp_path):
        log: list[str] = []
        loader = _loader_stub(log)
        app = _app(loader)
        with (
            patch(
                "qwenpaw.config.utils.get_plugins_dir",
                return_value=tmp_path,
            ),
        ):
            result = await install_plugin_source(
                f"  {tmp_path}  ",
                app=app,
                force=True,
                reload_agents=False,
            )
        assert result == "LOADED"
        kwargs = loader.load_plugin_from_path.call_args.kwargs
        assert kwargs["source_path"] == tmp_path
        assert kwargs["force"] is True
        assert kwargs["recover_incomplete"] is False

    async def test_missing_path_raises_file_not_found(self, tmp_path):
        loader = _loader_stub([])
        with pytest.raises(FileNotFoundError, match="Path not found"):
            await install_plugin_source(
                str(tmp_path / "ghost"),
                app=_app(loader),
            )
        loader.load_plugin_from_path.assert_not_called()

    async def test_http_url_downloads_then_extracts(self, tmp_path):
        log: list[str] = []
        loader = _loader_stub(log)
        urls: list[str] = []
        made: list[Path] = []

        async def _fake_download(url, dest):
            urls.append(url)
            dest.write_bytes(_zip_bytes({"plugin.json": '{"id": "p"}'}))

        real_mkdtemp = tempfile.mkdtemp
        seen_at_load: dict[str, Any] = {}

        def _mkdtemp(*args, **kwargs):
            path = Path(real_mkdtemp(*args, **kwargs))
            made.append(path)
            return str(path)

        async def _capture_load(**kwargs):
            source = kwargs["source_path"]
            seen_at_load["path"] = source
            seen_at_load["manifest"] = (source / "plugin.json").read_text(
                encoding="utf-8",
            )
            return "LOADED"

        loader.load_plugin_from_path = AsyncMock(side_effect=_capture_load)
        with (
            patch(
                "qwenpaw.config.utils.get_plugins_dir",
                return_value=tmp_path,
            ),
            patch(
                "qwenpaw.app.routers.plugins._async_download",
                new=_fake_download,
            ),
            patch(
                "qwenpaw.app.routers.plugins.tempfile.mkdtemp",
                side_effect=_mkdtemp,
            ),
        ):
            await install_plugin_source(
                "https://example.test/p.zip",
                app=_app(loader),
            )
        assert urls == ["https://example.test/p.zip"]
        # the ZIP was extracted into the temp dir and that dir handed to
        # the loader as the install source
        assert seen_at_load["path"] == made[0]
        assert seen_at_load["manifest"] == '{"id": "p"}'
        # the temporary download directory is removed afterwards
        assert not made[0].exists()

    async def test_temp_dir_is_removed_even_when_load_fails(
        self,
        tmp_path,
    ):
        loader = _loader_stub([])

        async def _fake_download(url, dest):
            dest.write_bytes(_zip_bytes({"plugin.json": '{"id": "p"}'}))

        holder: dict[str, Any] = {}

        async def _failing_load(**kwargs):
            holder["source_path"] = kwargs["source_path"]
            raise RuntimeError("load failed")

        loader.load_plugin_from_path = AsyncMock(side_effect=_failing_load)
        made: list[Path] = []
        real_mkdtemp = tempfile.mkdtemp

        def _mkdtemp(*args, **kwargs):
            path = Path(real_mkdtemp(*args, **kwargs))
            made.append(path)
            return str(path)

        with (
            patch(
                "qwenpaw.config.utils.get_plugins_dir",
                return_value=tmp_path,
            ),
            patch(
                "qwenpaw.app.routers.plugins._async_download",
                new=_fake_download,
            ),
            patch(
                "qwenpaw.app.routers.plugins.tempfile.mkdtemp",
                side_effect=_mkdtemp,
            ),
        ):
            with pytest.raises(RuntimeError, match="load failed"):
                await install_plugin_source(
                    "https://example.test/p.zip",
                    app=_app(loader),
                )
        assert holder["source_path"] == made[0]
        assert not made[0].exists()


class TestUninstallPluginSource:
    @pytest.mark.parametrize("reload_agents", [False, True])
    async def test_uninstall_uses_lifecycle_without_rebuilding_agents(
        self,
        reload_agents,
    ):
        from qwenpaw.plugins.lifecycle import UnloadMode, UnloadReport

        log = []
        loader = _loader_stub(log)
        report = UnloadReport(plugin_id="plug", mode=UnloadMode.UNINSTALL)

        async def unload(*args, **kwargs):
            log.append("unload_plugin")
            return report

        loader.unload_plugin.side_effect = unload
        app = _app(loader)
        await uninstall_plugin_source(
            "plug",
            app=app,
            reload_agents=reload_agents,
        )
        loader.unload_plugin.assert_awaited_once_with(
            "plug",
            delete_files=True,
            mode=UnloadMode.UNINSTALL,
        )
        assert log == [
            "lifecycle(plug):enter",
            "unload_plugin",
            "lifecycle(plug):exit",
        ]
        assert not app.state.multi_agent_manager.mock_calls

    async def test_unknown_plugin_error_comes_from_lifecycle(self):
        loader = _loader_stub([])
        loader.unload_plugin.side_effect = KeyError("Plugin 'ghost' not found")
        with pytest.raises(KeyError, match="ghost"):
            await uninstall_plugin_source("ghost", app=_app(loader))
        loader.unload_plugin.assert_awaited_once()

    @pytest.mark.parametrize(
        "quiescent,loaded",
        [(False, True), (False, False), (True, True)],
    )
    async def test_incomplete_uninstall_is_not_reported_as_success(
        self,
        quiescent,
        loaded,
    ):
        from qwenpaw.plugins.lifecycle import UnloadMode, UnloadReport

        loader = _loader_stub([], record=_record() if loaded else None)
        report = UnloadReport(
            plugin_id="plug",
            mode=UnloadMode.UNINSTALL,
            quiescent=quiescent,
            needs_restart=True,
        )
        loader.unload_plugin = AsyncMock(return_value=report)
        with pytest.raises(plugins_module.UnquiescentUnloadError) as caught:
            await uninstall_plugin_source("plug", app=_app(loader))
        assert caught.value.report is report
        assert caught.value.loaded is loaded


# ---------------------------------------------------------------------------
# install / uninstall / upload routes
# ---------------------------------------------------------------------------


class TestInstallPluginRoute:
    def test_success_payload(self, tmp_path):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins.install_plugin_source",
            new=AsyncMock(return_value=_record("plug")),
        ):
            response = _client(loader).post(
                "/api/plugins/install",
                json={"source": str(tmp_path), "force": True},
            )
        assert response.status_code == 200
        assert response.json() == {
            "id": "plug",
            "name": "plug display name",
            "version": "1.2.3",
            "description": "desc",
            "author": "auth",
            "loaded": True,
            "message": "Plugin 'plug display name' installed successfully.",
        }

    @pytest.mark.parametrize(
        "error,status",
        [
            (ValueError("dup"), 409),
            (FileNotFoundError("gone"), 400),
            (RuntimeError("not ready"), 400),
            (OSError("disk"), 500),
        ],
    )
    def test_error_mapping(self, error, status):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins.install_plugin_source",
            new=AsyncMock(side_effect=error),
        ):
            response = _client(loader).post(
                "/api/plugins/install",
                json={"source": "/tmp/x"},
            )
        assert response.status_code == status
        assert str(error) in response.json()["detail"]

    def test_http_exception_is_reraised_unchanged(self):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins.install_plugin_source",
            new=AsyncMock(
                side_effect=HTTPException(status_code=418, detail="teapot"),
            ),
        ):
            response = _client(loader).post(
                "/api/plugins/install",
                json={"source": "/tmp/x"},
            )
        assert response.status_code == 418
        assert response.json()["detail"] == "teapot"

    async def test_source_helper_is_called_with_request_app(self):
        app = _app(_loader_stub([]))
        seen: dict[str, Any] = {}

        async def _fake(source, *, app, **kwargs):
            seen["source"] = source
            seen["app"] = app
            seen.update(kwargs)
            return _record("plug")

        with patch(
            "qwenpaw.app.routers.plugins.install_plugin_source",
            new=_fake,
        ):
            await install_plugin(
                plugins_module.InstallPluginRequest(
                    source="/tmp/x",
                    force=True,
                ),
                _request(app),
            )
        assert seen["source"] == "/tmp/x"
        assert seen["force"] is True
        assert seen["app"] is app
        assert sorted(seen) == ["app", "force", "source"]


class TestSetPluginEnabledRoute:
    @staticmethod
    def _disable_loader(
        monkeypatch,
        tmp_path,
        *,
        enabled=True,
        loaded=True,
        quiescent=True,
    ):
        from qwenpaw.plugins.lifecycle import UnloadMode, UnloadReport

        plugin_dir = tmp_path / "plug"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(
            "qwenpaw.config.utils.get_plugins_dir",
            lambda: tmp_path,
        )
        settings = {"enabled": enabled}
        monkeypatch.setattr(
            plugins_module,
            "_plugin_config_row",
            lambda _id: settings,
        )
        loader = _loader_stub([], record=_record() if loaded else None)

        async def disable(plugin_id, requested_enabled):
            assert plugin_id == "plug"
            assert requested_enabled is False
            if quiescent:
                settings["enabled"] = False
                loader.get_loaded_plugin.return_value = None
            return UnloadReport(
                plugin_id=plugin_id,
                mode=UnloadMode.UNLOAD,
                clean=quiescent,
                quiescent=quiescent,
                needs_restart=not quiescent,
                errors=[] if quiescent else ["connection still alive"],
            )

        loader.lifecycle.set_enabled = AsyncMock(side_effect=disable)
        return loader, settings

    def test_disable_and_repeat_report_persisted_disabled_state(
        self,
        monkeypatch,
        tmp_path,
    ):
        loader, settings = self._disable_loader(
            monkeypatch,
            tmp_path,
        )
        client = _client(loader)
        for _ in range(2):
            response = client.post(
                "/api/plugins/plug/enabled",
                json={"enabled": False},
            )
            assert response.status_code == 200
            assert settings["enabled"] is False
            payload = response.json()
            assert payload["enabled"] is False
            assert payload["loaded"] is False
            assert payload["clean"] and payload["quiescent"]
        assert loader.lifecycle.set_enabled.await_count == 2

    @pytest.mark.parametrize(
        "persisted_enabled,loaded",
        [(True, False), (False, True)],
    )
    def test_failed_disable_reports_settings_and_loaded_state_separately(
        self,
        monkeypatch,
        tmp_path,
        persisted_enabled,
        loaded,
    ):
        loader, settings = self._disable_loader(
            monkeypatch,
            tmp_path,
            enabled=persisted_enabled,
            loaded=loaded,
            quiescent=False,
        )
        response = _client(loader).post(
            "/api/plugins/plug/enabled",
            json={"enabled": False},
        )
        assert response.status_code == 409
        assert settings["enabled"] is persisted_enabled
        detail = response.json()["detail"]
        assert detail["enabled"] is persisted_enabled
        assert detail["loaded"] is loaded
        assert not detail["quiescent"]
        assert detail["needs_restart"]
        loader.lifecycle.set_enabled.assert_awaited_once_with("plug", False)


class TestUninstallPluginRoute:
    @pytest.mark.parametrize("quiescent,loaded", [(False, True), (True, True)])
    def test_incomplete_lifecycle_result_returns_structured_409(
        self,
        quiescent,
        loaded,
    ):
        from qwenpaw.plugins.lifecycle import UnloadMode, UnloadReport

        loader = _loader_stub([], record=_record() if loaded else None)
        loader.unload_plugin = AsyncMock(
            return_value=UnloadReport(
                plugin_id="plug",
                mode=UnloadMode.UNINSTALL,
                clean=False,
                quiescent=quiescent,
                needs_restart=True,
                errors=["connection still alive"],
            ),
        )
        response = _client(loader).delete("/api/plugins/plug")
        assert response.status_code == 409
        assert response.json()["detail"] == {
            "id": "plug",
            "loaded": loaded,
            "clean": False,
            "quiescent": quiescent,
            "needs_restart": True,
            "errors": ["connection still alive"],
            "message": "Plugin 'plug' did not go quiescent.",
        }

    def test_memory_backend_in_use_returns_409_and_keeps_plugin_loaded(self):
        loader = _loader_stub([], record=_record())
        loader.unload_plugin.side_effect = RuntimeError(
            "memory backend is in use",
        )
        response = _client(loader).delete("/api/plugins/plug")
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["loaded"] is True
        assert detail["quiescent"] is False
        assert detail["needs_restart"] is True
        assert detail["errors"] == ["memory backend is in use"]

    def test_success_payload(self):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins.uninstall_plugin_source",
            new=AsyncMock(return_value=None),
        ):
            response = _client(loader).delete("/api/plugins/plug")
        assert response.status_code == 200
        assert response.json() == {
            "id": "plug",
            "message": "Plugin 'plug' uninstalled successfully.",
        }

    def test_unknown_plugin_is_404(self):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins.uninstall_plugin_source",
            new=AsyncMock(
                side_effect=KeyError("Plugin 'ghost' is not loaded."),
            ),
        ):
            response = _client(loader).delete("/api/plugins/ghost")
        assert response.status_code == 404
        assert "ghost" in response.json()["detail"]

    def test_unexpected_error_is_500(self, caplog):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins.uninstall_plugin_source",
            new=AsyncMock(side_effect=RuntimeError("disk on fire")),
        ):
            response = _client(loader).delete("/api/plugins/plug")
        assert response.status_code == 500
        assert "disk on fire" in response.json()["detail"]


class TestUploadPluginRoute:
    def test_success_payload(self):
        loader = _loader_stub([])
        payload = _zip_bytes({"plugin.json": '{"id": "p"}'})
        with patch(
            "qwenpaw.app.routers.plugins."
            "_load_plugin_with_optional_force_reinstall",
            new=AsyncMock(return_value=_record("plug")),
        ):
            response = _client(loader).post(
                "/api/plugins/upload?force=true",
                files={"file": ("plug.zip", payload, "application/zip")},
            )
        assert response.status_code == 200
        assert response.json()["id"] == "plug"
        assert response.json()["loaded"] is True

    def test_non_zip_filename_is_400(self):
        loader = _loader_stub([])
        response = _client(loader).post(
            "/api/plugins/upload",
            files={"file": ("plug.tar", b"nope")},
        )
        assert response.status_code == 400
        assert ".zip" in response.json()["detail"]

    async def test_empty_filename_is_rejected(self):
        """Probed at the handler: the multipart layer answers 422 for an
        empty filename before ``upload_plugin`` ever runs."""
        loader = _loader_stub([])
        upload = MagicMock()
        upload.filename = ""
        with pytest.raises(HTTPException) as exc_info:
            await upload_plugin(_request(_app(loader)), upload)
        assert exc_info.value.status_code == 400
        assert ".zip" in exc_info.value.detail

    def test_zip_slip_is_409(self):
        loader = _loader_stub([])
        payload = _zip_bytes({"../escape.txt": "evil"})
        with patch(
            "qwenpaw.app.routers.plugins._extract_plugin_zip_bytes",
            side_effect=ValueError("Zip Slip detected"),
        ):
            response = _client(loader).post(
                "/api/plugins/upload",
                files={"file": ("plug.zip", payload)},
            )
        assert response.status_code == 409
        assert "Zip Slip" in response.json()["detail"]

    def test_missing_manifest_is_400(self):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins._extract_plugin_zip_bytes",
            side_effect=FileNotFoundError("no plugin.json"),
        ):
            response = _client(loader).post(
                "/api/plugins/upload",
                files={"file": ("plug.zip", _zip_bytes({"a.txt": "A"}))},
            )
        assert response.status_code == 400

    def test_unexpected_error_is_500(self):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins._extract_plugin_zip_bytes",
            side_effect=OSError("disk full"),
        ):
            response = _client(loader).post(
                "/api/plugins/upload",
                files={"file": ("plug.zip", _zip_bytes({"a.txt": "A"}))},
            )
        assert response.status_code == 500
        assert "disk full" in response.json()["detail"]

    def test_http_exception_is_reraised_unchanged(self):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins._extract_plugin_zip_bytes",
            side_effect=HTTPException(status_code=418, detail="teapot"),
        ):
            response = _client(loader).post(
                "/api/plugins/upload",
                files={"file": ("plug.zip", _zip_bytes({"a.txt": "A"}))},
            )
        assert response.status_code == 418


# ---------------------------------------------------------------------------
# search_market_plugins
# ---------------------------------------------------------------------------


class _FakeHttpxResponse:
    def __init__(self, payload: Any = None, status_error: Exception = None):
        self._payload = payload
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error

    def json(self) -> Any:
        return self._payload


class _FakeAsyncClient:
    last: dict[str, Any] = {}

    def __init__(self, timeout=None):
        _FakeAsyncClient.last["timeout"] = timeout
        self._response = _FakeAsyncClient.response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def get(self, url, params=None):
        _FakeAsyncClient.last["url"] = url
        _FakeAsyncClient.last["params"] = params
        return self._response


class TestSearchMarketPlugins:
    def setup_method(self):
        _FakeAsyncClient.last = {}
        _FakeAsyncClient.response = _FakeHttpxResponse(payload={"ok": True})

    async def test_defaults_only_send_paging(self):
        with patch("httpx.AsyncClient", _FakeAsyncClient):
            result = await search_market_plugins()
        assert result == {"ok": True}
        assert _FakeAsyncClient.last["timeout"] == 15
        assert _FakeAsyncClient.last["url"] == (
            "https://platform.agentscope.io/openapi/v1/plugins"
        )
        assert _FakeAsyncClient.last["params"] == {
            "page_number": 1,
            "page_size": 20,
        }

    async def test_all_filters_are_forwarded(self):
        with patch("httpx.AsyncClient", _FakeAsyncClient):
            await search_market_plugins(
                page_number=3,
                page_size=5,
                search="git",
                category="dev",
                sort_by="stars",
                is_featured=True,
                is_trending=False,
            )
        assert _FakeAsyncClient.last["params"] == {
            "page_number": 3,
            "page_size": 5,
            "search": "git",
            "category": "dev",
            "sort_by": "stars",
            "is_featured": True,
            "is_trending": False,
        }

    async def test_empty_strings_are_not_forwarded(self):
        with patch("httpx.AsyncClient", _FakeAsyncClient):
            await search_market_plugins(search="", category="", sort_by="")
        assert _FakeAsyncClient.last["params"] == {
            "page_number": 1,
            "page_size": 20,
        }

    async def test_upstream_error_status_is_502(self, caplog):
        _FakeAsyncClient.response = _FakeHttpxResponse(
            status_error=RuntimeError("500 Server Error"),
        )
        with patch("httpx.AsyncClient", _FakeAsyncClient):
            with pytest.raises(HTTPException) as exc_info:
                await search_market_plugins()
        assert exc_info.value.status_code == 502
        assert "500 Server Error" in exc_info.value.detail
        assert "Plugin market search failed" in caplog.text

    async def test_transport_failure_is_502(self):
        class _Boom:
            def __init__(self, timeout=None):
                pass

            async def __aenter__(self):
                raise OSError("connection refused")

            async def __aexit__(self, *exc):
                return None

        with patch("httpx.AsyncClient", _Boom):
            with pytest.raises(HTTPException) as exc_info:
                await search_market_plugins()
        assert exc_info.value.status_code == 502
        assert "connection refused" in exc_info.value.detail


# ---------------------------------------------------------------------------
# remaining branches
# ---------------------------------------------------------------------------


class TestResidualBranches:
    async def test_catalog_route_proxies_the_fetcher(self):
        with patch(
            "qwenpaw.plugins.download_catalog.fetch_plugin_catalog_async",
            new=AsyncMock(return_value={"plugins": [{"id": "a"}]}),
        ) as fetch:
            assert await plugins_module.get_plugin_catalog() == {
                "plugins": [{"id": "a"}],
            }
        fetch.assert_awaited_once_with()

    async def test_ui_file_uses_the_loaded_record_source_path(
        self,
        tmp_path,
    ):
        (tmp_path / "ui").mkdir()
        asset = tmp_path / "ui" / "app.js"
        asset.write_text("console.log(1)", encoding="utf-8")
        loader = MagicMock()
        loader.get_loaded_plugin.return_value = _record("plug")
        loader.get_loaded_plugin.return_value.source_path = tmp_path
        response = await plugins_module.serve_plugin_ui_file(
            "plug",
            "ui/app.js",
            _request(_app(loader)),
        )
        assert Path(response.path) == asset
        assert response.media_type == "application/javascript"
        assert response.headers["Cache-Control"] == "no-cache"

    async def test_ui_file_serves_unknown_extensions(
        self,
        tmp_path,
    ):
        asset = tmp_path / "data.unknownext"
        asset.write_bytes(b"\x00\x01")
        loader = MagicMock()
        record = _record("plug")
        record.source_path = tmp_path
        loader.get_loaded_plugin.return_value = record
        response = await plugins_module.serve_plugin_ui_file(
            "plug",
            "data.unknownext",
            _request(_app(loader)),
        )
        assert Path(response.path) == asset
        assert response.headers["Cache-Control"] == "no-cache"
