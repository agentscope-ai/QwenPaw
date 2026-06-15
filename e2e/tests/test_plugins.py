# -*- coding: utf-8 -*-
"""
QwenPaw Plugin Manager end-to-end tests.

Cases:
- PLUGIN-001 P0  test_plugin_manager_page_loads
- PLUGIN-002 P0  test_install_minimal_zip_via_api
- PLUGIN-003 P1  test_uninstall_plugin_via_api_and_disk_cleanup
- PLUGIN-004 P2  test_install_duplicate_returns_409
- PLUGIN-005 P2  test_install_invalid_zip_returns_400
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest
from playwright.sync_api import expect

from pages.plugin_page import PluginPage
from utils.helpers import log_test_step, log_test_result


logger = logging.getLogger(__name__)


def _unique_plugin_id(prefix: str = "e2e-plugin") -> str:
    return f"{prefix}-{int(time.time() * 1000)}"


def _safe_uninstall(plugin_page: PluginPage, api_context, plugin_id: str):
    """Best-effort cleanup; never raises."""
    try:
        plugin_page.api_uninstall_plugin(api_context, plugin_id)
    except Exception as exc:  # pragma: no cover
        logger.warning("Cleanup uninstall failed for %s: %s", plugin_id, exc)


# ============================================================================
# PLUGIN-001 P0 — Plugin Manager page loads
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.plugins
class TestPluginManagerPageLoads:
    """PLUGIN-001: /plugin-manager renders header, install button, two tabs."""

    @pytest.mark.test_id("PLUGIN-001")
    def test_plugin_manager_page_loads(
        self,
        plugin_page: PluginPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        log_test_step("1. Navigate to /plugin-manager")
        plugin_page.open()

        log_test_step("2. 'Install Plugin' button visible (page-ready signal)")
        expect(
            plugin_page.page.locator(plugin_page.INSTALL_BTN).first
        ).to_be_visible(timeout=plugin_page.timeout)

        log_test_step("3. 'Installed' and 'Official' tabs both visible")
        expect(
            plugin_page.page.locator(plugin_page.TAB_INSTALLED).first
        ).to_be_visible(timeout=plugin_page.timeout)
        expect(
            plugin_page.page.locator(plugin_page.TAB_OFFICIAL).first
        ).to_be_visible(timeout=plugin_page.timeout)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# PLUGIN-002 P0 — Install minimal fixture plugin via API
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.plugins
class TestInstallMinimalZip:
    """PLUGIN-002: Upload a self-built zero-dep plugin zip, assert it loads."""

    @pytest.mark.test_id("PLUGIN-002")
    def test_install_minimal_zip_via_api(
        self,
        plugin_page: PluginPage,
        api_context,
        tmp_path: Path,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        plugin_id = _unique_plugin_id()

        log_test_step("1. Build a minimal fixture plugin zip")
        zip_path = plugin_page.build_fixture_plugin_zip(tmp_path, plugin_id)

        try:
            log_test_step("2. Upload via POST /api/plugins/upload")
            resp = plugin_page.api_upload_plugin(api_context, zip_path)
            assert resp.ok, (
                f"Upload failed [{resp.status}]: {resp.text()}"
            )

            log_test_step("3. /api/plugins lists the new plugin")
            ids = [
                p.get("plugin_id") or p.get("id") or p.get("name")
                for p in plugin_page.api_list_plugins(api_context)
            ]
            assert plugin_id in ids, (
                f"Expected {plugin_id} in plugin list; got {ids}"
            )

            log_test_step("4. /api/plugins/<id>/status reports loaded")
            status = plugin_page.api_get_plugin_status(api_context, plugin_id)
            assert status is not None, "status endpoint returned 404"
            # Different backends may use loaded vs enabled — accept either.
            assert (
                status.get("loaded") is True
                or status.get("enabled") is True
            ), f"Expected loaded/enabled True; got {status}"

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed (id={plugin_id})")
        finally:
            _safe_uninstall(plugin_page, api_context, plugin_id)


# ============================================================================
# PLUGIN-003 P1 — Uninstall via API + disk cleanup
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.plugins
class TestUninstallPlugin:
    """PLUGIN-003: After DELETE the plugin disappears from list and disk."""

    @pytest.mark.test_id("PLUGIN-003")
    def test_uninstall_plugin_via_api_and_disk_cleanup(
        self,
        plugin_page: PluginPage,
        api_context,
        tmp_path: Path,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        plugin_id = _unique_plugin_id()

        log_test_step("1. Install a fixture plugin")
        zip_path = plugin_page.build_fixture_plugin_zip(tmp_path, plugin_id)
        resp = plugin_page.api_upload_plugin(api_context, zip_path)
        assert resp.ok, f"Setup install failed: {resp.status} {resp.text()}"
        install_dir = plugin_page.plugin_install_dir(plugin_id)
        assert install_dir.exists(), (
            f"Expected install dir {install_dir} to exist after upload"
        )

        log_test_step("2. DELETE /api/plugins/<id>")
        del_resp = plugin_page.api_uninstall_plugin(api_context, plugin_id)
        assert del_resp.ok, (
            f"Uninstall failed [{del_resp.status}]: {del_resp.text()}"
        )

        log_test_step("3. Plugin no longer in list")
        ids = [
            p.get("plugin_id") or p.get("id") or p.get("name")
            for p in plugin_page.api_list_plugins(api_context)
        ]
        assert plugin_id not in ids, (
            f"{plugin_id} still in plugin list after delete: {ids}"
        )

        log_test_step("4. Plugin status endpoint returns 404")
        status = plugin_page.api_get_plugin_status(api_context, plugin_id)
        assert status is None, (
            f"Expected 404 from status endpoint, got: {status}"
        )

        log_test_step("5. Install dir removed from disk")
        # Filesystem ops are sync in the loader, but allow a tiny grace.
        for _ in range(10):
            if not install_dir.exists():
                break
            time.sleep(0.2)
        assert not install_dir.exists(), (
            f"Install dir {install_dir} should have been removed"
        )

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed (id={plugin_id})")


# ============================================================================
# PLUGIN-004 P2 — Duplicate install returns 409
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.plugins
class TestInstallDuplicate:
    """PLUGIN-004: Re-uploading the same plugin id without force → 409."""

    @pytest.mark.test_id("PLUGIN-004")
    def test_install_duplicate_returns_409(
        self,
        plugin_page: PluginPage,
        api_context,
        tmp_path: Path,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        plugin_id = _unique_plugin_id()
        zip_path = plugin_page.build_fixture_plugin_zip(tmp_path, plugin_id)

        try:
            log_test_step("1. First install succeeds")
            first = plugin_page.api_upload_plugin(api_context, zip_path)
            assert first.ok, (
                f"First install must succeed: {first.status} {first.text()}"
            )

            log_test_step("2. Second install (without force) returns 409")
            second = plugin_page.api_upload_plugin(
                api_context, zip_path, force=False
            )
            assert second.status == 409, (
                f"Expected 409 on duplicate; got {second.status}: "
                f"{second.text()}"
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed (id={plugin_id})")
        finally:
            _safe_uninstall(plugin_page, api_context, plugin_id)


# ============================================================================
# PLUGIN-005 P2 — Invalid zip (no plugin.json) returns 400
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.plugins
class TestInstallInvalidZip:
    """PLUGIN-005: Uploading a zip without plugin.json → 400."""

    @pytest.mark.test_id("PLUGIN-005")
    def test_install_invalid_zip_returns_400(
        self,
        plugin_page: PluginPage,
        api_context,
        tmp_path: Path,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        log_test_step("1. Build an invalid zip (no plugin.json)")
        bad_zip = plugin_page.build_invalid_zip(tmp_path, "bad-fixture")

        log_test_step("2. Upload returns 4xx")
        resp = plugin_page.api_upload_plugin(api_context, bad_zip)
        # Backend uses 400 for missing plugin.json; accept any 4xx as a
        # contract-style assertion (we mainly want to confirm it does
        # not 200 or 5xx).
        assert 400 <= resp.status < 500, (
            f"Expected 4xx for bad zip; got {resp.status}: {resp.text()}"
        )

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed (status={resp.status})")
