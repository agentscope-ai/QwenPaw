# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,unused-argument
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.dependencies import CreatorErrorRoute
from domain.errors import CreatorError

WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
PLUGIN_ENTRYPOINT = WORKSPACE_ROOT / "qwenpaw-creator" / "backend" / "main.py"
QWENPAW_SOURCE = WORKSPACE_ROOT.parents[1] / "src"


def _load_plugin_entrypoint(monkeypatch):
    # Discard a partially loaded or foreign qwenpaw module before loading
    # the checked-out host source so this contract test is deterministic.
    for module_name in tuple(sys.modules):
        if module_name == "qwenpaw" or module_name.startswith("qwenpaw."):
            monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.syspath_prepend(str(QWENPAW_SOURCE))
    spec = importlib.util.spec_from_file_location(
        "qwenpaw_creator_plugin_host_contract",
        PLUGIN_ENTRYPOINT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_defaults_runtime_paths_to_qwenpaw_working_dir(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_DATA_ROOT", "")
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", "")
    monkeypatch.setenv("CREATOR_BINARY_DIR", "")
    module = _load_plugin_entrypoint(monkeypatch)

    working_dir = tmp_path / "qwenpaw-home"
    (
        data_root,
        model_config_path,
    ) = module.configure_creator_runtime_environment(
        working_dir=working_dir,
    )

    assert data_root == working_dir / "creator-runtime"
    assert model_config_path == data_root / "config" / "model_config.json"
    assert Path(module.os.environ["CREATOR_DATA_ROOT"]) == data_root
    assert (
        Path(module.os.environ["CREATOR_MODEL_CONFIG_PATH"])
        == model_config_path
    )
    assert (
        Path(module.os.environ["CREATOR_BINARY_DIR"])
        == data_root / "runtime-tools" / "bin"
    )
    assert data_root.is_dir()
    assert model_config_path.parent.is_dir()


def test_plugin_rejects_unsafe_runtime_path_configuration(
    tmp_path,
    monkeypatch,
) -> None:
    # A model config path escaping the runtime root fails closed.
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path / "creator-runtime"))
    monkeypatch.setenv(
        "CREATOR_MODEL_CONFIG_PATH",
        str(tmp_path / "outside" / "model_config.json"),
    )
    module = _load_plugin_entrypoint(monkeypatch)
    with pytest.raises(
        module.CreatorDataRootError,
        match="inside CREATOR_DATA_ROOT",
    ):
        module.configure_creator_runtime_environment(working_dir=tmp_path)


def test_real_qwenpaw_host_mount_keeps_creator_errors_local_and_structured(
    api_runtime_root,
    monkeypatch,
) -> None:
    module = _load_plugin_entrypoint(monkeypatch)
    from qwenpaw.plugins.api import PluginApi
    from qwenpaw.plugins.registry import PluginRegistry

    previous_registry = PluginRegistry._instance
    PluginRegistry._instance = None
    try:
        host = FastAPI()
        registry = PluginRegistry()
        registry.set_plugin_http_app(host)
        plugin_api = PluginApi(
            "qwenpaw-creator",
            config={},
            manifest={"id": "qwenpaw-creator"},
        )
        plugin_api.set_registry(registry)
        module.app.register(plugin_api)

        assert CreatorError not in host.exception_handlers
        registrations = registry.get_http_router_registrations()
        assert len(registrations) == 1
        assert registrations[0].prefix == "/qwenpaw-creator"
        assert registrations[0].routes
        # FastAPI 0.135+ keeps include_router contributions as optimized
        # _IncludedRouter nodes instead of flattening top-level APIRoutes. The
        # plugin's own route class plus the real request below are the stable
        # contract; inspecting the host's private flattened shape is not.
        assert module.creator_router.route_class is CreatorErrorRoute

        async def scenario():
            transport = ASGITransport(app=host, raise_app_exceptions=False)
            async with AsyncClient(
                transport=transport,
                base_url="http://plugin-host.test",
            ) as client:
                return await client.get(
                    "/api/qwenpaw-creator/projects/project-does-not-exist/project",
                )

        response = asyncio.run(scenario())
        assert response.status_code == 404
        body = response.json()
        assert {
            key: body[key]
            for key in ("code", "message", "retryable", "details")
        } == {
            "code": "NOT_FOUND",
            "message": "Project 不存在",
            "retryable": False,
            "details": {},
        }
        assert body["errorId"] == response.headers["X-Creator-Error-ID"]
        assert body["traceId"] == response.headers["X-Creator-Trace-ID"]
        assert body["requestId"] == response.headers["X-Request-ID"]
    finally:
        PluginRegistry._instance = previous_registry
