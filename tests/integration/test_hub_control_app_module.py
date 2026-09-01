# -*- coding: utf-8 -*-
"""Integration tests for QwenPaw Hub control-app helpers.

Covers src/qwenpaw/hub/control_app.py (570 uncovered lines):
hub data-root resolution, pagination envelope, runtime payload
assembly.
"""
# pylint: disable=protected-access,consider-using-from-import

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_get_hub_root_default(monkeypatch) -> None:
    """Without QWENPAW_HUB_DIR the hub root is WORKING_DIR/hub."""
    import qwenpaw.hub.control_app as control_app

    monkeypatch.delenv("QWENPAW_HUB_DIR", raising=False)
    root = control_app.get_hub_root()
    assert root.name == "hub"
    assert root.is_absolute()


@pytest.mark.integration
@pytest.mark.p1
def test_get_hub_root_env_override(tmp_path: Path, monkeypatch) -> None:
    """QWENPAW_HUB_DIR overrides the hub data root."""
    import qwenpaw.hub.control_app as control_app

    custom = tmp_path / "custom-hub"
    monkeypatch.setenv("QWENPAW_HUB_DIR", str(custom))
    root = control_app.get_hub_root()
    assert root == custom.resolve()


@pytest.mark.integration
@pytest.mark.p1
def test_get_hub_root_blank_env_falls_back(monkeypatch) -> None:
    """Blank QWENPAW_HUB_DIR is treated as unset."""
    import qwenpaw.hub.control_app as control_app

    monkeypatch.setenv("QWENPAW_HUB_DIR", "   ")
    root = control_app.get_hub_root()
    assert root.name == "hub"


@pytest.mark.integration
@pytest.mark.p1
def test_page_payload_single_page() -> None:
    """Small totals fit on one page."""
    import qwenpaw.hub.control_app as control_app

    payload = control_app._page_payload(["a", "b"], 1, 10, 2)
    assert payload["items"] == ["a", "b"]
    assert payload["page"] == 1
    assert payload["page_size"] == 10
    assert payload["total"] == 2
    assert payload["pages"] == 1


@pytest.mark.integration
@pytest.mark.p1
def test_page_payload_multi_page() -> None:
    """Page count rounds up for partial pages."""
    import qwenpaw.hub.control_app as control_app

    payload = control_app._page_payload([], 2, 10, 25)
    assert payload["pages"] == 3
    assert payload["page"] == 2


@pytest.mark.integration
@pytest.mark.p1
def test_page_payload_zero_total() -> None:
    """Zero items still report at least one page."""
    import qwenpaw.hub.control_app as control_app

    payload = control_app._page_payload([], 1, 10, 0)
    assert payload["pages"] == 1
    assert payload["total"] == 0


@pytest.mark.integration
@pytest.mark.p1
def test_runtime_payload_assembly() -> None:
    """Runtime payload adds owner, endpoint, and security level."""
    import qwenpaw.hub.control_app as control_app

    class FakeRecord:
        host = "127.0.0.1"
        port = 6199
        provisioner = "local"

        def to_dict(self) -> dict:
            return {"id": "rt-1", "state": "running"}

    class FakeService:
        def security_level(self, provisioner: str) -> str:
            return "sandboxed" if provisioner == "docker" else "local"

    payload = control_app._runtime_payload(
        FakeService(),
        FakeRecord(),
        owner_username="alice",
    )
    assert payload["id"] == "rt-1"
    assert payload["owner_username"] == "alice"
    assert payload["endpoint"] == "http://127.0.0.1:6199"
    assert payload["security_level"] == "local"
