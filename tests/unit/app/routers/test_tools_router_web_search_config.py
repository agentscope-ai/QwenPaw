# -*- coding: utf-8 -*-
"""Unit tests for the ``web_search`` builtin-tool Console config plumbing
in ``qwenpaw.app.routers.tools``.

Covers:
- ``_builtin_credential_ref`` ref derivation (provider present/blank)
- ``GET /tools/web_search/config`` — credential-store readback + masking
- ``POST /tools/web_search/config`` — the 4-way api_key semantics table:
  missing (preserve) / empty string (clear) / masked value (preserve) /
  new value (store)
"""
# pylint: disable=protected-access,redefined-outer-name
# flake8: noqa: E501
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
import pytest

from qwenpaw.app.routers.tools import (
    ToolConfigUpdate,
    _builtin_credential_ref,
    get_tool_config,
    update_tool_config,
)
from qwenpaw.drivers.credentials.types import CredentialRecord
from qwenpaw.security.secret_store import mask_secret_value


def _workspace(agent_id: str = "default") -> SimpleNamespace:
    return SimpleNamespace(agent_id=agent_id)


def _registry_mock(*, tool_config: dict | None = None) -> MagicMock:
    """A PluginRegistry stand-in where web_search is never a plugin tool."""
    registry = MagicMock(name="PluginRegistry")
    registry.get_plugin_id_for_tool.return_value = None
    registry.get_tool_config.return_value = tool_config or {}
    return registry


# ---------------------------------------------------------------------------
# _builtin_credential_ref
# ---------------------------------------------------------------------------


def test_builtin_credential_ref_with_provider() -> None:
    ref = _builtin_credential_ref("web_search", {"provider": "anysearch"})
    assert ref == "tool/web_search/anysearch"


def test_builtin_credential_ref_blank_provider_returns_empty() -> None:
    assert _builtin_credential_ref("web_search", {}) == ""
    assert _builtin_credential_ref("web_search", {"provider": ""}) == ""
    assert _builtin_credential_ref("web_search", {"provider": "  "}) == ""


# ---------------------------------------------------------------------------
# GET /tools/web_search/config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tool_config_reads_credential_and_masks() -> None:
    registry = _registry_mock(tool_config={"provider": "anysearch"})
    record = CredentialRecord(
        ref="tool/web_search/anysearch",
        kind="static",
        secrets={"api_key": "as_sk_00d83dc1b2f507950d7e5412952b5fdf"},
    )

    with (
        patch(
            "qwenpaw.plugins.registry.PluginRegistry",
            return_value=registry,
        ),
        patch(
            "qwenpaw.app.agent_context.get_agent_for_request",
            AsyncMock(return_value=_workspace()),
        ),
        patch(
            "qwenpaw.app.driver_config_service.DriverConfigService"
            ".load_optional_credential",
            AsyncMock(return_value=record),
        ),
    ):
        result = await get_tool_config(tool_name="web_search", request=None)

    assert result["provider"] == "anysearch"
    assert result["api_key"] == mask_secret_value(
        "as_sk_00d83dc1b2f507950d7e5412952b5fdf",
    )
    assert result["api_key"] != "as_sk_00d83dc1b2f507950d7e5412952b5fdf"


@pytest.mark.asyncio
async def test_get_tool_config_blank_provider_skips_credential_lookup() -> None:  # noqa: E501
    registry = _registry_mock(tool_config={})
    load_credential = AsyncMock()

    with (
        patch(
            "qwenpaw.plugins.registry.PluginRegistry",
            return_value=registry,
        ),
        patch(
            "qwenpaw.app.agent_context.get_agent_for_request",
            AsyncMock(return_value=_workspace()),
        ),
        patch(
            "qwenpaw.app.driver_config_service.DriverConfigService"
            ".load_optional_credential",
            load_credential,
        ),
    ):
        result = await get_tool_config(tool_name="web_search", request=None)

    assert result == {}
    load_credential.assert_not_called()


@pytest.mark.asyncio
async def test_get_tool_config_no_stored_key_omits_api_key() -> None:
    registry = _registry_mock(tool_config={"provider": "tavily"})

    with (
        patch(
            "qwenpaw.plugins.registry.PluginRegistry",
            return_value=registry,
        ),
        patch(
            "qwenpaw.app.agent_context.get_agent_for_request",
            AsyncMock(return_value=_workspace()),
        ),
        patch(
            "qwenpaw.app.driver_config_service.DriverConfigService"
            ".load_optional_credential",
            AsyncMock(return_value=None),
        ),
    ):
        result = await get_tool_config(tool_name="web_search", request=None)

    assert result == {"provider": "tavily"}
    assert "api_key" not in result


