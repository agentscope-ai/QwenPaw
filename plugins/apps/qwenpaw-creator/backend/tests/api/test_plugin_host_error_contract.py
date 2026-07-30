# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,unused-argument
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.dependencies import CreatorErrorRoute
from domain.errors import CreatorError


WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
PLUGIN_ENTRYPOINT = WORKSPACE_ROOT / "qwenpaw-creator" / "backend" / "main.py"
PLUGIN_MANIFEST = WORKSPACE_ROOT / "qwenpaw-creator" / "plugin.json"
QWENPAW_SOURCE = WORKSPACE_ROOT.parents[1] / "src"


def _load_plugin_entrypoint(monkeypatch):
    # Other Creator API tests may attempt optional host imports first.  Make
    # this host-contract test deterministic by discarding a partially loaded
    # or foreign qwenpaw module before loading the checked-out host source.
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
    assert Path(module.os.environ["CREATOR_BINARY_DIR"]) == (
        data_root / "runtime-tools" / "bin"
    )
    assert data_root.is_dir()
    assert model_config_path.parent.is_dir()


def test_plugin_preserves_explicit_absolute_runtime_paths(
    tmp_path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "external-creator"
    model_config_path = data_root / "private" / "models.json"
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(data_root))
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(model_config_path))
    module = _load_plugin_entrypoint(monkeypatch)

    assert module.configure_creator_runtime_environment(
        working_dir=tmp_path / "ignored-qwenpaw-home",
    ) == (data_root, model_config_path)


def test_plugin_rejects_relative_runtime_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CREATOR_DATA_ROOT", "relative/creator-runtime")
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", "")
    module = _load_plugin_entrypoint(monkeypatch)

    with pytest.raises(module.CreatorDataRootError, match="absolute path"):
        module.configure_creator_runtime_environment(working_dir=tmp_path)


def test_plugin_rejects_model_config_outside_runtime_root(
    tmp_path,
    monkeypatch,
) -> None:
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


def test_plugin_manifest_declares_every_creator_config_tool(
    monkeypatch,
) -> None:
    manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    tools = {item["name"]: item for item in manifest["meta"]["tools"]}
    assert set(tools) == {
        "creator_text_model",
        "creator_vlm_model",
        "creator_web_grounding",
        "creator_asr_model",
        "creator_image_model",
        "creator_video_model",
        "creator_media_oss",
    }
    oss_fields = {
        item["name"]: item
        for item in tools["creator_media_oss"]["config_fields"]
    }
    assert {
        "policy_api_key",
        "access_key_id",
        "access_key_secret",
        "endpoint",
        "bucket",
        "public_base_url",
    } == set(oss_fields)
    assert oss_fields["access_key_secret"]["type"] == "password"
    grounding_fields = {
        item["name"]: item
        for item in tools["creator_web_grounding"]["config_fields"]
    }
    assert set(grounding_fields) == {
        "enabled",
        "tavily_api_key",
        "native_search_enabled",
        "search_reuse_llm",
        "search_api_key",
        "search_model",
        "search_base_url",
        "validation_source",
        "reuse_llm",
        "api_key",
        "model",
        "base_url",
    }
    assert grounding_fields["tavily_api_key"]["type"] == "password"

    module = _load_plugin_entrypoint(monkeypatch)
    assert not hasattr(module, "_ensure_config_tools_registered")


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
        assert response.json() == {
            "code": "NOT_FOUND",
            "message": "Project 不存在",
            "retryable": False,
            "details": {},
        }
    finally:
        PluginRegistry._instance = previous_registry
