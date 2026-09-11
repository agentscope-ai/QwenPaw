# -*- coding: utf-8 -*-
from __future__ import annotations

import json

import pytest

from qwenpaw.plugins.marketplace_registry import ExternalMarketplaceRegistry


@pytest.mark.asyncio
async def test_marketplace_registry_scrubs_url_credentials_and_is_idempotent(
    tmp_path,
):
    path = tmp_path / "marketplaces.json"
    registry = ExternalMarketplaceRegistry(path)

    first = await registry.register_if_absent(
        provider="codex",
        source_id="codex:private",
        name="private",
        source="https://user:secret@example.com/plugins.zip?token=secret#x",
        source_type="url",
    )
    second = await registry.register_if_absent(
        provider="codex",
        source_id="codex:private",
        name="private",
        source="https://user:secret@example.com/plugins.zip?token=secret#x",
        source_type="url",
    )

    assert first == ("created", True)
    assert second == ("same", True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    record = payload["sources"]["codex:codex:private"]
    assert record["source"] == "https://example.com/plugins.zip"
    assert "secret" not in path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_marketplace_registry_keeps_a_conflicting_source(tmp_path):
    registry = ExternalMarketplaceRegistry(tmp_path / "marketplaces.json")
    await registry.register_if_absent(
        provider="codex",
        source_id="codex:local",
        name="local",
        source="https://example.com/old.git",
        source_type="git",
    )

    result = await registry.register_if_absent(
        provider="codex",
        source_id="codex:local",
        name="local",
        source="https://example.com/new.git",
        source_type="git",
    )

    assert result == ("conflict", False)
    payload = json.loads(registry.path.read_text(encoding="utf-8"))
    assert payload["sources"]["codex:codex:local"]["source"].endswith(
        "old.git",
    )
