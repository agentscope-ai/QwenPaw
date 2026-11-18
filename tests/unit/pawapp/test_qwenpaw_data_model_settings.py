# -*- coding: utf-8 -*-
"""References stay scoped; only execution resolves provider credentials."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx
from fastapi import FastAPI, HTTPException, Request

path = (
    Path(__file__).resolve().parents[3]
    / "plugins/apps/qwenpaw-data/backend/model_settings.py"
)
spec = importlib.util.spec_from_file_location(
    "data_model_settings_under_test",
    path,
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

scope_spec = importlib.util.spec_from_file_location(
    "data_standalone_scope",
    path.with_name("standalone.py"),
)
assert scope_spec is not None and scope_spec.loader is not None
scope_module = importlib.util.module_from_spec(scope_spec)
sys.modules[scope_spec.name] = scope_module
scope_spec.loader.exec_module(scope_module)
TaskScope = scope_module.DataScope


@pytest.fixture(name="configured")
def configured_service(tmp_path, monkeypatch):
    provider = SimpleNamespace(
        id="provider",
        name="Provider",
        api_key="private-test-key",
        base_url="https://models.example/v1",
        enabled=True,
        chat_model="OpenAIChatModel",
        models=[SimpleNamespace(id="model-a", name="Model A")],
        extra_models=[],
        discovered_models=[],
        get_model_info=lambda value: (
            object() if value in {"model-a", "model-b"} else None
        ),
    )
    manager = SimpleNamespace(
        get_provider=lambda _: provider,
        list_provider_info=AsyncMock(return_value=[provider]),
    )
    service = module.ModelSettingsService(tmp_path)
    monkeypatch.setattr(service, "_manager", lambda: manager)
    monkeypatch.setattr(
        service,
        "_workspace_choice",
        lambda scope: module.ModelChoice(
            source="host",
            provider_id="provider",
            model_id="model-a" if scope.workspace_id == "one" else "model-b",
        ),
    )
    return service, provider


def scope(workspace="one", principal="alice"):
    return TaskScope(
        app_id="qwenpaw-data",
        principal_id=principal,
        workspace_id=workspace,
    )


@pytest.mark.asyncio
async def test_references_and_metadata_never_copy_keys(configured, tmp_path):
    service, provider = configured
    response = await service.save(
        scope(),
        module.ModelSettings(
            lightweight=module.ModelChoice(
                source="host",
                provider_id="provider",
                model_id="model-b",
            ),
        ),
    )
    assert "private-test-key" not in json.dumps(response)
    assert "private-test-key" not in next(tmp_path.glob("*.json")).read_text()
    runtime = await service.runtime(scope())
    assert runtime["analysis"]["model_id"] == "model-a"
    assert runtime["lightweight"]["model_id"] == "model-b"
    assert runtime["databridge"]["model_id"] == "model-a"
    provider.api_key = "rotated-key"
    assert (await service.runtime(scope()))["analysis"][
        "api_key"
    ] == "rotated-key"
    assert runtime["analysis"]["api_key"] == "private-test-key"


@pytest.mark.asyncio
async def test_scope_isolation_and_stale_save(configured):
    service, _ = configured
    await service.save(
        scope(),
        module.ModelSettings(analysis=module.ModelChoice(source="local")),
    )
    assert service.load(scope()).analysis.source == "local"
    assert service.load(scope("two")).analysis.source == "inherit"
    assert service.load(scope(principal="bob")).analysis.source == "inherit"
    assert (await service.runtime(scope("two")))["analysis"][
        "model_id"
    ] == "model-b"
    with pytest.raises(HTTPException) as error:
        await service.save(scope(), module.ModelSettings())
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_unsupported_provider_fails_explicitly(configured):
    service, provider = configured
    provider.chat_model = "AnthropicChatModel"
    response = await service.describe(scope())
    assert not response["effective"]["analysis"]["configured"]
    with pytest.raises(HTTPException) as error:
        await service.runtime(scope())
    assert error.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "unsupported", "credentials"])
async def test_model_configuration_errors_are_actionable_http_conflicts(
    configured,
    monkeypatch,
    failure,
):
    service, provider = configured
    if failure == "missing":
        monkeypatch.setattr(service, "_workspace_choice", lambda _: None)
        expected = "Choose a default model in main chat settings."
    elif failure == "unsupported":
        provider.chat_model = "AnthropicChatModel"
        expected = (
            "Data requires an OpenAI-compatible or DashScope chat model."
        )
    else:
        provider.api_key = ""
        expected = "Configure this provider in main chat settings."
    gateway = SimpleNamespace(
        json=AsyncMock(
            return_value={
                "console_protocol": 1,
                "scoped_sessions": True,
                "runtime_model_bindings": True,
                "dataset_context": True,
            },
        ),
    )
    app = FastAPI()

    @app.post("/console/chat")
    async def chat(request: Request):
        return await scope_module.dispatch_console_chat(
            request,
            gateway,
            service.runtime,
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post("/console/chat", json={"text": "analyze"})
    assert response.status_code == 409
    assert response.json() == {"detail": expected}
    assert "private-test-key" not in response.text
    # Admission checks compatibility, but never submits an invalid analysis.
    assert gateway.json.call_count == 1
    assert gateway.json.call_args.args[0] == "GET"


@pytest.mark.asyncio
async def test_main_chat_default_remains_visible_with_data_override(
    configured,
):
    service, _ = configured
    initial = await service.describe(scope())
    assert initial["settings"]["analysis"]["source"] == "inherit"
    assert initial["effective"]["analysis"]["model_id"] == "model-a"
    response = await service.save(
        scope(),
        module.ModelSettings(
            analysis=module.ModelChoice(
                source="host",
                provider_id="provider",
                model_id="model-b",
            ),
        ),
    )
    assert response["workspace_default"]["model_id"] == "model-a"
    assert response["workspace_default"]["configured"] is True
    assert response["effective"]["analysis"]["model_id"] == "model-b"
    assert "private-test-key" not in json.dumps(response)


def test_workspace_selection_matches_main_chat_precedence(
    tmp_path,
    monkeypatch,
):
    # Exercise the internal resolver directly to isolate model precedence.
    # pylint: disable=protected-access
    from qwenpaw.config import config

    service = module.ModelSettingsService(tmp_path)
    global_slot = SimpleNamespace(provider_id="global", model="global-model")
    workspace = SimpleNamespace(
        active_model=SimpleNamespace(
            provider_id="workspace",
            model="workspace-model",
        ),
    )
    monkeypatch.setattr(config, "load_agent_config", lambda _: workspace)
    monkeypatch.setattr(
        service,
        "_manager",
        lambda: SimpleNamespace(get_active_model=lambda: global_slot),
    )
    assert service._workspace_choice(scope()).model_id == "workspace-model"
    workspace.active_model = None
    assert service._workspace_choice(scope()).model_id == "global-model"
