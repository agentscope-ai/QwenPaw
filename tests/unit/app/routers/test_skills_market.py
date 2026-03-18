# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from copaw.app.routers.skills import (
    MarketError,
    MarketplaceItem,
    SkillsMarketPayload,
    SkillsMarketConfig,
    ValidateMarketRequest,
    _generate_market_index_from_directory,
    _extract_market_items,
    _payload_to_market_config,
    router,
    validate_market,
)
from copaw.config.config import SkillMarketSpec


@pytest.fixture
def skills_api_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_payload_to_market_config_normalizes_owner_repo_url() -> None:
    payload = SkillsMarketPayload(
        version=1,
        cache={"ttl_sec": 600},
        install={"overwrite_default": False},
        markets=[
            SkillMarketSpec(
                id="official",
                name="Official",
                url="futuremeng/editor-skills",
                branch="main",
                path="index.json",
                enabled=True,
                order=1,
            ),
        ],
    )

    config = _payload_to_market_config(payload)

    assert config.markets[0].url == "https://github.com/futuremeng/editor-skills.git"
    assert config.cache.ttl_sec == 600


def test_payload_to_market_config_rejects_unsafe_index_path() -> None:
    payload = SkillsMarketPayload(
        version=1,
        cache={"ttl_sec": 600},
        install={"overwrite_default": False},
        markets=[
            SkillMarketSpec(
                id="unsafe",
                name="Unsafe",
                url="https://github.com/example/skills.git",
                branch="",
                path="../index.json",
                enabled=True,
                order=1,
            ),
        ],
    )

    with pytest.raises(HTTPException) as exc:
        _payload_to_market_config(payload)

    assert exc.value.status_code == 400
    assert "MARKET_INDEX_INVALID" in str(exc.value.detail)


def test_extract_market_items_builds_install_url_with_branch_and_path() -> None:
    market_payload = SkillsMarketPayload(
        version=1,
        cache={"ttl_sec": 600},
        install={"overwrite_default": False},
        markets=[
            SkillMarketSpec(
                id="official",
                name="Official",
                url="https://github.com/example/skills.git",
                branch="main",
                path="index.json",
                enabled=True,
                order=1,
            ),
        ],
    )
    market = _payload_to_market_config(market_payload).markets[0]

    items, errors = _extract_market_items(
        market,
        {
            "skills": [
                {
                    "skill_id": "python-dev",
                    "name": "Python Dev",
                    "description": {"zh": "Python 开发技能"},
                    "version": "0.1.0",
                    "source": {
                        "type": "git",
                        "url": "https://github.com/example/skills.git",
                        "branch": "dev",
                        "path": "skills/python-dev",
                    },
                    "tags": ["python", "dev"],
                },
            ],
        },
    )

    assert errors == []
    assert len(items) == 1
    assert items[0].install_url == (
        "https://github.com/example/skills/tree/dev/skills/python-dev"
    )
    assert items[0].description == "Python 开发技能"


def test_extract_market_items_returns_error_for_invalid_skills_field() -> None:
    market_payload = SkillsMarketPayload(
        version=1,
        cache={"ttl_sec": 600},
        install={"overwrite_default": False},
        markets=[
            SkillMarketSpec(
                id="official",
                name="Official",
                url="https://github.com/example/skills.git",
                branch="main",
                path="index.json",
                enabled=True,
                order=1,
            ),
        ],
    )
    market = _payload_to_market_config(market_payload).markets[0]

    items, errors = _extract_market_items(market, {"skills": {}})

    assert items == []
    assert len(errors) == 1
    assert isinstance(errors[0], MarketError)
    assert errors[0].code == "MARKET_INDEX_INVALID"


def test_payload_to_market_config_parses_github_tree_url() -> None:
    payload = SkillsMarketPayload(
        version=1,
        cache={"ttl_sec": 600},
        install={"overwrite_default": False},
        markets=[
            SkillMarketSpec(
                id="openclaw",
                name="OpenClaw Skills",
                url="https://github.com/openclaw/openclaw/tree/main/skills",
                branch="",
                path="index.json",
                enabled=True,
                order=1,
            ),
        ],
    )

    config = _payload_to_market_config(payload)

    assert config.markets[0].url == "https://github.com/openclaw/openclaw.git"
    assert config.markets[0].branch == "main"
    assert config.markets[0].path == "skills"


def test_payload_to_market_config_keeps_single_git_suffix() -> None:
    payload = SkillsMarketPayload(
        version=1,
        cache={"ttl_sec": 600},
        install={"overwrite_default": False},
        markets=[
            SkillMarketSpec(
                id="openclaw",
                name="OpenClaw Skills",
                url="https://github.com/openclaw/openclaw.git",
                branch="main",
                path="skills",
                enabled=True,
                order=1,
            ),
        ],
    )

    config = _payload_to_market_config(payload)

    assert config.markets[0].url == "https://github.com/openclaw/openclaw.git"