@pytest.mark.asyncio
async def test_get_tool_config_provider_query_wins_over_saved_config() -> None:
    """Saved provider is tavily, but the frontend asks for anysearch's slot
    (user is about to switch). The query param must drive the credential
    lookup so an existing anysearch key is returned instead of a blank."""
    registry = _registry_mock(tool_config={"provider": "tavily"})
    record = CredentialRecord(
        ref="tool/web_search/anysearch",
        kind="static",
        secrets={"api_key": "as_sk_query_provider_key"},
    )
    load_credential = AsyncMock(return_value=record)

    with (
        patch(
            "qwenpaw.plugins.registry.PluginRegistry",
            return_value=registry,
        ),
        patch(
            "qwenpaw.app.agent_context.get_agent_for_request",
            AsyncMock(return_value=_workspace()),
        ),
        patch(
            "qwenpaw.app.driver_config_service.DriverConfigService"
            ".load_optional_credential",
            load_credential,
        ),
    ):
        result = await get_tool_config(
            tool_name="web_search",
            request=None,
            provider="anysearch",
        )

    load_credential.assert_awaited_once_with("tool/web_search/anysearch")
    assert result["provider"] == "anysearch"
    assert result["api_key"] == mask_secret_value("as_sk_query_provider_key")


# ---------------------------------------------------------------------------
# POST /tools/web_search/config — 4-way api_key semantics
# ---------------------------------------------------------------------------


async def _update(
    *,
    config: dict,
    registry: MagicMock,
    credential_store: MagicMock,
    load_optional_credential: AsyncMock,
):
    with (
        patch(
            "qwenpaw.plugins.registry.PluginRegistry",
            return_value=registry,
        ),
        patch(
            "qwenpaw.app.agent_context.get_agent_for_request",
            AsyncMock(return_value=_workspace()),
        ),
        patch(
            "qwenpaw.app.driver_config_service.DriverConfigService"
            ".load_optional_credential",
            load_optional_credential,
        ),
        patch(
            "qwenpaw.app.driver_config_service.DriverConfigService"
            ".credential_store",
            new_callable=lambda: property(lambda self: credential_store),
        ),
        patch("qwenpaw.app.routers.tools.schedule_agent_reload"),
    ):
        return await update_tool_config(
            tool_name="web_search",
            body=ToolConfigUpdate(config=config),
            request=None,
        )


@pytest.mark.asyncio
async def test_update_tool_config_missing_api_key_preserves_existing() -> None:
    """Field absent from the submitted body -> credential store untouched."""
    registry = _registry_mock()
    credential_store = MagicMock()
    credential_store.put = AsyncMock()
    credential_store.delete = AsyncMock()

    resp = await _update(
        config={"provider": "anysearch"},  # no "api_key" key at all
        registry=registry,
        credential_store=credential_store,
        load_optional_credential=AsyncMock(),
    )

    assert resp["status"] == "success"
    credential_store.put.assert_not_called()
    credential_store.delete.assert_not_called()


@pytest.mark.asyncio
async def test_update_tool_config_empty_api_key_clears_existing() -> None:
    """Empty string -> existing credential is deleted."""
    registry = _registry_mock()
    credential_store = MagicMock()
    credential_store.put = AsyncMock()
    credential_store.delete = AsyncMock()
    old_record = CredentialRecord(
        ref="tool/web_search/anysearch",
        kind="static",
        secrets={"api_key": "old-key"},
    )

    resp = await _update(
        config={"provider": "anysearch", "api_key": ""},
        registry=registry,
        credential_store=credential_store,
        load_optional_credential=AsyncMock(return_value=old_record),
    )

    assert resp["status"] == "success"
    credential_store.delete.assert_awaited_once_with(
        "tool/web_search/anysearch",
    )
    credential_store.put.assert_not_called()


@pytest.mark.asyncio
async def test_update_tool_config_masked_value_preserves_existing() -> None:
    """Submitting the masked display value -> treated as unchanged."""
    registry = _registry_mock()
    credential_store = MagicMock()
    credential_store.put = AsyncMock()
    credential_store.delete = AsyncMock()
    old_key = "as_sk_00d83dc1b2f507950d7e5412952b5fdf"
    old_record = CredentialRecord(
        ref="tool/web_search/anysearch",
        kind="static",
        secrets={"api_key": old_key},
    )

    resp = await _update(
        config={
            "provider": "anysearch",
            "api_key": mask_secret_value(old_key),
        },
        registry=registry,
        credential_store=credential_store,
        load_optional_credential=AsyncMock(return_value=old_record),
    )

    assert resp["status"] == "success"
    # restore_masked_secret_value recognizes the masked echo -> re-puts the
    # same underlying key (no destructive clear, no unrelated mutation).
    credential_store.put.assert_awaited_once()
    put_call = credential_store.put.await_args.args[0]
    assert put_call.secrets["api_key"] == old_key
    credential_store.delete.assert_not_called()


