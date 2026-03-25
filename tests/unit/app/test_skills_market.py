# -*- coding: utf-8 -*-
"""Unit tests for skills marketplace backend helpers."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from copaw.app.routers.skills import (
    SkillsMarketPayload,
    _extract_market_items,
    _generate_market_index_from_directory,
    _payload_to_market_config,
)
from copaw.config.config import SkillMarketSpec


def test_payload_to_market_config_normalizes_owner_repo_url() -> None:
    payload = SkillsMarketPayload(
        version=1,
        cache={"ttl_sec": 600},
        install={"overwrite_default": False},
        markets=[
            SkillMarketSpec(
                id="community",
                name="Community",
                url="futuremeng/editor-skills",
                branch="main",
                path="index.json",
                enabled=True,
                order=1,
            ),
        ],
    )

    cfg = _payload_to_market_config(payload)

    assert cfg.markets[0].url == "https://github.com/futuremeng/editor-skills.git"
    assert cfg.cache.ttl_sec == 600


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


def test_generate_market_index_from_directory_scans_skill_folders(
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    skills_dir = repo_dir / "skills"
    weather_dir = skills_dir / "weather"
    weather_dir.mkdir(parents=True)
    (weather_dir / "SKILL.md").write_text("# Weather", encoding="utf-8")

    market = SkillMarketSpec(
        id="community",
        name="Community",
        url="https://github.com/example/skills.git",
        branch="main",
        path="skills",
        enabled=True,
        order=1,
    )

    doc, warnings = _generate_market_index_from_directory(
        market,
        skills_dir,
        effective_branch="main",
    )

    assert warnings == []
    assert len(doc["skills"]) == 1
    assert doc["skills"][0]["skill_id"] == "weather"
    assert doc["skills"][0]["source"]["path"] == "skills/weather"


def test_extract_market_items_builds_install_url_with_branch_and_path() -> None:
    market = SkillMarketSpec(
        id="official",
        name="Official",
        url="https://github.com/example/skills.git",
        branch="main",
        path="index.json",
        enabled=True,
        order=1,
    )

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
    assert (
        items[0].install_url
        == "https://github.com/example/skills/tree/dev/skills/python-dev"
    )
    assert items[0].description == "Python 开发技能"
