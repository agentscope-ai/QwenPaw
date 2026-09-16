# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Data settings reach only the intended child on save/start/restart."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.pawapp import ManagedService

MAIN_FILE = (
    Path(__file__).resolve().parents[3]
    / "plugins/apps/qwenpaw-data/backend/main.py"
)

# Capture the actual child environment before answering health probes. No
# model/Neo4j/container service is contacted in this lifecycle regression.
_SERVER = """
import json, os, socket, sys
from pathlib import Path
Path(sys.argv[3]).write_text(json.dumps(dict(os.environ)))
server = socket.socket()
server.bind((sys.argv[1], int(sys.argv[2])))
server.listen()
while True:
    connection, _ = server.accept()
    connection.recv(65536)
    connection.sendall(b"HTTP/1.1 200 OK\\r\\nContent-Length: 2\\r\\n\\r\\nok")
    connection.close()
"""


@pytest.fixture
def backend(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "qwenpaw_data_environment_under_test",
        MAIN_FILE,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config_module = sys.modules[module.load_config.__module__]
    for name, value in {
        "APP_DATA_DIR": tmp_path,
        "CONFIG_JSON_PATH": tmp_path / "config.json",
        "ENV_FILE_PATH": tmp_path / ".env",
        "MODELS_JSON_PATH": tmp_path / "models.json",
    }.items():
        monkeypatch.setattr(config_module, name, value)
        if hasattr(module, name):
            monkeypatch.setattr(module, name, value)
    monkeypatch.setattr(module, "ENGINE_HOME", tmp_path / "engine")
    monkeypatch.setattr(module, "_push_model_config", AsyncMock())
    monkeypatch.setattr(module, "_host_llm_payload", lambda: {})
    return module


def _child_service(spec, tmp_path):
    return ManagedService(
        replace(
            spec,
            command=(
                sys.executable,
                "-c",
                _SERVER,
                "{host}",
                "{port}",
                str(tmp_path / f"{spec.name}.json"),
            ),
            health_path="/",
            cwd=tmp_path,
            mode_env=None,
            external_url_env=None,
        ),
    )


@pytest.mark.asyncio
async def test_data_save_restart_and_clear_leave_host_environment_unchanged(
    backend,
    tmp_path,
    monkeypatch,
) -> None:
    for name in (
        "OPENAI_API_KEY",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
        "MODEL_CONFIG_PATH",
        "QWENPAW_DATA_ENV_FILE",
        "QWENPAW_DATA_MODEL_API_KEY",
        "QWENPAW_DATA_CM_BASE_URL",
        "QWENPAW_DATA_API_TOKEN",
        "UNRELATED_APP_SECRET",
    ):
        monkeypatch.setenv(name, "host-owned")
    monkeypatch.setenv("NEO4J_DATABASE_DEMO", "pipeline-demo")
    before = dict(os.environ)
    context = _child_service(backend._context_service.spec, tmp_path)
    engine_spec = replace(
        backend._engine_service.spec,
        env={
            **backend._engine_service.spec.env,
            "QWENPAW_DATA_HOME": str(tmp_path / "engine"),
        },
    )
    engine = _child_service(engine_spec, tmp_path)
    monkeypatch.setattr(backend, "_context_service", context)
    payload = backend.DataAppConfig().to_dict()
    payload["neo4j"]["password"] = "graph-${SECRET}-{port}"
    payload["neo4j"]["database"] = "app-graph"
    payload["llm"].update(model="app-model", api_key="app-model-key")
    await backend.set_config(payload)
    try:
        await context.start()
        await engine.start()
        context_env = json.loads((tmp_path / "context.json").read_text())
        engine_env = json.loads((tmp_path / "engine.json").read_text())
        assert context_env["NEO4J_PASSWORD"] == "graph-${SECRET}-{port}"
        assert context_env["OPENAI_API_KEY"] == "app-model-key"
        assert context_env["NEO4J_DATABASE_DEMO"] == "pipeline-demo"
        assert context_env["QWENPAW_DATA_ENV_FILE"] == str(tmp_path / ".env")
        assert context_env["QWENPAW_DATA_API_TOKEN"] == backend._context_token
        assert "QWENPAW_DATA_MODEL_API_KEY" not in context_env
        assert "QWENPAW_DATA_CM_BASE_URL" not in context_env
        assert engine_env["QWENPAW_DATA_API_TOKEN"] == backend._engine_token
        assert engine_env["QWENPAW_DATA_MODEL_API_KEY"] == "app-model-key"
        assert engine_env["QWENPAW_DATA_CM_BASE_URL"] == context.base_url
        assert (
            engine_env["QWENPAW_DATA_CLIENT_API_TOKEN"]
            == backend._context_token
        )
        assert "NEO4J_PASSWORD" not in engine_env
        assert "OPENAI_API_KEY" not in engine_env
        assert "UNRELATED_APP_SECRET" not in context_env
        assert "UNRELATED_APP_SECRET" not in engine_env

        # Saved empty values must not recover from either the old child or
        # conflicting global env values when both services are restarted.
        await backend.set_config(backend.DataAppConfig().to_dict())
        await context.restart()
        await engine.restart()
        context_env = json.loads((tmp_path / "context.json").read_text())
        engine_env = json.loads((tmp_path / "engine.json").read_text())
        assert "NEO4J_PASSWORD" not in context_env
        assert "NEO4J_DATABASE" not in context_env
        assert "OPENAI_API_KEY" not in context_env
        assert "QWENPAW_DATA_MODEL_API_KEY" not in engine_env
        assert engine_env["QWENPAW_DATA_CM_BASE_URL"] == context.base_url
        models = json.loads((tmp_path / "models.json").read_text())
        assert models["llm"]["api_key"] == ""
        assert models["embedding"]["api_key"] == ""
        # Show only changed names if this fails, never developer credentials.
        assert not {
            key
            for key in before.keys() | os.environ.keys()
            if before.get(key) != os.environ.get(key)
        }
    finally:
        await engine.stop()
        await context.stop()


@pytest.mark.asyncio
async def test_reuse_model_save_and_engine_restart_do_not_write_host_env(
    backend,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "host-owned")
    monkeypatch.setenv("QWENPAW_DATA_MODEL_API_KEY", "other-app-owned")
    monkeypatch.setattr(
        backend,
        "_resolve_host_active",
        lambda: (
            SimpleNamespace(
                base_url="https://provider.invalid/v1",
                api_key="reused-key",
                name="Fixture",
            ),
            "reused-model",
        ),
    )
    backend.save_config(backend.DataAppConfig())
    await backend.reuse_host_model({"target": "llm", "reuse": True})
    await backend._engine_before_start()
    assert backend._engine_env()["QWENPAW_DATA_MODEL_API_KEY"] == "reused-key"
    assert os.environ["OPENAI_API_KEY"] == "host-owned"
    assert os.environ["QWENPAW_DATA_MODEL_API_KEY"] == "other-app-owned"


@pytest.mark.asyncio
async def test_first_start_imports_persisted_defaults_without_host_mutation(
    backend,
    monkeypatch,
) -> None:
    import qwenpaw.envs

    monkeypatch.setenv("OPENAI_API_KEY", "host-owned")
    monkeypatch.setattr(
        qwenpaw.envs,
        "load_envs",
        lambda: {"OPENAI_API_KEY": "persisted-default"},
    )
    await backend._initialize_config()
    assert backend.load_config().llm.api_key == "persisted-default"
    config = backend.load_config()
    config.llm.api_key = ""
    backend.save_config(config)
    await backend._initialize_config()
    assert backend.load_config().llm.api_key == ""
    assert os.environ["OPENAI_API_KEY"] == "host-owned"
