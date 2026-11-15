# -*- coding: utf-8 -*-
"""Tests for per-agent WeChat credential scoping.

Two agents must be able to hold **different** WeChat accounts in one
installation. Scopes are hashed from the credential file paths (and the inline
credential, when set), so the fallback path must be resolved against each
agent's own workspace — not the process-wide WORKING_DIR.
"""

# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path

from qwenpaw.app.channels.wechat_auth_custody import wechat_auth_scopes


def test_same_config_and_dir_yields_identical_scopes(tmp_path: Path) -> None:
    config = {"enabled": True}
    assert wechat_auth_scopes(
        config,
        working_dir=tmp_path,
    ) == wechat_auth_scopes(
        config,
        working_dir=tmp_path,
    )


def test_default_token_file_follows_the_working_dir(tmp_path: Path) -> None:
    """No explicit bot_token_file → the workspace decides, not a global path."""
    config = {"enabled": True}
    first = wechat_auth_scopes(config, working_dir=tmp_path / "agent-a")
    second = wechat_auth_scopes(config, working_dir=tmp_path / "agent-b")

    assert first and second
    assert set(first).isdisjoint(second)


def test_explicit_token_files_in_separate_dirs_are_independent(
    tmp_path: Path,
) -> None:
    """One credential directory per agent: token + context tokens both differ."""
    shared_dir = tmp_path / "shared"
    first = wechat_auth_scopes(
        {
            "enabled": True,
            "bot_token_file": str(tmp_path / "agent-a" / "token"),
        },
        working_dir=shared_dir,
    )
    second = wechat_auth_scopes(
        {
            "enabled": True,
            "bot_token_file": str(tmp_path / "agent-b" / "token"),
        },
        working_dir=shared_dir,
    )

    assert set(first).isdisjoint(second)


def test_token_files_in_one_dir_still_share_the_context_token_file(
    tmp_path: Path,
) -> None:
    """Documents the boundary: the context-token file lives beside the token."""
    first = wechat_auth_scopes(
        {"enabled": True, "bot_token_file": str(tmp_path / "a_token")},
        working_dir=tmp_path,
    )
    second = wechat_auth_scopes(
        {"enabled": True, "bot_token_file": str(tmp_path / "b_token")},
        working_dir=tmp_path,
    )

    assert set(first) & set(second), "same directory shares context tokens"


def test_inline_credential_is_scoped_by_its_value(tmp_path: Path) -> None:
    """The same inline token is the same account, wherever it lives."""
    first = wechat_auth_scopes(
        {"enabled": True, "bot_token": "token-abc"},
        working_dir=tmp_path / "agent-a",
    )
    second = wechat_auth_scopes(
        {"enabled": True, "bot_token": "token-abc"},
        working_dir=tmp_path / "agent-b",
    )

    assert set(first) & set(second), "identical credentials must collide"


def test_different_inline_credentials_do_not_collide(tmp_path: Path) -> None:
    first = wechat_auth_scopes(
        {"enabled": True, "bot_token": "token-a"},
        working_dir=tmp_path / "agent-a",
    )
    second = wechat_auth_scopes(
        {"enabled": True, "bot_token": "token-b"},
        working_dir=tmp_path / "agent-b",
    )

    assert set(first).isdisjoint(second)
