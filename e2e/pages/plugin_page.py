# -*- coding: utf-8 -*-
"""
QwenPaw Plugin Manager page object.

Wraps:
- Navigation to ``/plugin-manager``
- Tab and selector anchors for the installed / official plugin lists
- Backend API helpers (install / upload / uninstall / list / status)
- A fixture-plugin builder that produces a self-contained zero-dependency
  zip on disk for use by upload tests

Cases covered:
- PLUGIN-001 P0  test_plugin_manager_page_loads
- PLUGIN-002 P0  test_install_minimal_zip_via_api
- PLUGIN-003 P1  test_uninstall_plugin_via_api_and_disk_cleanup
- PLUGIN-004 P2  test_install_duplicate_returns_409
- PLUGIN-005 P2  test_install_invalid_zip_returns_400
"""
from __future__ import annotations

import io
import json
import logging
import os
import textwrap
import zipfile
from pathlib import Path
from typing import Optional, Tuple

from playwright.sync_api import Page, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config


logger = logging.getLogger(__name__)


class PluginPage(BasePage):
    """Page object for the Plugin Manager (``/plugin-manager``)."""

    PAGE_URL = f"{config.base_url}/plugin-manager"

    # ========== Selectors (bilingual where copy is i18n-driven) ==========

    # PageHeader breadcrumb / title
    # Robust against zh/en + DOM variations: match on either an h1 or
    # the breadcrumbCurrent span, in either language.
    PAGE_TITLE_TEXT = (
        'h1:has-text("Plugin Manager"), '
        'h1:has-text("插件管理"), '
        '[class*="breadcrumbCurrent"]:has-text("Plugin Manager"), '
        '[class*="breadcrumbCurrent"]:has-text("插件管理")'
    )
    INSTALL_BTN = (
        'button:has-text("Install Plugin"), '
        'button:has-text("安装插件")'
    )
    TAB_INSTALLED = (
        '.qwenpaw-tabs-tab:has-text("Installed"), '
        '.qwenpaw-tabs-tab:has-text("已安装")'
    )
    TAB_OFFICIAL = (
        '.qwenpaw-tabs-tab:has-text("Official"), '
        '.qwenpaw-tabs-tab:has-text("官方")'
    )

    # Empty-state text inside the installed table
    EMPTY_INSTALLED = (
        'text=/(No plugins installed|暂无已安装插件)/'
    )

    # Generic table anchor (the Installed tab uses a qwenpaw Table)
    TABLE = '.qwenpaw-table'
    TABLE_ROW = '.qwenpaw-table-tbody > tr'

    # localStorage agent storage — see CodingPage for the rationale.
    LS_AGENT_KEY = "qwenpaw-agent-storage"
    LS_LAST_AGENT_KEY = "qwenpaw-last-used-agent"
    AGENT_ID_DEFAULT = "default"

    # ========== Lifecycle ==========

    _init_script_installed = False

    def _install_default_agent_init_script(self) -> None:
        """Pin selectedAgent to ``default`` for every page in this context."""
        if self._init_script_installed:
            return
        agent = self.AGENT_ID_DEFAULT
        script = (
            "(() => {"
            "  try {"
            f"    const a = '{agent}';"
            "    const blob = JSON.stringify({"
            "      state: { selectedAgent: a, agents: [], lastChatIdByAgent: {} },"
            "      version: 0"
            "    });"
            "    try { localStorage.setItem('qwenpaw-last-used-agent', a); } catch (e) {}"
            "    try { localStorage.setItem('qwenpaw-agent-storage', blob); } catch (e) {}"
            "    try { sessionStorage.setItem('qwenpaw-agent-storage', blob); } catch (e) {}"
            "  } catch (e) {}"
            "})();"
        )
        try:
            self.page.context.add_init_script(script=script)
            self._init_script_installed = True
            logger.info("Installed default-agent init script (plugins)")
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("Could not install init script: %s", exc)

    def open(self, force_default_agent: bool = True) -> "PluginPage":
        """Navigate to the Plugin Manager page."""
        if force_default_agent:
            self._install_default_agent_init_script()
        logger.info("Open Plugin Manager page")
        self.page.goto(self.PAGE_URL, wait_until="commit", timeout=self.timeout)
        # Wait until SPA chunks have settled — the Plugin Manager page
        # is route-split, so domcontentloaded fires too early.
        try:
            self.page.wait_for_load_state(
                "networkidle",
                timeout=self.timeout,
            )
        except TimeoutError:
            logger.warning("networkidle wait timed out; continuing")
        return self

    # ========== Backend API helpers ==========

    def _agent_headers(self) -> dict:
        return {"X-Agent-Id": self.AGENT_ID_DEFAULT}

    def api_list_plugins(self, api_context) -> list:
        """GET /api/plugins."""
        resp = api_context.get(
            "/api/plugins", headers=self._agent_headers()
        )
        assert resp.ok, f"List plugins failed [{resp.status}]: {resp.text()}"
        body = resp.json()
        # Backend may return list or {plugins: [...]}.
        if isinstance(body, list):
            return body
        if isinstance(body, dict) and isinstance(body.get("plugins"), list):
            return body["plugins"]
        return []

    def api_get_plugin_status(self, api_context, plugin_id: str):
        """GET /api/plugins/<id>/status — None on 404, dict otherwise."""
        resp = api_context.get(
            f"/api/plugins/{plugin_id}/status",
            headers=self._agent_headers(),
        )
        if resp.status == 404:
            return None
        assert resp.ok, f"Status failed [{resp.status}]: {resp.text()}"
        return resp.json()

    def api_upload_plugin(self, api_context, zip_path: Path, force: bool = False):
        """POST /api/plugins/upload — multipart/form-data.

        The session-level ``api_context`` injects ``Content-Type:
        application/json`` for every request, which clobbers the
        multipart boundary header and causes the backend to reject the
        upload with 422 ``file: missing``. We sidestep that by issuing
        the multipart upload through ``page.context.request`` (which
        carries no global Content-Type override) instead.
        """
        ctx = self.page.context.request
        params = {"force": "true"} if force else None
        url = f"{config.base_url}/api/plugins/upload"
        resp = ctx.post(
            url,
            multipart={
                "file": {
                    "name": zip_path.name,
                    "mimeType": "application/zip",
                    "buffer": zip_path.read_bytes(),
                },
            },
            params=params,
            headers=self._agent_headers(),
        )
        return resp

    def api_uninstall_plugin(self, api_context, plugin_id: str):
        """DELETE /api/plugins/<id>."""
        resp = api_context.delete(
            f"/api/plugins/{plugin_id}",
            headers=self._agent_headers(),
        )
        return resp

    # ========== Fixture plugin builder ==========

    @staticmethod
    def build_fixture_plugin_zip(
        target_dir: Path,
        plugin_id: str,
        plugin_type: str = "general",
    ) -> Path:
        """Build a self-contained zero-dependency plugin zip.

        The plugin contains nothing but ``plugin.json`` and an empty
        ``plugin.py`` whose ``register`` is a no-op. It does not declare
        ``requirements.txt``, does not register HTTP routers, does not
        monkey-patch core classes, and does not declare ``meta.tools`` —
        keeping side effects on the test backend minimal.

        Returns:
            Path to the resulting ``<plugin_id>.zip`` file.
        """
        target_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "id": plugin_id,
            "name": plugin_id,
            "version": "0.0.1",
            "type": plugin_type,
            "author": "e2e",
            "description": "E2E fixture plugin — no side effects.",
            "entry": {"backend": "plugin.py"},
        }
        plugin_py = textwrap.dedent(
            """\
            # E2E fixture plugin: exports a `plugin` object with a no-op
            # register(api). The loader does:
            #     module.plugin.register(api)
            # so we must surface a top-level `plugin` symbol.
            class _E2EPlugin:
                def register(self, api):
                    return None

            plugin = _E2EPlugin()
            """
        )

        zip_path = target_dir / f"{plugin_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("plugin.json", json.dumps(manifest, indent=2))
            zf.writestr("plugin.py", plugin_py)
        return zip_path

    @staticmethod
    def build_invalid_zip(target_dir: Path, name: str) -> Path:
        """Build a zip without a top-level ``plugin.json`` (illegal)."""
        target_dir.mkdir(parents=True, exist_ok=True)
        zip_path = target_dir / f"{name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("README.md", "no plugin.json here")
        return zip_path

    # ========== Disk inspection (for cleanup assertions) ==========

    @staticmethod
    def plugin_install_dir(plugin_id: str) -> Path:
        """Return the on-disk install directory for a plugin id.

        Honours ``QWENPAW_WORKING_DIR`` (used by the e2e isolated server)
        and falls back to ``~/.qwenpaw``.
        """
        working = os.getenv("QWENPAW_WORKING_DIR")
        if working:
            base = Path(working)
        else:
            base = Path.home() / ".qwenpaw"
        return base / "plugins" / plugin_id
