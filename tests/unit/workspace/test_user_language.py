# -*- coding: utf-8 -*-
"""Unit tests for GET/PUT /config/user-language endpoints."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copaw.app.routers.config import router
from copaw.config.config import Config, UserLanguageConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SUPPORTED_LANGUAGES = ["en", "zh", "ja", "ru"]


def _make_client(tmp_config: Path) -> TestClient:
    """Return a TestClient wired to a temporary config file."""
    app = FastAPI()
    app.include_router(router)  # router already has prefix="/config"
    return TestClient(app)


def _write_config(tmp_dir: Path, language: str = "en") -> Path:
    """Write a minimal config.json to *tmp_dir* and return its path."""
    config_path = tmp_dir / "config.json"
    config_path.write_text(
        json.dumps({"user_language": language}),
        encoding="utf-8",
    )
    return config_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_config_dir():
    """Provide a temporary directory that acts as the config home."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture()
def client(tmp_config_dir):
    """TestClient with load_config / save_config patched to use tmp dir."""
    config_path = _write_config(tmp_config_dir, language="en")

    def _load(path=None):
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return Config(**data)

    def _save(cfg, path=None):
        config_path.write_text(cfg.model_dump_json(), encoding="utf-8")

    with (
        patch("copaw.app.routers.config.load_config", side_effect=_load),
        patch("copaw.app.routers.config.save_config", side_effect=_save),
    ):
        app = FastAPI()
        app.include_router(router)  # router already has prefix="/config"
        yield TestClient(app), config_path


# ---------------------------------------------------------------------------
# GET /config/user-language
# ---------------------------------------------------------------------------


class TestGetUserLanguage:
    def test_returns_default_language(self, client):
        tc, _ = client
        resp = tc.get("/config/user-language")
        assert resp.status_code == 200
        assert resp.json() == {"language": "en"}

    @pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
    def test_returns_stored_language(self, tmp_config_dir, lang):
        """GET returns whatever language is saved in config."""
        config_path = _write_config(tmp_config_dir, language=lang)

        def _load(path=None):
            data = json.loads(config_path.read_text(encoding="utf-8"))
            return Config(**data)

        def _save(cfg, path=None):
            config_path.write_text(cfg.model_dump_json(), encoding="utf-8")

        with (
            patch("copaw.app.routers.config.load_config", side_effect=_load),
            patch("copaw.app.routers.config.save_config", side_effect=_save),
        ):
            app = FastAPI()
            app.include_router(router)  # router already has prefix="/config"
            tc = TestClient(app)
            resp = tc.get("/config/user-language")
            assert resp.status_code == 200
            assert resp.json()["language"] == lang


# ---------------------------------------------------------------------------
# PUT /config/user-language
# ---------------------------------------------------------------------------


class TestPutUserLanguage:
    @pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
    def test_set_each_supported_language(self, client, lang):
        """PUT persists and returns the chosen language for all 4 locales."""
        tc, config_path = client
        resp = tc.put(
            "/config/user-language",
            json={"language": lang},
        )
        assert resp.status_code == 200
        assert resp.json() == {"language": lang}

        # Verify persisted value
        saved = Config(**json.loads(config_path.read_text(encoding="utf-8")))
        assert saved.user_language == lang

    def test_set_english(self, client):
        tc, config_path = client
        resp = tc.put("/config/user-language", json={"language": "en"})
        assert resp.status_code == 200
        assert resp.json()["language"] == "en"
        saved = Config(**json.loads(config_path.read_text(encoding="utf-8")))
        assert saved.user_language == "en"

    def test_set_chinese(self, client):
        tc, config_path = client
        resp = tc.put("/config/user-language", json={"language": "zh"})
        assert resp.status_code == 200
        assert resp.json()["language"] == "zh"
        saved = Config(**json.loads(config_path.read_text(encoding="utf-8")))
        assert saved.user_language == "zh"

    def test_set_japanese(self, client):
        tc, config_path = client
        resp = tc.put("/config/user-language", json={"language": "ja"})
        assert resp.status_code == 200
        assert resp.json()["language"] == "ja"
        saved = Config(**json.loads(config_path.read_text(encoding="utf-8")))
        assert saved.user_language == "ja"

    def test_set_russian(self, client):
        tc, config_path = client
        resp = tc.put("/config/user-language", json={"language": "ru"})
        assert resp.status_code == 200
        assert resp.json()["language"] == "ru"
        saved = Config(**json.loads(config_path.read_text(encoding="utf-8")))
        assert saved.user_language == "ru"

    def test_strips_whitespace(self, client):
        """Language values with surrounding whitespace are stripped."""
        tc, config_path = client
        resp = tc.put("/config/user-language", json={"language": "  zh  "})
        assert resp.status_code == 200
        assert resp.json()["language"] == "zh"
        saved = Config(**json.loads(config_path.read_text(encoding="utf-8")))
        assert saved.user_language == "zh"

    def test_empty_language_returns_400(self, client):
        """Empty language string is rejected with HTTP 400."""
        tc, _ = client
        resp = tc.put("/config/user-language", json={"language": ""})
        assert resp.status_code == 400

    def test_whitespace_only_returns_400(self, client):
        """Whitespace-only language string is rejected with HTTP 400."""
        tc, _ = client
        resp = tc.put("/config/user-language", json={"language": "   "})
        assert resp.status_code == 400

    def test_missing_language_field_returns_422(self, client):
        """Missing required field returns HTTP 422 Unprocessable Entity."""
        tc, _ = client
        resp = tc.put("/config/user-language", json={})
        assert resp.status_code == 422

    def test_get_after_put_roundtrip(self, client):
        """PUT then GET returns the updated language."""
        tc, _ = client
        for lang in SUPPORTED_LANGUAGES:
            tc.put("/config/user-language", json={"language": lang})
            resp = tc.get("/config/user-language")
            assert resp.status_code == 200
            assert resp.json()["language"] == lang


# ---------------------------------------------------------------------------
# UserLanguageConfig model
# ---------------------------------------------------------------------------


class TestUserLanguageConfig:
    def test_valid_language_field(self):
        cfg = UserLanguageConfig(language="en")
        assert cfg.language == "en"

    @pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
    def test_all_supported_languages(self, lang):
        cfg = UserLanguageConfig(language=lang)
        assert cfg.language == lang

    def test_missing_field_raises(self):
        with pytest.raises(Exception):
            UserLanguageConfig()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Config model default
# ---------------------------------------------------------------------------


class TestConfigUserLanguageDefault:
    def test_default_is_en(self):
        """Config.user_language defaults to 'en'."""
        cfg = Config()
        assert cfg.user_language == "en"

    @pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
    def test_can_set_any_supported_language(self, lang):
        cfg = Config(user_language=lang)
        assert cfg.user_language == lang
