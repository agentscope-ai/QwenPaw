# -*- coding: utf-8 -*-
"""Security contract tests for Agent tool configuration DTOs."""

import pytest
from pydantic import ValidationError

from qwenpaw.app.routers.tools import (
    ToolConfigUpdate,
    ToolCredentialAction,
    _project_safe_tool_config,
    _validate_tool_config_update,
    _tool_config_fields,
    _ensure_browser_policy_allows_agent_change,
)


FIELDS = [
    {"name": "api_key", "type": "password", "required": True},
    {"name": "endpoint", "type": "text", "required": False},
    {"name": "timeout", "type": "number", "required": False},
]


def test_tool_config_projection_never_returns_password_or_mask() -> None:
    view = _project_safe_tool_config(
        {"api_key": "sk-secret", "endpoint": "https://example.test"},
        FIELDS,
        credential_status={"api_key": "configured"},
    )

    assert view.config == {"endpoint": "https://example.test"}
    assert view.credential_status == {"api_key": "configured"}
    assert "sk-secret" not in view.model_dump_json()
    assert "***" not in view.model_dump_json()


def test_tool_config_update_separates_secret_actions() -> None:
    body = ToolConfigUpdate(
        config={"endpoint": "https://example.test", "timeout": 30},
        credential_updates={
            "api_key": ToolCredentialAction(
                action="replace",
                value="new-secret",
            ),
        },
    )

    non_sensitive, actions = _validate_tool_config_update(body, FIELDS)

    assert non_sensitive == {
        "endpoint": "https://example.test",
        "timeout": 30,
    }
    assert actions["api_key"].action == "replace"
    assert actions["api_key"].value == "new-secret"


@pytest.mark.parametrize(
    "body",
    [
        ToolConfigUpdate(config={"api_key": "plaintext"}),
        ToolConfigUpdate(config={"unknown": "value"}),
        ToolConfigUpdate(
            credential_updates={"endpoint": ToolCredentialAction(action="delete")}
        ),
    ],
)
def test_tool_config_update_rejects_secret_leaks_and_unknown_fields(body) -> None:
    with pytest.raises(ValueError):
        _validate_tool_config_update(body, FIELDS)


def test_replace_secret_requires_non_empty_value() -> None:
    with pytest.raises(ValidationError):
        ToolCredentialAction(action="replace", value="")


def test_keep_and_delete_reject_secret_value() -> None:
    for action in ("keep", "delete"):
        with pytest.raises(ValidationError):
            ToolCredentialAction(action=action, value="should-not-be-sent")


def test_browser_builtin_keeps_its_single_user_experimental_field() -> None:
    class Registry:
        def get_plugin_id_for_tool(self, _name):
            return None

    assert _tool_config_fields(Registry(), "browser") == [
        {
            "name": "experimental",
            "label": "Browser implementation",
            "type": "boolean",
            "required": False,
        }
    ]


def test_browser_policy_blocks_agent_changes_when_platform_disables_it(
    monkeypatch,
) -> None:
    from fastapi import HTTPException
    from types import SimpleNamespace

    monkeypatch.setattr(
        "qwenpaw.app.routers.tools.is_multi_user_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.tools.load_config",
        lambda: SimpleNamespace(
            browser=SimpleNamespace(multi_user_enabled=False),
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        _ensure_browser_policy_allows_agent_change("browser")

    assert exc_info.value.status_code == 403
