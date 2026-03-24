# -*- coding: utf-8 -*-
"""Unit tests for FSBackendConfig."""

import os

import pytest

from copaw.fs_backend.config import FSBackendConfig, is_cloud_mode


# ── defaults ──────────────────────────────────────────────────────────


def test_default_mode_is_local():
    cfg = FSBackendConfig()
    assert cfg.mode == "local"


def test_validate_local_ok():
    cfg = FSBackendConfig(mode="local")
    ok, msg = cfg.validate()
    assert ok is True
    assert msg == ""


def test_validate_invalid_mode():
    cfg = FSBackendConfig(mode="docker")
    ok, msg = cfg.validate()
    assert ok is False
    assert "Invalid mode" in msg


def test_validate_opensandbox_missing_key():
    cfg = FSBackendConfig(mode="opensandbox", opensandbox_api_key=None)
    # Clear env to ensure no fallback
    old = os.environ.pop("OPEN_SANDBOX_API_KEY", None)
    try:
        cfg.opensandbox_api_key = None
        ok, msg = cfg.validate()
        assert ok is False
        assert "OPEN_SANDBOX_API_KEY" in msg
    finally:
        if old is not None:
            os.environ["OPEN_SANDBOX_API_KEY"] = old


def test_validate_opensandbox_with_key():
    cfg = FSBackendConfig(
        mode="opensandbox",
        opensandbox_api_key="test-key-123",
    )
    ok, msg = cfg.validate()
    assert ok is True


# ── from_dict ─────────────────────────────────────────────────────────


def test_from_dict():
    cfg = FSBackendConfig.from_dict({
        "mode": "opensandbox",
        "opensandbox_api_key": "key123",
        "opensandbox_domain": "sandbox.example.com",
        "opensandbox_image": "ubuntu:22.04",
        "opensandbox_timeout": 7200,
        "working_dir": "/data",
    })
    assert cfg.mode == "opensandbox"
    assert cfg.opensandbox_api_key == "key123"
    assert cfg.opensandbox_domain == "sandbox.example.com"
    assert cfg.opensandbox_image == "ubuntu:22.04"
    assert cfg.opensandbox_timeout == 7200
    assert cfg.working_dir == "/data"


def test_from_dict_defaults():
    cfg = FSBackendConfig.from_dict({})
    assert cfg.mode == "local"
    assert cfg.opensandbox_image == "python:3.11"
    assert cfg.opensandbox_timeout == 3600


# ── from_env ──────────────────────────────────────────────────────────


def test_from_env(monkeypatch):
    monkeypatch.setenv("COPAW_FS_MODE", "opensandbox")
    monkeypatch.setenv("OPEN_SANDBOX_API_KEY", "env-key")
    monkeypatch.setenv("OPEN_SANDBOX_DOMAIN", "env.example.com")
    monkeypatch.setenv("COPAW_OPENSANDBOX_IMAGE", "node:20")
    monkeypatch.setenv("COPAW_OPENSANDBOX_TIMEOUT", "600")
    monkeypatch.setenv("COPAW_WORKING_DIR", "/work")

    cfg = FSBackendConfig.from_env()
    assert cfg.mode == "opensandbox"
    assert cfg.opensandbox_api_key == "env-key"
    assert cfg.opensandbox_domain == "env.example.com"
    assert cfg.opensandbox_image == "node:20"
    assert cfg.opensandbox_timeout == 600
    assert cfg.working_dir == "/work"


# ── to_dict ───────────────────────────────────────────────────────────


def test_to_dict_masks_api_key():
    cfg = FSBackendConfig(
        mode="opensandbox",
        opensandbox_api_key="super-secret-key-12345",
    )
    d = cfg.to_dict()
    assert d["opensandbox_api_key"] == "super-secr..."
    assert d["mode"] == "opensandbox"


def test_to_dict_no_key():
    cfg = FSBackendConfig(mode="local")
    cfg.opensandbox_api_key = None
    d = cfg.to_dict()
    assert d["opensandbox_api_key"] is None


# ── is_cloud_mode ─────────────────────────────────────────────────────


def test_is_cloud_mode_false(monkeypatch):
    from copaw.fs_backend import config as config_mod
    config_mod._default_config = FSBackendConfig(mode="local")
    try:
        assert is_cloud_mode() is False
    finally:
        config_mod._default_config = None


def test_is_cloud_mode_true(monkeypatch):
    from copaw.fs_backend import config as config_mod
    config_mod._default_config = FSBackendConfig(mode="opensandbox")
    try:
        assert is_cloud_mode() is True
    finally:
        config_mod._default_config = None
