# -*- coding: utf-8 -*-
"""Integration tests for Auth & config utils internals.

Covers src/qwenpaw/app/auth.py (207 uncovered) and
src/qwenpaw/config/utils.py (290 uncovered).
"""

from __future__ import annotations

import pytest


# ------------------------------------------------------------------ #
# auth
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_auth_password_hash_verify_roundtrip() -> None:
    """_hash_password + verify_password round-trip."""
    from qwenpaw.app.auth import _hash_password, verify_password

    hashed, salt = _hash_password("integ-password")
    assert verify_password("integ-password", hashed, salt) is True
    assert verify_password("wrong", hashed, salt) is False


@pytest.mark.integration
@pytest.mark.p1
def test_auth_token_roundtrip() -> None:
    """create_token + verify_token round-trip."""
    from qwenpaw.app.auth import create_token, verify_token

    token = create_token("integ-user")
    assert isinstance(token, str)
    username = verify_token(token)
    assert username == "integ-user"


@pytest.mark.integration
@pytest.mark.p1
def test_auth_verify_token_garbage() -> None:
    """verify_token returns None for a garbage token."""
    from qwenpaw.app.auth import verify_token

    assert verify_token("not-a-real-token") is None


@pytest.mark.integration
@pytest.mark.p1
def test_auth_is_enabled() -> None:
    """is_auth_enabled returns a bool."""
    from qwenpaw.app.auth import is_auth_enabled

    assert isinstance(is_auth_enabled(), bool)


# ------------------------------------------------------------------ #
# config utils
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_config_get_config_path() -> None:
    """get_config_path returns a Path."""
    from qwenpaw.config.utils import get_config_path

    assert get_config_path().name.endswith(".json")


@pytest.mark.integration
@pytest.mark.p1
def test_config_get_available_channels() -> None:
    """get_available_channels returns a tuple of channel ids."""
    from qwenpaw.config.utils import get_available_channels

    channels = get_available_channels()
    assert isinstance(channels, tuple)
    assert "console" in channels


@pytest.mark.integration
@pytest.mark.p1
def test_config_is_running_in_container() -> None:
    """is_running_in_container returns a bool."""
    from qwenpaw.config.utils import is_running_in_container

    assert isinstance(is_running_in_container(), bool)


@pytest.mark.integration
@pytest.mark.p1
def test_config_load_config() -> None:
    """load_config returns a Config object."""
    from qwenpaw.config.utils import load_config

    config = load_config()
    assert config is not None


@pytest.mark.integration
@pytest.mark.p1
def test_config_remove_nested_key() -> None:
    """_remove_nested_key removes a nested path."""
    from qwenpaw.config.utils import _remove_nested_key

    data = {"a": {"b": {"c": 1}}}
    assert _remove_nested_key(data, ["a", "b", "c"]) is True
    assert data == {"a": {"b": {}}}
    assert _remove_nested_key(data, ["a", "x"]) is False
