# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
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


def _write_config(tmp_dir: Path, language: str = "en") -> Path:
    """Write a minimal config.json to *tmp_dir* and return its path."""
    config_path = tmp_dir / "config.json"
    config_path.write_text(
        json.dumps({"user_language": language}),
        encoding="utf-8",
    )
    return config_path


def _make_test_client(config_path: Path):
    """Return app and patched load/save functions for the given config file."""

    def _load(_path=None):
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return Config(**data)

    def _save(cfg, _path=None):
        config_path.write_text(cfg.model_dump_json(), encoding="utf-8")

    app = FastAPI()
    app.include_router(router)  # router already has prefix="/config"
    return app, _load, _save


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_config_dir():
    """Provide a temporary directory that acts as the config home."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture()
def lang_client(tmp_config_dir):  # pylint: disable=redefined-outer-name
    """TestClient with load_config / save_config patched to use tmp dir."""
    config_path = _write_config(tmp_config_dir, language="en")
    app, _load, _save = _make_test_client(config_path)

    with (
        patch("copaw.app.routers.config.load_config", side_effect=_load),
        patch("copaw.app.routers.config.save_config", side_effect=_save),
    ):
        yield TestClient(app), config_path


# ---------------------------------------------------------------------------
# GET /config/user-language
# ---------------------------------------------------------------------------


class TestGetUserLanguage:
    def test_returns_default_language(self, lang_client):
        """GET returns 'en' when config stores the default language."""
        tc, _ = lang_client
        resp = tc.get("/config/user-language")
        assert resp.status_code == 200
        assert resp.json() == {"language": "en"}

    @pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
    def test_returns_stored_language(
        self,
        tmp_config_dir,
        lang,
    ):  # pylint: disable=redefined-outer-name
        """GET returns whatever language is saved in config."""
        config_path = _write_config(tmp_config_dir, language=lang)
        app, _load, _save = _make_test_client(config_path)

        with (
            patch("copaw.app.routers.config.load_config", side_effect=_load),
            patch("copaw.app.routers.config.save_config", side_effect=_save),
        ):
            tc = TestClient(app)
            resp = tc.get("/config/user-language")
            assert resp.status_code == 200
            assert resp.json()["language"] == lang


# ---------------------------------------------------------------------------
# PUT /config/user-language
# ---------------------------------------------------------------------------


class TestPutUserLanguage:
    @pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
    def test_set_each_supported_language(self, lang_client, lang):
        """PUT persists and returns the chosen language for all 4 locales."""
        tc, config_path = lang_client
        resp = tc.put("/config/user-language", json={"language": lang})
        assert resp.status_code == 200
        assert resp.json() == {"language": lang}

        saved = Config(**json.loads(config_path.read_text(encoding="utf-8")))
        assert saved.user_language == lang

    def test_set_english(self, lang_client):
        """PUT with 'en' persists English."""
        tc, config_path = lang_client
        resp = tc.put("/config/user-language", json={"language": "en"})
        assert resp.status_code == 200
        assert resp.json()["language"] == "en"
        saved = Config(**json.loads(config_path.read_text(encoding="utf-8")))
        assert saved.user_language == "en"

    def test_set_chinese(self, lang_client):
        """PUT with 'zh' persists Chinese."""
        tc, config_path = lang_client
        resp = tc.put("/config/user-language", json={"language": "zh"})
        assert resp.status_code == 200
        assert resp.json()["language"] == "zh"
        saved = Config(**json.loads(config_path.read_text(encoding="utf-8")))
        assert saved.user_language == "zh"

    def test_set_japanese(self, lang_client):
        """PUT with 'ja' persists Japanese."""
        tc, config_path = lang_client
        resp = tc.put("/config/user-language", json={"language": "ja"})
        assert resp.status_code == 200
        assert resp.json()["language"] == "ja"
        saved = Config(**json.loads(config_path.read_text(encoding="utf-8")))
        assert saved.user_language == "ja"

    def test_set_russian(self, lang_client):
        """PUT with 'ru' persists Russian."""
        tc, config_path = lang_client
        resp = tc.put("/config/user-language", json={"language": "ru"})
        assert resp.status_code == 200
        assert resp.json()["language"] == "ru"
        saved = Config(**json.loads(config_path.read_text(encoding="utf-8")))
        assert saved.user_language == "ru"

    def test_strips_whitespace(self, lang_client):
        """Language values with surrounding whitespace are stripped."""
        tc, config_path = lang_client
        resp = tc.put("/config/user-language", json={"language": "  zh  "})
        assert resp.status_code == 200
        assert resp.json()["language"] == "zh"
        saved = Config(**json.loads(config_path.read_text(encoding="utf-8")))
        assert saved.user_language == "zh"

    def test_empty_language_returns_400(self, lang_client):
        """Empty language string is rejected with HTTP 400."""
        tc, _ = lang_client
        resp = tc.put("/config/user-language", json={"language": ""})
        assert resp.status_code == 400

    def test_whitespace_only_returns_400(self, lang_client):
        """Whitespace-only language string is rejected with HTTP 400."""
        tc, _ = lang_client
        resp = tc.put("/config/user-language", json={"language": "   "})
        assert resp.status_code == 400

    def test_missing_language_field_returns_422(self, lang_client):
        """Missing required field returns HTTP 422 Unprocessable Entity."""
        tc, _ = lang_client
        resp = tc.put("/config/user-language", json={})
        assert resp.status_code == 422

    def test_get_after_put_roundtrip(self, lang_client):
        """PUT then GET returns the updated language."""
        tc, _ = lang_client
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
        """UserLanguageConfig accepts a valid language string."""
        cfg = UserLanguageConfig(language="en")
        assert cfg.language == "en"

    @pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
    def test_all_supported_languages(self, lang):
        """UserLanguageConfig accepts each of the 4 supported locales."""
        cfg = UserLanguageConfig(language=lang)
        assert cfg.language == lang

    def test_missing_field_raises(self):
        """UserLanguageConfig raises when the required field is absent."""
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
        """Config.user_language can be assigned any supported locale."""
        cfg = Config(user_language=lang)
        assert cfg.user_language == lang