def test_generate_market_index_from_directory_scans_skill_folders(
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    skills_dir = repo_dir / "skills"
    skill_dir = skills_dir / "weather"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: Weather Assistant\n"
        "description: 查询天气\n"
        "tags:\n"
        "  - weather\n"
        "  - tools\n"
        "---\n\n"
        "skill body\n",
        encoding="utf-8",
    )
    market = SkillMarketSpec(
        id="openclaw",
        name="OpenClaw Skills",
        url="https://github.com/openclaw/openclaw.git",
        branch="main",
        path="skills",
        enabled=True,
        order=1,
    )

    index_doc = _generate_market_index_from_directory(
        market,
        repo_dir,
        skills_dir,
        "main",
    )

    assert len(index_doc["skills"]) == 1
    assert index_doc["skills"][0]["skill_id"] == "weather"
    assert index_doc["skills"][0]["name"] == "Weather Assistant"
    assert index_doc["skills"][0]["source"]["path"] == "skills/weather"


def test_validate_market_maps_index_value_error_to_http_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = ValidateMarketRequest(
        id="openclaw",
        name="OpenClaw Skills",
        url="https://github.com/openclaw/openclaw.git",
        branch="main",
        path="skills",
        enabled=True,
        order=1,
    )

    def _ok_ls_remote(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=["git", "ls-remote"],
            returncode=0,
            stdout="",
            stderr="",
        )

    def _raise_index_error(*args, **kwargs):
        raise ValueError("MARKET_INDEX_INVALID: missing skills")

    monkeypatch.setattr("copaw.app.routers.skills._run_git_command", _ok_ls_remote)
    monkeypatch.setattr("copaw.app.routers.skills._load_market_index", _raise_index_error)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(validate_market(payload))

    assert exc.value.status_code == 400
    assert "MARKET_INDEX_INVALID" in str(exc.value.detail)


def test_validate_market_maps_market_runtime_error_to_http_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = ValidateMarketRequest(
        id="openclaw",
        name="OpenClaw Skills",
        url="https://github.com/openclaw/openclaw.git",
        branch="main",
        path="skills",
        enabled=True,
        order=1,
    )

    def _ok_ls_remote(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=["git", "ls-remote"],
            returncode=0,
            stdout="",
            stderr="",
        )

    def _raise_unreachable(*args, **kwargs):
        raise RuntimeError("MARKET_UNREACHABLE: clone failed")

    monkeypatch.setattr("copaw.app.routers.skills._run_git_command", _ok_ls_remote)
    monkeypatch.setattr("copaw.app.routers.skills._load_market_index", _raise_unreachable)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(validate_market(payload))

    assert exc.value.status_code == 502
    assert "MARKET_UNREACHABLE" in str(exc.value.detail)


def test_validate_market_endpoint_returns_normalized_contract(
    monkeypatch: pytest.MonkeyPatch,
    skills_api_client: TestClient,
) -> None:
    def _ok_ls_remote(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=["git", "ls-remote"],
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr("copaw.app.routers.skills._run_git_command", _ok_ls_remote)
    monkeypatch.setattr(
        "copaw.app.routers.skills._load_market_index",
        lambda *_args, **_kwargs: ({"skills": []}, []),
    )

    response = skills_api_client.post(
        "/skills/markets/validate",
        json={
            "id": "community",
            "name": "Community Skills",
            "url": "futuremeng/editor-skills",
            "branch": "",
            "path": "index.json",
            "enabled": True,
            "order": 1,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert isinstance(data["warnings"], list)
    assert data["normalized"]["url"] == "https://github.com/futuremeng/editor-skills.git"


def test_marketplace_endpoint_returns_expected_shape(
    monkeypatch: pytest.MonkeyPatch,
    skills_api_client: TestClient,
) -> None:
    monkeypatch.setattr(
        "copaw.app.routers.skills.load_config",
        lambda: SimpleNamespace(skills_market=SkillsMarketConfig()),
    )
    monkeypatch.setattr(
        "copaw.app.routers.skills._aggregate_marketplace",
        lambda *_args, **_kwargs: (
            [
                MarketplaceItem(
                    market_id="community",
                    skill_id="weather",
                    name="Weather",
                    description="Weather helper",
                    version="0.1.0",
                    source_url="https://github.com/futuremeng/editor-skills",
                    install_url="https://github.com/futuremeng/editor-skills/tree/main/skills/weather",
                    tags=["tools"],
                ),
            ],
            [
                MarketError(
                    market_id="community",
                    code="MARKET_UNREACHABLE",
                    message="timeout",
                    retryable=True,
                ),
            ],
            {
                "refreshed_at": 123,
                "cache_hit": False,
                "enabled_market_count": 1,
                "success_market_count": 1,
            },
        ),
    )

    response = skills_api_client.get("/skills/marketplace?refresh=true")

    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"items", "market_errors", "meta"}
    assert data["items"][0]["skill_id"] == "weather"
    assert data["market_errors"][0]["code"] == "MARKET_UNREACHABLE"
    assert data["meta"]["enabled_market_count"] == 1


def test_marketplace_install_endpoint_returns_not_found_when_item_missing(
    monkeypatch: pytest.MonkeyPatch,
    skills_api_client: TestClient,
) -> None:
    monkeypatch.setattr(
        "copaw.app.routers.skills.load_config",
        lambda: SimpleNamespace(skills_market=SkillsMarketConfig()),
    )
    monkeypatch.setattr(
        "copaw.app.routers.skills._aggregate_marketplace",
        lambda *_args, **_kwargs: ([], [], {}),
    )

    response = skills_api_client.post(
        "/skills/marketplace/install",
        json={
            "market_id": "community",
            "skill_id": "not-found",
            "enable": True,
            "overwrite": False,
        },
    )

    assert response.status_code == 404
    assert "MARKET_ITEM_NOT_FOUND" in response.json()["detail"]
