# -*- coding: utf-8 -*-

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copaw.app.routers import agents as agents_router_module
from copaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    AgentsConfig,
    AgentsSquareConfig,
    AgentsSquareSourceSpec,
    Config,
)


@pytest.fixture
def agents_square_api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    square_dir = tmp_path / "agents_square"
    square_dir.mkdir(parents=True, exist_ok=True)

    config_payload = {
        "version": 1,
        "cache": {"ttl_sec": 600},
        "install": {
            "overwrite_default": False,
            "preserve_workspace_files": True,
        },
        "sources": [
            {
                "id": "agency-agents",
                "name": "agency-agents",
                "provider": "agency_markdown_repo",
                "url": "https://github.com/msitarzewski/agency-agents.git",
                "branch": "main",
                "path": ".",
                "enabled": True,
                "order": 1,
                "trust": "official",
                "license_hint": "MIT",
                "pinned": True,
            }
        ],
    }

    default_payload = {
        "version": 1,
        "cache": {"ttl_sec": 600},
        "install": {
            "overwrite_default": False,
            "preserve_workspace_files": True,
        },
        "sources": [
            {
                "id": "agency-agents-zh",
                "name": "agency-agents-zh",
                "provider": "agency_markdown_repo",
                "url": "https://github.com/jnMetaCode/agency-agents-zh",
                "branch": "main",
                "path": ".",
                "enabled": True,
                "order": 1,
                "trust": "community",
                "license_hint": "",
                "pinned": True,
            },
            {
                "id": "agency-agents",
                "name": "agency-agents",
                "provider": "agency_markdown_repo",
                "url": "https://github.com/msitarzewski/agency-agents.git",
                "branch": "main",
                "path": ".",
                "enabled": False,
                "order": 2,
                "trust": "official",
                "license_hint": "MIT",
                "pinned": True,
            },
            {
                "id": "agent-teams",
                "name": "agent-teams",
                "provider": "agency_markdown_repo",
                "url": "https://github.com/dsclca12/agent-teams",
                "branch": "main",
                "path": ".",
                "enabled": False,
                "order": 3,
                "trust": "community",
                "license_hint": "",
                "pinned": True,
            },
        ],
    }

    (square_dir / "config.json").write_text(
        json.dumps(config_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    (square_dir / "default.json").write_text(
        json.dumps(default_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    state = {
        "config": Config(
            agents=AgentsConfig(
                active_agent="default",
                profiles={
                    "default": AgentProfileRef(
                        id="default",
                        workspace_dir=str(tmp_path / "workspaces" / "default"),
                    )
                },
            ),
            agents_square=AgentsSquareConfig(
                sources=[
                    AgentsSquareSourceSpec(
                        id="agency-agents",
                        name="agency-agents",
                        provider="agency_markdown_repo",
                        url="https://github.com/msitarzewski/agency-agents.git",
                        branch="main",
                        path=".",
                        enabled=True,
                        order=1,
                        trust="official",
                        license_hint="MIT",
                        pinned=True,
                    )
                ]
            ),
        ),
        "agent_configs": {},
    }

    def fake_load_config():
        return state["config"]

    def fake_save_config(new_config):
        state["config"] = new_config

    def fake_save_agent_config(agent_id: str, cfg: AgentProfileConfig):
        state["agent_configs"][agent_id] = cfg

    def fake_load_agent_config(agent_id: str):
        cfg = state["agent_configs"].get(agent_id)
        if cfg is None:
            raise ValueError(f"Agent '{agent_id}' not found")
        return cfg

    def fake_init_workspace(workspace_dir: Path, _cfg: AgentProfileConfig):
        (workspace_dir / "sessions").mkdir(parents=True, exist_ok=True)
        (workspace_dir / "memory").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(agents_router_module, "load_config", fake_load_config)
    monkeypatch.setattr(agents_router_module, "save_config", fake_save_config)
    monkeypatch.setattr(agents_router_module, "save_agent_config", fake_save_agent_config)
    monkeypatch.setattr(agents_router_module, "load_agent_config", fake_load_agent_config)
    monkeypatch.setattr(agents_router_module, "_initialize_agent_workspace", fake_init_workspace)
    monkeypatch.setattr(agents_router_module, "WORKING_DIR", str(tmp_path))
    monkeypatch.setattr(
        agents_router_module,
        "_AGENTS_SQUARE_DEFAULT_DIR",
        square_dir,
    )
    monkeypatch.setattr(
        agents_router_module,
        "_AGENTS_SQUARE_CONFIG_PATH",
        square_dir / "config.json",
    )
    monkeypatch.setattr(
        agents_router_module,
        "_AGENTS_SQUARE_DEFAULT_PATH",
        square_dir / "default.json",
    )

    app = FastAPI()
    app.include_router(agents_router_module.router)
    return TestClient(app)


def test_square_items_endpoint_returns_expected_shape(
    agents_square_api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        agents_router_module,
        "_aggregate_square_items",
        lambda *_args, **_kwargs: (
            [
                agents_router_module.AgentSquareItem(
                    source_id="agency-agents",
                    agent_id="frontend-developer",
                    name="Frontend Developer",
                    description="UI expert",
                    version="",
                    license="MIT",
                    source_url="https://github.com/msitarzewski/agency-agents/blob/main/engineering/frontend.md",
                    install_url="https://github.com/msitarzewski/agency-agents/blob/main/engineering/frontend.md",
                    tags=["frontend", "react"],
                    extra={"category": "engineering"},
                )
            ],
            [
                agents_router_module.SourceError(
                    source_id="community",
                    code="SOURCE_UNREACHABLE",
                    message="timeout",
                    retryable=True,
                )
            ],
            {
                "generated_at": 123.0,
                "cache_ttl_sec": 600,
                "source_count": 1,
                "item_count": 1,
                "cache_hit": False,
                "duration_ms": 4,
            },
            {},
        ),
    )

    response = agents_square_api_client.get("/agents/square/items?refresh=true")

    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"items", "source_errors", "meta"}
    assert data["items"][0]["agent_id"] == "frontend-developer"
    assert data["source_errors"][0]["code"] == "SOURCE_UNREACHABLE"
    assert data["meta"]["item_count"] == 1


def test_agents_square_config_defaults_include_expected_sources() -> None:
    config = AgentsSquareConfig()

    assert [source.id for source in config.sources] == [
        "agency-agents-zh",
        "agency-agents",
        "agent-teams",
    ]
    assert [source.enabled for source in config.sources] == [True, False, False]
    assert [source.order for source in config.sources] == [1, 2, 3]
    assert [source.url for source in config.sources] == [
        "https://github.com/jnMetaCode/agency-agents-zh",
        "https://github.com/msitarzewski/agency-agents.git",
        "https://github.com/dsclca12/agent-teams",
    ]


def test_square_source_defaults_endpoint_returns_bundled_defaults(
    agents_square_api_client: TestClient,
) -> None:
    response = agents_square_api_client.get("/agents/square/sources/defaults")

    assert response.status_code == 200
    payload = response.json()
    assert [source["id"] for source in payload["sources"]] == [
        "agency-agents-zh",
        "agency-agents",
        "agent-teams",
    ]
    assert [source["enabled"] for source in payload["sources"]] == [
        True,
        False,
        False,
    ]


def test_square_source_reset_endpoint_returns_bundled_defaults(
    agents_square_api_client: TestClient,
) -> None:
    response = agents_square_api_client.post("/agents/square/sources/reset")

    assert response.status_code == 200
    payload = response.json()
    assert [source["id"] for source in payload["sources"]] == [
        "agency-agents-zh",
        "agency-agents",
        "agent-teams",
    ]
    assert [source["enabled"] for source in payload["sources"]] == [
        True,
        False,
        False,
    ]


def test_square_import_creates_agent_and_writes_import_metadata(
    agents_square_api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        agents_router_module,
        "_aggregate_square_items",
        lambda *_args, **_kwargs: (
            [
                agents_router_module.AgentSquareItem(
                    source_id="agency-agents",
                    agent_id="frontend-developer",
                    name="Frontend Developer",
                    description="UI expert",
                    version="",
                    license="MIT",
                    source_url="https://github.com/msitarzewski/agency-agents/blob/main/engineering/frontend.md",
                    install_url="https://github.com/msitarzewski/agency-agents/blob/main/engineering/frontend.md",
                    tags=[],
                    extra={},
                )
            ],
            [],
            {
                "generated_at": 123.0,
                "cache_ttl_sec": 600,
                "source_count": 1,
                "item_count": 1,
                "cache_hit": False,
                "duration_ms": 1,
            },
            {
                "agency-agents/frontend-developer": {
                    "name": "Frontend Developer",
                    "description": "UI expert",
                    "content": "# Frontend Developer\n\nDo frontend work.",
                    "source_url": "https://github.com/msitarzewski/agency-agents/blob/main/engineering/frontend.md",
                    "license": "MIT",
                    "original_agent_id": "frontend-developer",
                }
            },
        ),
    )

    response = agents_square_api_client.post(
        "/agents/square/import",
        json={
            "source_id": "agency-agents",
            "agent_id": "frontend-developer",
            "overwrite": False,
            "enable": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["imported"] is True
    assert payload["name"] == "Frontend Developer"

    workspace_dir = Path(payload["workspace_dir"])
    assert workspace_dir.exists()
    assert (workspace_dir / "AGENTS.md").exists()
    assert (workspace_dir / "imported_from.json").exists()

    imported_from = json.loads((workspace_dir / "imported_from.json").read_text(encoding="utf-8"))
    assert imported_from["source_id"] == "agency-agents"
    assert imported_from["original_agent_id"] == "frontend-developer"


def test_square_import_conflict_then_overwrite(
    agents_square_api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    existing_workspace = tmp_path / "workspaces" / "ag1234"
    existing_workspace.mkdir(parents=True, exist_ok=True)
    (existing_workspace / "imported_from.json").write_text(
        json.dumps(
            {
                "source_id": "agency-agents",
                "original_agent_id": "frontend-developer",
                "source_url": "x",
                "license": "MIT",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Inject existing profile + config
    cfg = agents_router_module.load_config()
    cfg.agents.profiles["ag1234"] = AgentProfileRef(
        id="ag1234",
        workspace_dir=str(existing_workspace),
    )
    agents_router_module.save_config(cfg)
    agents_router_module.save_agent_config(
        "ag1234",
        AgentProfileConfig(
            id="ag1234",
            name="Old Name",
            description="Old",
            workspace_dir=str(existing_workspace),
            language="en",
        ),
    )

    monkeypatch.setattr(
        agents_router_module,
        "_aggregate_square_items",
        lambda *_args, **_kwargs: (
            [
                agents_router_module.AgentSquareItem(
                    source_id="agency-agents",
                    agent_id="frontend-developer",
                    name="Frontend Developer",
                    description="Updated desc",
                    version="",
                    license="MIT",
                    source_url="https://example.com/src",
                    install_url="https://example.com/src",
                    tags=[],
                    extra={},
                )
            ],
            [],
            {
                "generated_at": 123.0,
                "cache_ttl_sec": 600,
                "source_count": 1,
                "item_count": 1,
                "cache_hit": False,
                "duration_ms": 1,
            },
            {
                "agency-agents/frontend-developer": {
                    "name": "Frontend Developer",
                    "description": "Updated desc",
                    "content": "# Updated\n\nNew content.",
                    "source_url": "https://example.com/src",
                    "license": "MIT",
                    "original_agent_id": "frontend-developer",
                }
            },
        ),
    )

    conflict = agents_square_api_client.post(
        "/agents/square/import",
        json={
            "source_id": "agency-agents",
            "agent_id": "frontend-developer",
            "overwrite": False,
        },
    )
    assert conflict.status_code == 409
    assert "AGENT_NAME_CONFLICT" in conflict.json()["detail"]

    overwrite = agents_square_api_client.post(
        "/agents/square/import",
        json={
            "source_id": "agency-agents",
            "agent_id": "frontend-developer",
            "overwrite": True,
        },
    )
    assert overwrite.status_code == 200
    data = overwrite.json()
    assert data["id"] == "ag1234"
    assert (existing_workspace / "AGENTS.md").read_text(encoding="utf-8").startswith(
        "# Updated"
    )


def test_square_sources_get_and_validate_normalization(
    agents_square_api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        agents_router_module.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "CP",
            (),
            {"returncode": 0, "stderr": "", "stdout": ""},
        )(),
    )

    get_resp = agents_square_api_client.get("/agents/square/sources")
    assert get_resp.status_code == 200
    payload = get_resp.json()
    assert "sources" in payload
    assert payload["sources"][0]["id"] == "agency-agents"

    validate_resp = agents_square_api_client.post(
        "/agents/square/sources/validate",
        json={
            "id": "futuremeng-editor-skills",
            "name": "Editor Skills",
            "type": "git",
            "provider": "index_json_repo",
            "url": "futuremeng/editor-skills",
            "branch": "",
            "path": "index.json",
            "enabled": True,
            "order": 2,
            "trust": "community",
            "license_hint": "MIT",
            "pinned": False,
        },
    )

    assert validate_resp.status_code == 200
    data = validate_resp.json()
    assert data["ok"] is True
    assert (
        data["normalized"]["url"]
        == "https://github.com/futuremeng/editor-skills.git"
    )


def test_square_sources_put_rejects_deleting_pinned_source(
    agents_square_api_client: TestClient,
):
    response = agents_square_api_client.put(
        "/agents/square/sources",
        json={
            "version": 1,
            "cache": {"ttl_sec": 600},
            "install": {
                "overwrite_default": False,
                "preserve_workspace_files": True,
            },
            "sources": [],
        },
    )

    assert response.status_code == 400
    assert "SOURCE_PINNED_CANNOT_DELETE" in response.json()["detail"]


def test_square_import_returns_422_when_content_missing(
    agents_square_api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        agents_router_module,
        "_aggregate_square_items",
        lambda *_args, **_kwargs: (
            [
                agents_router_module.AgentSquareItem(
                    source_id="agency-agents",
                    agent_id="empty-agent",
                    name="Empty Agent",
                    description="",
                    version="",
                    license="MIT",
                    source_url="https://example.com/src",
                    install_url="https://example.com/src",
                    tags=[],
                    extra={},
                )
            ],
            [],
            {
                "generated_at": 1.0,
                "cache_ttl_sec": 600,
                "source_count": 1,
                "item_count": 1,
                "cache_hit": False,
                "duration_ms": 1,
            },
            {
                "agency-agents/empty-agent": {
                    "name": "Empty Agent",
                    "description": "",
                    "content": "",
                    "source_url": "https://example.com/src",
                    "license": "MIT",
                    "original_agent_id": "empty-agent",
                }
            },
        ),
    )

    response = agents_square_api_client.post(
        "/agents/square/import",
        json={
            "source_id": "agency-agents",
            "agent_id": "empty-agent",
            "overwrite": False,
        },
    )
    assert response.status_code == 422
    assert "AGENT_TEMPLATE_INVALID" in response.json()["detail"]


def test_square_import_uses_preferred_name(
    agents_square_api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        agents_router_module,
        "_aggregate_square_items",
        lambda *_args, **_kwargs: (
            [
                agents_router_module.AgentSquareItem(
                    source_id="agency-agents",
                    agent_id="frontend-developer",
                    name="Frontend Developer",
                    description="UI expert",
                    version="",
                    license="MIT",
                    source_url="https://example.com/src",
                    install_url="https://example.com/src",
                    tags=[],
                    extra={},
                )
            ],
            [],
            {
                "generated_at": 1.0,
                "cache_ttl_sec": 600,
                "source_count": 1,
                "item_count": 1,
                "cache_hit": False,
                "duration_ms": 1,
            },
            {
                "agency-agents/frontend-developer": {
                    "name": "Frontend Developer",
                    "description": "UI expert",
                    "content": "# Frontend Developer\n\nDo frontend work.",
                    "source_url": "https://example.com/src",
                    "license": "MIT",
                    "original_agent_id": "frontend-developer",
                }
            },
        ),
    )

    response = agents_square_api_client.post(
        "/agents/square/import",
        json={
            "source_id": "agency-agents",
            "agent_id": "frontend-developer",
            "preferred_name": "My Frontend Lead",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "My Frontend Lead"