@pytest.mark.asyncio
async def test_update_tool_config_new_value_stores_new_key() -> None:
    """A genuinely new value -> stored verbatim."""
    registry = _registry_mock()
    credential_store = MagicMock()
    credential_store.put = AsyncMock()
    credential_store.delete = AsyncMock()

    resp = await _update(
        config={"provider": "anysearch", "api_key": "sk-brand-new"},
        registry=registry,
        credential_store=credential_store,
        load_optional_credential=AsyncMock(return_value=None),
    )

    assert resp["status"] == "success"
    credential_store.put.assert_awaited_once()
    put_call = credential_store.put.await_args.args[0]
    assert put_call.ref == "tool/web_search/anysearch"
    assert put_call.kind == "static"
    assert put_call.secrets["api_key"] == "sk-brand-new"
    credential_store.delete.assert_not_called()


@pytest.mark.asyncio
async def test_update_tool_config_blank_provider_skips_credential_io() -> None:
    """No provider selected -> credential store never touched, even if an
    api_key field is present in the submitted body."""
    registry = _registry_mock()
    credential_store = MagicMock()
    credential_store.put = AsyncMock()
    credential_store.delete = AsyncMock()

    resp = await _update(
        config={"api_key": "sk-should-be-ignored"},
        registry=registry,
        credential_store=credential_store,
        load_optional_credential=AsyncMock(),
    )

    assert resp["status"] == "success"
    credential_store.put.assert_not_called()
    credential_store.delete.assert_not_called()


# ---------------------------------------------------------------------------
# POST /tools/web_search/config — transactional ordering (review #7081,
# Issue 2): agent.json is committed before the credential mutation, and a
# failed credential write rolls the config back.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_tool_config_config_failure_leaves_credential_untouched() -> None:
    """Config write failing must not leave a half-applied credential."""
    registry = _registry_mock()
    credential_store = MagicMock()
    credential_store.put = AsyncMock()
    credential_store.delete = AsyncMock()
    update_config = AsyncMock(side_effect=RuntimeError("disk full"))

    with (
        patch(
            "qwenpaw.plugins.registry.PluginRegistry",
            return_value=registry,
        ),
        patch(
            "qwenpaw.app.agent_context.get_agent_for_request",
            AsyncMock(return_value=_workspace()),
        ),
        patch(
            "qwenpaw.app.driver_config_service.DriverConfigService"
            ".load_optional_credential",
            AsyncMock(return_value=None),
        ),
        patch(
            "qwenpaw.app.driver_config_service.DriverConfigService"
            ".credential_store",
            new_callable=lambda: property(lambda self: credential_store),
        ),
        patch(
            "qwenpaw.app.routers.tools.update_agent_config_async",
            update_config,
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await update_tool_config(
                tool_name="web_search",
                body=ToolConfigUpdate(
                    config={"provider": "anysearch", "api_key": "sk-new"},
                ),
                request=None,
            )

    assert exc_info.value.status_code == 500
    credential_store.put.assert_not_called()
    credential_store.delete.assert_not_called()


@pytest.mark.asyncio
async def test_update_tool_config_credential_failure_rolls_back_config() -> None:
    """A failed credential write must restore the previous agent config."""
    registry = _registry_mock()
    credential_store = MagicMock()
    credential_store.put = AsyncMock(side_effect=OSError("disk full"))
    credential_store.delete = AsyncMock()
    update_config = AsyncMock()

    with (
        patch(
            "qwenpaw.plugins.registry.PluginRegistry",
            return_value=registry,
        ),
        patch(
            "qwenpaw.app.agent_context.get_agent_for_request",
            AsyncMock(return_value=_workspace()),
        ),
        patch(
            "qwenpaw.app.driver_config_service.DriverConfigService"
            ".load_optional_credential",
            AsyncMock(return_value=None),
        ),
        patch(
            "qwenpaw.app.driver_config_service.DriverConfigService"
            ".credential_store",
            new_callable=lambda: property(lambda self: credential_store),
        ),
        patch(
            "qwenpaw.app.routers.tools.update_agent_config_async",
            update_config,
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await update_tool_config(
                tool_name="web_search",
                body=ToolConfigUpdate(
                    config={"provider": "anysearch", "api_key": "sk-new"},
                ),
                request=None,
            )

    assert exc_info.value.status_code == 500
    # Commit + best-effort rollback.
    assert update_config.await_count == 2
    credential_store.delete.assert_not_called()


@pytest.mark.asyncio
async def test_update_tool_config_keyless_provider_skips_credential_io() -> None:
    """provider=tavily is keyless: an api_key in the body must not land in
    any credential slot (regression: switching anysearch->tavily used to
    write the leftover key into tool/web_search/tavily)."""
    registry = _registry_mock()
    credential_store = MagicMock()
    credential_store.put = AsyncMock()
    credential_store.delete = AsyncMock()

    resp = await _update(
        config={"provider": "tavily", "api_key": "sk-should-be-ignored"},
        registry=registry,
        credential_store=credential_store,
        load_optional_credential=AsyncMock(),
    )

    assert resp["status"] == "success"
    credential_store.put.assert_not_called()
    credential_store.delete.assert_not_called()


def test_builtin_credential_ref_keyless_provider_returns_empty() -> None:
    assert _builtin_credential_ref("web_search", {"provider": "tavily"}) == ""
