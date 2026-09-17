"""HTTP model catalog and administration use separate capabilities."""

from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_member_cannot_import_metadata(monkeypatch):
    from qwenpaw.app.routers.model_governance import router
    from qwenpaw.access.dependencies import get_actor
    from tests.unit.models.test_governance import actor, Manager

    app = FastAPI()
    app.state.provider_manager = Manager()
    app.include_router(router)
    app.dependency_overrides[get_actor] = actor
    with TestClient(app) as client:
        assert client.post("/model-governance/import/preview").status_code == 403


def test_console_rejects_legacy_and_forged_model_authority():
    from qwenpaw.app.routers.console import _extract_session_and_payload

    with pytest.raises(ValueError, match="model_slot_override_not_supported"):
        _extract_session_and_payload(
            {"model_slot_override": {"provider_id": "p", "model": "m"}}
        )
    with pytest.raises(ValueError, match="authority_unavailable"):
        _extract_session_and_payload(
            {"request_context": {"published_model_id": "fake"}}
        )


@pytest.mark.asyncio
async def test_enforced_management_list_rejects_member(monkeypatch):
    from qwenpaw.app.routers.providers import _require_model_management_route
    from fastapi import HTTPException
    from tests.unit.models.test_governance import actor

    class Repo:
        async def get_status(self):
            return {"enforced": True}

    monkeypatch.setattr(
        "qwenpaw.models.runtime.get_model_service",
        lambda _: SimpleNamespace(repository=Repo()),
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.providers.is_multi_user_enabled", lambda: True
    )
    request = SimpleNamespace(
        url=SimpleNamespace(path="/models"),
        method="GET",
        state=SimpleNamespace(actor=actor()),
        app=SimpleNamespace(state=SimpleNamespace(provider_manager=None)),
    )
    with pytest.raises(HTTPException) as error:
        await _require_model_management_route(request)
    assert error.value.status_code == 403


def test_chat_model_null_is_explicit_clear(monkeypatch):
    from qwenpaw.app.routers import model_governance as module
    from qwenpaw.access.dependencies import get_actor
    from tests.unit.models.test_governance import actor

    selections = []

    async def owned(*args):
        return SimpleNamespace(agent_id="a"), SimpleNamespace(id="c")

    async def persist(*args):
        selections.append(args[-1])

    async def resolve(*args):
        return {"active_llm": {"provider_id": "p", "model": "default"}}

    monkeypatch.setattr(module, "owned_context", owned)
    monkeypatch.setattr(module, "persist_selection", persist)
    monkeypatch.setattr(module, "resolve_selection", resolve)
    monkeypatch.setattr(module, "load_agent_config", lambda _: None)
    monkeypatch.setattr(module, "service", lambda _: SimpleNamespace(manager=None))
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[get_actor] = actor
    with TestClient(app) as client:
        response = client.put(
            "/chats/c/model",
            content="null",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 200, response.text
        assert selections == [None]
        assert client.put("/chats/c/model").status_code == 422


def test_catalog_database_outage_is_explicit_unavailable(monkeypatch):
    from sqlalchemy.exc import OperationalError
    from qwenpaw.app.routers import model_governance as module
    from qwenpaw.access.dependencies import get_actor
    from tests.unit.models.test_governance import actor

    class Broken:
        async def list_catalog(self, *args):
            raise OperationalError("SELECT 1", {}, Exception("synthetic-secret"))

    monkeypatch.setattr(module, "service", lambda _: Broken())
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[get_actor] = actor
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/model-catalog")
        assert response.status_code == 503
        assert response.json() == {"detail": "model_authority_unavailable"}


def test_downloaded_model_reference_blocks_local_deletion(monkeypatch):
    from qwenpaw.app.routers.local_models import router
    app=FastAPI()
    app.include_router(router)
    app.state.local_model_manager=SimpleNamespace(get_llamacpp_server_status=lambda:{"running":False},remove_downloaded_model=lambda _:None)
    app.state.provider_manager=SimpleNamespace(get_active_model=lambda:SimpleNamespace(provider_id="qwenpaw-local",model="local-one"))
    monkeypatch.setattr("qwenpaw.app.routers.local_models.is_multi_user_enabled",lambda:False)
    with TestClient(app) as client:
        assert client.delete("/local-models/models/local-one").status_code==409
