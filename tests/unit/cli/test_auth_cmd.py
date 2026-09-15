# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Unit tests for `qwenpaw auth reset-password`."""

import pytest
from click.testing import CliRunner

from qwenpaw.cli import auth_cmd as auth_mod


@pytest.fixture()
def auth_env(monkeypatch):
    """Stub the auth module so no real SECRET_DIR/auth.json is touched."""
    state = {
        "enabled": True,
        "data": {
            "user": {
                "username": "alice",
                "password_hash": "old-hash",
                "password_salt": "old-salt",
            },
            "jwt_secret": "old-jwt-secret",
        },
        "load_error": None,
        "saved": [],
        "hashed": [],
    }

    monkeypatch.setattr(auth_mod, "is_auth_enabled", lambda: state["enabled"])

    def fake_load():
        data = dict(state["data"])
        if state["load_error"]:
            data["_auth_load_error"] = state["load_error"]
        return data

    monkeypatch.setattr(auth_mod, "_load_auth_data", fake_load)
    monkeypatch.setattr(auth_mod, "_save_auth_data", state["saved"].append)

    def fake_hash(password, salt=None):
        state["hashed"].append((password, salt))
        return ("hash-of-" + password, "salt-of-" + password)

    monkeypatch.setattr(auth_mod, "_hash_password", fake_hash)

    # Make token_hex deterministic so rotation can be asserted.
    tokens = iter(["rotated-secret-1", "rotated-secret-2"])
    monkeypatch.setattr(auth_mod.secrets, "token_hex", lambda _n: next(tokens))

    return state


class TestAuthDisabled:
    def test_reports_that_auth_is_not_enabled(self, auth_env):
        auth_env["enabled"] = False

        result = CliRunner().invoke(auth_mod.auth_group, ["reset-password"])

        assert result.exit_code == 0
        assert "Authentication is not enabled." in result.output
        assert "QWENPAW_AUTH_ENABLED=true" in result.output

    def test_does_not_prompt_or_save_when_disabled(self, auth_env):
        auth_env["enabled"] = False

        result = CliRunner().invoke(
            auth_mod.auth_group, ["reset-password"], input="pw\npw\n"
        )

        assert result.exit_code == 0
        assert auth_env["saved"] == []
        assert auth_env["hashed"] == []


class TestLoadError:
    def test_raises_click_exception_on_corrupt_auth_data(self, auth_env):
        auth_env["load_error"] = "bad json"

        result = CliRunner().invoke(auth_mod.auth_group, ["reset-password"])

        assert result.exit_code != 0
        assert "Failed to read auth data" in result.output
        assert "auth.json" in result.output


class TestNoUser:
    def test_reports_nothing_to_reset(self, auth_env):
        auth_env["data"] = {"jwt_secret": "s"}

        result = CliRunner().invoke(auth_mod.auth_group, ["reset-password"])

        assert result.exit_code == 0
        assert "No registered user found. Nothing to reset." in result.output
        assert auth_env["saved"] == []

    def test_empty_user_dict_is_treated_as_absent(self, auth_env):
        auth_env["data"] = {"user": {}, "jwt_secret": "s"}

        result = CliRunner().invoke(auth_mod.auth_group, ["reset-password"])

        assert result.exit_code == 0
        assert "No registered user found" in result.output


class TestSuccessfulReset:
    def test_announces_the_target_username(self, auth_env):
        result = CliRunner().invoke(
            auth_mod.auth_group, ["reset-password"], input="newpw\nnewpw\n"
        )

        assert result.exit_code == 0
        assert "Resetting password for user: alice" in result.output

    def test_falls_back_to_unknown_when_username_missing(self, auth_env):
        auth_env["data"]["user"] = {"password_hash": "h"}

        result = CliRunner().invoke(
            auth_mod.auth_group, ["reset-password"], input="newpw\nnewpw\n"
        )

        assert "Resetting password for user: <unknown>" in result.output

    def test_stores_the_new_hash_and_salt(self, auth_env):
        CliRunner().invoke(
            auth_mod.auth_group, ["reset-password"], input="newpw\nnewpw\n"
        )

        saved = auth_env["saved"][-1]
        assert saved["user"]["password_hash"] == "hash-of-newpw"
        assert saved["user"]["password_salt"] == "salt-of-newpw"

    def test_hashes_the_prompted_password(self, auth_env):
        CliRunner().invoke(
            auth_mod.auth_group, ["reset-password"], input="newpw\nnewpw\n"
        )

        assert auth_env["hashed"] == [("newpw", None)]

    def test_rotates_the_jwt_secret_to_invalidate_sessions(self, auth_env):
        CliRunner().invoke(
            auth_mod.auth_group, ["reset-password"], input="newpw\nnewpw\n"
        )

        saved = auth_env["saved"][-1]
        assert saved["jwt_secret"] == "rotated-secret-1"
        assert saved["jwt_secret"] != auth_env["data"]["jwt_secret"]

    def test_confirms_sessions_were_invalidated(self, auth_env):
        result = CliRunner().invoke(
            auth_mod.auth_group, ["reset-password"], input="newpw\nnewpw\n"
        )

        assert "Password reset successfully" in result.output
        assert "sessions have been invalidated" in result.output

    def test_saves_exactly_once(self, auth_env):
        CliRunner().invoke(
            auth_mod.auth_group, ["reset-password"], input="newpw\nnewpw\n"
        )

        assert len(auth_env["saved"]) == 1


class TestEmptyPassword:
    def test_empty_input_is_aborted_by_the_prompt_layer(self, auth_env):
        """`click.prompt(confirmation_prompt=True)` retries an empty line until
        EOF, then aborts — so the empty string never reaches the command body.

        Probed: empty input -> exit 1, no value returned; the product's
        `if not new_password` half is therefore unreachable via the CLI, while
        the `not new_password.strip()` half is exercised by the whitespace test
        below. Assert the real behaviour (abort, nothing saved) rather than a
        message the body never prints on this path.
        """
        result = CliRunner().invoke(
            auth_mod.auth_group, ["reset-password"], input="\n\n"
        )

        assert result.exit_code != 0
        assert "Aborted" in result.output
        assert auth_env["saved"] == []
        assert auth_env["hashed"] == []

    def test_rejects_a_whitespace_only_password(self, auth_env):
        # Whitespace passes the prompt but is caught by the body's .strip() guard.
        result = CliRunner().invoke(
            auth_mod.auth_group, ["reset-password"], input="   \n   \n"
        )

        assert result.exit_code != 0
        assert "Password cannot be empty." in result.output

    def test_nothing_is_saved_when_the_password_is_rejected(self, auth_env):
        CliRunner().invoke(
            auth_mod.auth_group, ["reset-password"], input="   \n   \n"
        )

        assert auth_env["saved"] == []
        assert auth_env["hashed"] == []


class TestConfirmationPrompt:
    def test_mismatched_confirmation_aborts_without_saving(self, auth_env):
        result = CliRunner().invoke(
            auth_mod.auth_group, ["reset-password"], input="one\ntwo\n"
        )

        assert result.exit_code != 0
        assert auth_env["saved"] == []
